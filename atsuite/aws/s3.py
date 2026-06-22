import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from atsuite_sdk.storage import StorageBase

_S3_TIMEOUT = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={"max_attempts": 2},
)


class AWSS3(StorageBase):
    """AWS S3 对象存储适配器"""

    def __init__(self, bucket: str, region: str = "us-east-1"):
        self.bucket = bucket
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.client = self.create_s3_client()
        self.ensure_bucket_exists()

    def create_s3_client(self):
        return boto3.client("s3", region_name=self.region, config=_S3_TIMEOUT)

    def ensure_bucket_exists(self):
        """确保存储桶存在，如果不存在则创建"""
        try:
            self.client.head_bucket(Bucket=self.bucket)
            print(f"Bucket '{self.bucket}' already exists")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                try:
                    if self.region == "us-east-1":
                        self.client.create_bucket(Bucket=self.bucket)
                    else:
                        self.client.create_bucket(
                            Bucket=self.bucket,
                            CreateBucketConfiguration={'LocationConstraint': self.region}
                        )
                    print(f"Bucket '{self.bucket}' created successfully")
                except ClientError as create_error:
                    print(f"Error creating bucket: {create_error}")
                    raise
            else:
                raise
        except Exception as e:
            print(f"[AWSS3] ensure_bucket_exists failed (non-fatal): {e}")
            print(f"[AWSS3] Continuing without bucket verification")

    def upload(self, key: str, filepath: str):
        """上传本地文件到 S3"""
        try:
            self.client.upload_file(filepath, self.bucket, key)
            print(f"Upload {filepath} to s3://{self.bucket}/{key}")
        except ClientError as e:
            print(f"Error uploading file: {e}")
            raise

    def download(self, key: str, filepath: str):
        """从 S3 下载文件到本地"""
        try:
            self.client.download_file(self.bucket, key, filepath)
            print(f"Download s3://{self.bucket}/{key} to {filepath}")
        except ClientError as e:
            print(f"Error downloading file: {e}")
            raise

    def append(self, key: str, data) -> int:
        """
        追加数据到 S3 对象
        1. 读取现有对象
        2. 追加新数据
        3. 重新上传
        返回新的对象大小
        """
        try:
            # 尝试读取现有对象
            try:
                response = self.client.get_object(Bucket=self.bucket, Key=key)
                existing_data = response['Body'].read()
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    existing_data = b''
                else:
                    raise

            # 合并数据
            if isinstance(data, str):
                data = data.encode('utf-8')
            new_data = existing_data + data

            # 上传合并后的数据
            self.client.put_object(Bucket=self.bucket, Key=key, Body=new_data)
            
            # 返回新的位置（对象大小）
            return len(new_data)
        except ClientError as e:
            print(f"Error appending to object: {e}")
            raise

    def read(self, key: str) -> str:
        """读取 S3 对象内容为文本"""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            content = response['Body'].read().decode('utf-8')
            return content
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                print(f"No such key: {key}")
                return ""
            else:
                print(f"Error reading object: {e}")
                raise

    def deleteobj(self, key: str) -> None:
        """删除 S3 对象"""
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            print(f"Deleted s3://{self.bucket}/{key}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                print(f"No such key: {key}")
                raise
            else:
                print(f"Error deleting object: {e}")
                raise

    def clearobj(self, key: str) -> None:
        """清空 S3 对象内容（删除后重新创建空对象）"""
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            self.client.put_object(Bucket=self.bucket, Key=key, Body=b'')
            print(f"Cleared s3://{self.bucket}/{key}")
        except ClientError as e:
            print(f"Error clearing object: {e}")
            raise


if __name__ == "__main__":
    s3 = AWSS3(bucket="atsuite", region="us-east-1")
    print(s3.read("notebook/test_user_1.json"))