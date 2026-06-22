import os
import json
import time
from dotenv import load_dotenv

from atsuite.function import FunctionBase
from atsuite.utils import run

load_dotenv()

_FUNCTION_URL_CORS = {
    'AllowOrigins': ['*'],
    'AllowMethods': ['*'],
    'AllowHeaders': ['*'],
    'MaxAge': 86400,
}

_PUBLIC_FUNCTION_URL_STATEMENT_IDS = (
    'FunctionURLAllowPublicAccess',
    'FunctionURLAllowPublicInvoke',
)


class AWSLambda(FunctionBase):
    """AWS Lambda 函数部署类，负责将 Docker 镜像部署到 AWS Lambda"""
    
    def __init__(
        self,
        function_name: str,
        entrypoint: list,
        tag: str,
        lambda_client,
        ecr_client,
        region: str,
        iam_client=None,
        runtime: str = 'custom-container',
        cpu: int = 1,
        memory_size: int = 1024,
        timeout: int = 60,
        disk_size: int = 512,
    ):
        self.lambda_client = lambda_client
        self.ecr_client = ecr_client
        self.iam_client = iam_client
        self.region = region
        self.url = None
        self.function_name = function_name
        self.entrypoint = entrypoint
        self.tag = tag
        self.runtime = runtime
        self.cpu = cpu
        self.memory_size = min(max(memory_size, 128), 10240)  # Lambda 限制
        self.timeout = min(max(timeout, 1), 900)  # Lambda 限制
        self.disk_size = min(max(disk_size, 512), 10240)  # Lambda 限制
        
        # 从环境变量获取配置
        self.account_id = os.environ["AWS_ACCOUNT_ID"]
        self.repository_name = os.environ["ECR_REPOSITORY_NAME"]
        self.lambda_role_arn = os.environ.get(
            "AWS_LAMBDA_ROLE_ARN",
            f"arn:aws:iam::{self.account_id}:role/atsuite-lambda-execution-role"
        )
        self.xray_policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"

    def deploy(self) -> str:
        # 推送镜像到 ECR
        image_uri = self.create_ecr(self.tag)
        
        #  创建或更新 Lambda 函数
        self.create_or_update_function(image_uri=image_uri)
        
        #  创建 Function URL
        self.url = self.create_function_url()
        
        print(f"\n\n Success deploy on AWS Lambda\n")
        print(f"Function URL: {self.url}\n")
        return self.url

    @staticmethod
    def _role_name_from_arn(role_arn: str) -> str:
        return str(role_arn).rsplit("/", 1)[-1]

    def ensure_xray_write_access(self, role_arn: str | None = None) -> None:
        if self.iam_client is None:
            print(
                "Lambda Warning: iam_client not provided, skipping X-Ray role policy check"
            )
            return

        role_name = self._role_name_from_arn(role_arn or self.lambda_role_arn)
        attached_policy_arns = set()
        marker = None
        while True:
            kwargs = {"RoleName": role_name}
            if marker:
                kwargs["Marker"] = marker
            response = self.iam_client.list_attached_role_policies(**kwargs)
            for policy in response.get("AttachedPolicies", []):
                policy_arn = policy.get("PolicyArn")
                if policy_arn:
                    attached_policy_arns.add(str(policy_arn))
            if not response.get("IsTruncated"):
                break
            marker = response.get("Marker")

        if self.xray_policy_arn in attached_policy_arns:
            print(f"Lambda X-Ray policy already attached to role '{role_name}'")
            return

        print(f"Lambda Attaching AWSXRayDaemonWriteAccess to role '{role_name}'...")
        self.iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn=self.xray_policy_arn,
        )
        print(f"Lambda Attached AWSXRayDaemonWriteAccess to role '{role_name}'")

    def create_ecr(self, tag: str) -> str:
        docker_image_name = f"{tag}:latest"
        ecr_uri = f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/{self.repository_name}"
        full_image_uri = f"{ecr_uri}:{tag}"
        
        print(f"ECR Pushing image to {full_image_uri}")
        
        #  获取 ECR 登录密码
        import subprocess
        
        try:
            response = self.ecr_client.get_authorization_token()
            auth_data = response['authorizationData'][0]
            token = auth_data['authorizationToken']
            
            import base64
            username, password = base64.b64decode(token).decode('utf-8').split(':')
            
            # 登录 ECR
            subprocess.run(
                [
                    "docker", "login",
                    "--username", username,
                    "--password-stdin",
                    f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com"
                ],
                input=password.encode(),
                check=True
            )
            
        except Exception as e:
            print(f"ECR Warning: Failed to login via API, trying AWS CLI: {e}")
            # 备用方案：使用 AWS CLI
            password_result = subprocess.run(
                ["aws", "ecr", "get-login-password", "--region", self.region],
                capture_output=True,
                text=True,
                check=True
            )
            # 登录 Docker
            subprocess.run(
                [
                    "docker", "login",
                    "--username", "AWS",
                    "--password-stdin",
                    f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com"
                ],
                input=password_result.stdout.strip().encode(),
                check=True
            )
        
        # 确保 ECR 仓库存在，不存在则自动创建
        try:
            self.ecr_client.describe_repositories(
                repositoryNames=[self.repository_name]
            )
            print(f"[ECR] Repository '{self.repository_name}' exists")
        except self.ecr_client.exceptions.RepositoryNotFoundException:
            print(f"[ECR] Creating repository '{self.repository_name}'...")
            self.ecr_client.create_repository(
                repositoryName=self.repository_name,
                imageScanningConfiguration={"scanOnPush": False},
            )
            print(f"[ECR] Repository created")
        
        # 给本地镜像打标签
        print(f"ECR Tagging image: {docker_image_name} -> {full_image_uri}")
        run([
            "docker", "tag",
            docker_image_name,
            full_image_uri
        ])
        
        # 推送到 ECR
        print(f"ECR Pushing image to ECR...")
        run([
            "docker", "push",
            full_image_uri
        ])
        
        print(f"[ECR]  Image pushed successfully")
        return full_image_uri

    def create_or_update_function(self, image_uri: str):
        """
        创建或更新 Lambda 函数
        """
        try:
            # 尝试获取现有函数
            print(f"Lambda Checking if function '{self.function_name}' exists...")
            response = self.lambda_client.get_function(FunctionName=self.function_name)
            function_role_arn = (
                response.get("Configuration", {}).get("Role")
                or self.lambda_role_arn
            )
            if function_role_arn != self.lambda_role_arn:
                print(
                    "Lambda Function role differs from configured AWS_LAMBDA_ROLE_ARN; "
                    f"using active role '{function_role_arn}' for X-Ray policy attachment"
                )
            self.ensure_xray_write_access(function_role_arn)
            
            # 函数已存在，更新代码
            print(f"Lambda Function exists, updating code and configuration...")
            self.lambda_client.update_function_code(
                FunctionName=self.function_name,
                ImageUri=image_uri
            )
            
            # 等待更新完成
            waiter = self.lambda_client.get_waiter('function_updated')
            waiter.wait(FunctionName=self.function_name)
            
            # 更新配置
            self.lambda_client.update_function_configuration(
                FunctionName=self.function_name,
                MemorySize=self.memory_size,
                Timeout=self.timeout,
                EphemeralStorage={'Size': self.disk_size},
                TracingConfig={'Mode': 'Active'},
            )

            # 等待配置更新完成，避免后续操作（如 create_function_url）触发 ResourceConflictException
            waiter = self.lambda_client.get_waiter('function_updated')
            waiter.wait(FunctionName=self.function_name)
            
            print(f"Lambda Function updated successfully")
            
        except self.lambda_client.exceptions.ResourceNotFoundException:
            # 函数不存在，创建新函数
            self.ensure_xray_write_access(self.lambda_role_arn)
            print(f"Lambda Function does not exist, creating new function...")
            self.create_function(image_uri)

    def create_function(self, image_uri: str):
        try:
            response = self.lambda_client.create_function(
                FunctionName=self.function_name,
                Role=self.lambda_role_arn,  # IAM 角色 ARN
                Code={
                    'ImageUri': image_uri  # ECR 镜像地址
                },
                PackageType='Image',  # 使用容器镜像
                Description=f"{self.function_name}'s Lambda function",
                MemorySize=self.memory_size,  
                Timeout=self.timeout,  
                Architectures=['x86_64'],  
                EphemeralStorage={
                    'Size': self.disk_size  
                },
                TracingConfig={'Mode': 'Active'},
            )
            
            waiter = self.lambda_client.get_waiter('function_active')
            waiter.wait(FunctionName=self.function_name)
            
            print(f"Lambda Function created successfully")
            
        except Exception as error:
            print(f"Lambda Error creating function: {error}")
            raise

    def create_function_url(self) -> str:
        """
        创建 Function URL   
        """
        try:
            # 尝试获取现有的 Function URL
            print(f"Lambda Checking if function URL exists...")
            response = self.lambda_client.get_function_url_config(
                FunctionName=self.function_name
            )
            url = response['FunctionUrl']
            auth_type = response.get('AuthType')
            if auth_type != 'AWS_IAM':
                print(f"Lambda Function URL auth is {auth_type}, updating to AWS_IAM...")
                response = self.lambda_client.update_function_url_config(
                    FunctionName=self.function_name,
                    AuthType='AWS_IAM',
                    Cors=_FUNCTION_URL_CORS,
                )
                url = response['FunctionUrl']
                self._remove_legacy_public_permissions()
            print(f"Lambda Function URL already exists: {url}")
            return url
            
        except self.lambda_client.exceptions.ResourceNotFoundException:
            # Function URL 不存在，创建新的
            print(f" Creating Function URL...")
            
            try:
                response = self.lambda_client.create_function_url_config(
                    FunctionName=self.function_name,
                    AuthType='AWS_IAM',
                    Cors=_FUNCTION_URL_CORS,
                )
                url = response['FunctionUrl']

                print(f"Lambda Function URL created: {url}")
                return url
                
            except Exception as error:
                print(f"Lambda Error creating Function URL: {error}")
                raise

    def _remove_legacy_public_permissions(self) -> None:
        for statement_id in _PUBLIC_FUNCTION_URL_STATEMENT_IDS:
            try:
                self.lambda_client.remove_permission(
                    FunctionName=self.function_name,
                    StatementId=statement_id,
                )
            except Exception:
                # Older deployments might not have one or both public statements.
                continue
