import alibabacloud_oss_v2 as oss
from alibabacloud_oss_v2.exceptions import OperationError

from atsuite_sdk.storage import StorageBase

class AliOSS(StorageBase):
    def __init__(self, bucket: str, location: str = "us-east-1"):
        self.bucket = bucket
        self.client = self.create_oss_client(location)
        self.ensure_bucket_exists()

    def create_oss_client(self, location: str):
        cfg = oss.config.load_default()
        cfg.connect_timeout = 300
        cfg.readwrite_timeout = 300
        cfg.region = location
        cfg.credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()
        return oss.Client(cfg)

    def ensure_bucket_exists(self):
        try:
            self.client.put_bucket(
                oss.PutBucketRequest(
                    bucket=self.bucket,
                    create_bucket_configuration=oss.CreateBucketConfiguration(
                        storage_class="Standard"
                    ),
                )
            )
        except OperationError as e:
            if e._error.code in ["BucketAlreadyExists", "BucketAlreadyOwnedByYou"]:
                pass
            else:
                raise
    
    def upload(self, key: str, filepath: str):
        result = self.client.put_object_from_file(
            oss.PutObjectRequest(
                bucket=self.bucket,
                key=key
            ),
            filepath
        )
        print(f"Upload {filepath} to {self.bucket} : {key}")

    def download(self, key: str, filepath: str):
        result = self.client.get_object(oss.GetObjectRequest(
            bucket=self.bucket,
            key=key    
        ))
        with result.body as body_stream:
            data = body_stream.read()
            with open(filepath, 'wb') as f:
                f.write(data)
            print(f"Download {self.bucket} : {key} to {filepath}")
    
    def append(self, key: str, data):
        try:
            meta = self.client.head_object(
                oss.HeadObjectRequest(bucket=self.bucket, key=key)
            )
            position = meta.content_length

        except OperationError as e:
            if e._error.code == "NoSuchKey":
                position = 0
            else:
                raise

        result = self.client.append_object(
            oss.AppendObjectRequest(
                bucket=self.bucket,
                key=key,
                position=position,
                body=data,
            )
        )
        return result.next_position
        
    def read(self, key: str):
        try:
            result = self.client.get_object(oss.GetObjectRequest(
                bucket=self.bucket,
                key=key    
            ))
        except OperationError as e:
            if e._error.code == "NoSuchKey":
                print("No such key!")
                return ""
            else:
                raise
        with result.body as body:
            content = body.read().decode("utf-8")
        return content
    
    def deleteobj(self, key: str):
        try:
            result = self.client.delete_object(oss.DeleteObjectRequest(
                bucket=self.bucket,
                key=key,
            ))
        except OperationError as e:
            if e._error.code == "NoSuchKey":
                # print("No such key!")
                return
            raise

    def clearobj(self, key: str):
        self.deleteobj(key)

        result = self.client.append_object(oss.AppendObjectRequest(
            bucket=self.bucket,
            key=key,
            position=0,
            body=None    
        ))

    def getobjsize(self, key: str) -> float:
        try:
            result = self.client.head_object(
                oss.HeadObjectRequest(
                    bucket=self.bucket,
                    key=key
                )
            )
            size_bytes = result.content_length
            return size_bytes / (1024**3)
        except OperationError as e:
            if e._error.code == "NoSuchKey":
                # print("No such key!")
                return 0.0
            raise

if __name__ == "__main__":
    a = AliOSS("atsuite")
    b = a.getobjsize("notebook/durnt.json")
    print(b)
    # c = a.deleteobj("notebook/kkk.json")
    # print("ok")