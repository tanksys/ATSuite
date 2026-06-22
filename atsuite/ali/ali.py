import os
from dotenv import load_dotenv

from alibabacloud_fc20230330.client import Client as FC20230330Client
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_fc20230330 import models as fc20230330_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_openapi import models as open_api_models

from atsuite.ali.fc import AliFC

load_dotenv()


class Ali:
    def __init__(
        self,
    ):
        self.fc_client: FC20230330Client | None = None

    def get_fc_client(self) -> FC20230330Client:
        if self.fc_client is None:
            credential = CredentialClient()
            config = open_api_models.Config(
                credential=credential
            )
            config.endpoint=os.environ["ALI_ENDPOINT"]
            self.fc_client = FC20230330Client(config)
        return self.fc_client
    
    def deploy_function(self, **kwargs) -> AliFC:
        return AliFC(
            client=self.get_fc_client(),
            typ = "function",
            **kwargs
        )
    
    def deploy_mcp(self, **kwargs) -> AliFC:
        return AliFC(
            client=self.get_fc_client(),
            typ = "mcp",
            **kwargs
        )

    @staticmethod
    def create_scalingconfig(client, function_name, num):
        put_scaling_config_input = fc20230330_models.PutScalingConfigInput(
                min_instances=num
            )
        put_scaling_config_request = fc20230330_models.PutScalingConfigRequest(
            body=put_scaling_config_input
        )
        runtime = util_models.RuntimeOptions()
        headers = {}     

        try:
            resp = client.put_scaling_config_with_options(function_name, put_scaling_config_request, headers, runtime)
        except Exception as error:
            pass
            # print(error.message)
            # print(error.data.get("Recommend"))
    
    @staticmethod
    def delete_scalingconfig(client, function_name):
        delete_scaling_config_request = fc20230330_models.DeleteScalingConfigRequest(
            qualifier='LATEST'
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            resp = client.delete_scaling_config_with_options(function_name, delete_scaling_config_request, headers, runtime)
        except Exception as error:
            pass
            # print(error.message)
            # print(error.data.get("Recommend"))