import os
from dotenv import load_dotenv

from alibabacloud_fc20230330 import models as fc20230330_models
from alibabacloud_fc20230330.client import Client as FC20230330Client
from alibabacloud_tea_util import models as util_models

from atsuite.function import FunctionBase
from atsuite.utils import run
from atsuite.ali.sls import AliSLS

load_dotenv()


class AliFC(FunctionBase):
    def __init__(
        self,
        function_name: str,
        entrypoint: list,
        tag: str,
        client: FC20230330Client,
        typ: str = "function",
        runtime: str = 'custom-container',
        cpu: int = 1,
        memory_size: int = 1024,
        disk_size: int = 512,
        timeout: int = 60,
        trigger_type: str = 'http',
        trigger_config: str = '{"authType":"anonymous","disableURLInternet":false,"methods":["GET","POST","PUT","DELETE"]}'        
    ):
        self.client = client
        self.typ = typ
        self.url = None
        self.function_name = f"{function_name}-{self.typ}"
        self.entrypoint = entrypoint
        self.tag = tag
        self.runtime = runtime
        self.cpu = cpu
        self.memory_size = memory_size
        self.disk_size = disk_size
        self.timeout = timeout
        self.trigger_type = trigger_type
        self.trigger_config = trigger_config

    def deploy(self) -> str:
        image_addr = self.push_image(self.tag)
        sls = AliSLS(
            project='atsuite',
            location='us-east-1'
        )
        sls.create_project()
        sls.create_logstore(self.function_name)
        self.create_function(image=image_addr)
        self.url = self.create_trigger()
        print("\n\n Success deploy on AliFC \n\n")
        return self.url

    @staticmethod
    def push_image(tag: str) -> str:
        docker_image_name = f"{tag}:latest"
        dockerhub_name = os.environ["DOCKERHUB_NAME"]
        run([
            "docker",
            "tag",
            docker_image_name,
            f"{dockerhub_name}:{tag}",
        ])
        run([
            "docker",
            "push",
            f"{dockerhub_name}:{tag}",
        ])
        return f"{dockerhub_name}:{tag}"

    def create_function(self, image: str):
        port = 9000 if self.typ == "function" else 8000
        create_function_input_custom_container_config = fc20230330_models.CustomContainerConfig(
            entrypoint=self.entrypoint,
            image=image,
            port=port
        )
        create_function_input_environment_variables = {
            'OSS_ACCESS_KEY_ID': os.environ["OSS_ACCESS_KEY_ID"],
            'OSS_ACCESS_KEY_SECRET': os.environ["OSS_ACCESS_KEY_SECRET"]
        }
        create_function_input_log_config = fc20230330_models.LogConfig(
            enable_instance_metrics=True,
            enable_request_metrics=True,
            logstore=self.function_name,
            project='atsuite'
        )
        if self.typ == "mcp":
            # self.cpu = max(2, self.cpu)
            # self.memory_size = max(self.cpu * 1024, self.memory_size)
            kwargs = dict(
                cpu=self.cpu,
                description=f"{self.function_name}'s mcp server",
                function_name=self.function_name,
                runtime=self.runtime,
                timeout=self.timeout,
                disk_size=self.disk_size,
                memory_size=self.memory_size,
                custom_container_config=create_function_input_custom_container_config,
                environment_variables=create_function_input_environment_variables,
                session_affinity='MCP_STREAMABLE',
                instance_isolation_mode='SESSION_EXCLUSIVE',
                instance_concurrency=200,
                session_affinity_config='{"sessionConcurrencyPerInstance":1, "SessionTTLInSeconds": 1800, "SessionIdleTimeoutInSeconds": 300}',
                log_config=create_function_input_log_config
            )
        elif self.typ == "function":
            kwargs = dict(
                cpu=self.cpu,
                description=f"{self.function_name}'s function",
                function_name=self.function_name,
                runtime=self.runtime,
                timeout=self.timeout,
                disk_size=self.disk_size,
                memory_size=self.memory_size,
                custom_container_config=create_function_input_custom_container_config,
                environment_variables=create_function_input_environment_variables,
                instance_concurrency=200,
                log_config=create_function_input_log_config
            )
                        
        create_function_input = fc20230330_models.CreateFunctionInput(**kwargs)
        create_function_request = fc20230330_models.CreateFunctionRequest(
            body=create_function_input
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            resp = self.client.create_function_with_options(create_function_request, headers, runtime)
            # print(json.dumps(resp, default=str, indent=2))
        except Exception as error:
            print(error.message)
            print(error.data.get("Recommend"))     
    
    def create_trigger(self) -> str:
        trigger_name = f"{self.function_name}-trigger"
        create_trigger_input = fc20230330_models.CreateTriggerInput(
                description=f'The trigger of {self.function_name}',
                trigger_type=self.trigger_type,
                trigger_name=trigger_name,
                trigger_config=self.trigger_config
            )
        create_trigger_request = fc20230330_models.CreateTriggerRequest(
            body=create_trigger_input
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            resp = self.client.create_trigger_with_options(self.function_name, create_trigger_request, headers, runtime)
            # print(json.dumps(resp, default=str, indent=2))
        except Exception as error:
            print(error.message)
            print(error.data.get("Recommend"))

        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            resp = self.client.get_trigger_with_options(self.function_name, trigger_name, headers, runtime)
            return resp.body.http_trigger.url_internet

        except Exception as error:
            print(error.message)
            print(error.data.get("Recommend"))
