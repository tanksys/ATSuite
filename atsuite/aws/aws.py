import os
import boto3
from dotenv import load_dotenv

from atsuite.aws.Lambda import AWSLambda
from atsuite.aws.Agentcore import AWSAgentCore

load_dotenv()


class AWS:
    """AWS 客户端管理类，负责创建和管理 AWS 服务客户端"""

    def __init__(self):
        self.lambda_client = None
        self.ecr_client = None
        self.iam_client = None
        self.agentcore_client = None
        self.region = os.environ.get("AWS_REGION", "us-east-1")

        self._validate_credentials()

    def _validate_credentials(self):
        """验证 AWS 凭证是否配置"""
        required_vars = ["AWS_ACCOUNT_ID", "ECR_REPOSITORY_NAME"]
        missing = [var for var in required_vars if not os.environ.get(var)]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Please set them in your .env file or environment."
            )

    def get_lambda_client(self):
        if self.lambda_client is None:
            self.lambda_client = boto3.client("lambda", region_name=self.region)
        return self.lambda_client

    def get_ecr_client(self):
        if self.ecr_client is None:
            self.ecr_client = boto3.client("ecr", region_name=self.region)
        return self.ecr_client

    def get_iam_client(self):
        if self.iam_client is None:
            self.iam_client = boto3.client("iam")
        return self.iam_client

    def get_agentcore_client(self):
        """获取 AWS Bedrock AgentCore 控制平面客户端"""
        if self.agentcore_client is None:
            self.agentcore_client = boto3.client(
                "bedrock-agentcore-control", region_name=self.region
            )
        return self.agentcore_client

    def deploy_lambda(self, **kwargs) -> AWSLambda:
        return AWSLambda(
            lambda_client=self.get_lambda_client(),
            ecr_client=self.get_ecr_client(),
            iam_client=self.get_iam_client(),
            region=self.region,
            **kwargs,
        )

    def deploy_agentcore(self, node_name: str, tag: str, **kwargs) -> AWSAgentCore:
        return AWSAgentCore(
            node_name=node_name,
            tag=tag,
            ecr_client=self.get_ecr_client(),
            agentcore_client=self.get_agentcore_client(),
            region=self.region,
            **kwargs,
        )
