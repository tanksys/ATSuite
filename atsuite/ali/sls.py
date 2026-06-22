import time
import json

from alibabacloud_sls20201230.client import Client as Sls20201230Client
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_sls20201230 import models as sls_20201230_models
from alibabacloud_tea_util import models as util_models

TK = [',', ' ', '\'', '"', ';', '=', '(', ')', '[', ']', '{', '}', '?', '@', '&', '<', '>', '/', ':', '\n', '\t', '\r']

class AliSLS:
    def __init__(self, project: str = "atsuite", location: str = "us-east-1"):
        self.project = project
        self.location = location
        self.client = self.create_sls_client()

    def create_sls_client(self):
        credential = CredentialClient()
        config = open_api_models.Config(
            credential=credential
        )
        config.endpoint = f'{self.location}.log.aliyuncs.com'
        return Sls20201230Client(config)
    
    def create_project(self):
        create_project_request = sls_20201230_models.CreateProjectRequest(
            description=f'{self.project} sls',
            project_name=self.project
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            resp = self.client.create_project_with_options(create_project_request, headers, runtime)
            # print(json.dumps(resp, default=str, indent=2))
        except Exception as error:
            print(error.message)
            # print(error.data.get("Recommend"))

    def create_index(self, logstore):
        index_line = sls_20201230_models.IndexLine(
            case_sensitive=False,
            token=TK,
            chn=False
        )
        index_index_key_version_id = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_tx_total_bytes = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='long',
            doc_value=True
        )
        index_index_key_tx_bytes = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='long',
            doc_value=True
        )
        index_index_key_trigger_type = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_requestId = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_status_code = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='long',
            doc_value=True
        )
        index_index_key_service_name = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=True,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_rx_total_bytes = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='long',
            doc_value=True
        )
        index_index_key_rx_bytes = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='long',
            doc_value=True
        )
        index_index_key_qualifier = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=True,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_operation = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_memory_usage_percent = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_memory_usage_mb = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_memory_limit_mb = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_is_cold_start = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_ip_address = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_instance_id = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_hostname = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_has_function_error = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_function_name = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=True,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_error_type = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='text',
            doc_value=True,
            token=TK,
        )
        index_index_key_duration_ms = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_coldStartLatencyMs = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_invokeFunctionLatencyMs = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_prepareCodeLatencyMs = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_runtimeInitializationMs = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_scheduleLatencyMs = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_cpu_quota_percent = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_cpu_percent = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='double',
            doc_value=True
        )
        index_index_key_concurrent_requests = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='long',
            doc_value=True
        )
        index_index_key_agg_period_seconds = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='long',
            doc_value=True
        )
        index_index_key_start_time = sls_20201230_models.IndexKey(
            chn=False,
            case_sensitive=False,
            type='long',
            doc_value=True
        )
        index_keys = {
            'aggPeriodSeconds': index_index_key_agg_period_seconds,
            'concurrentRequests': index_index_key_concurrent_requests,
            'cpuPercent': index_index_key_cpu_percent,
            'cpuQuotaPercent': index_index_key_cpu_quota_percent,
            'durationMs': index_index_key_duration_ms,
            'errorType': index_index_key_error_type,
            'functionName': index_index_key_function_name,
            'hasFunctionError': index_index_key_has_function_error,
            'hostname': index_index_key_hostname,
            'instanceID': index_index_key_instance_id,
            'ipAddress': index_index_key_ip_address,
            'isColdStart': index_index_key_is_cold_start,
            'memoryLimitMB': index_index_key_memory_limit_mb,
            'memoryUsageMB': index_index_key_memory_usage_mb,
            'memoryUsagePercent': index_index_key_memory_usage_percent,
            'operation': index_index_key_operation,
            'qualifier': index_index_key_qualifier,
            'rxBytes': index_index_key_rx_bytes,
            'rxTotalBytes': index_index_key_rx_total_bytes,
            'serviceName': index_index_key_service_name,
            'statusCode': index_index_key_status_code,
            'triggerType': index_index_key_trigger_type,
            'txBytes': index_index_key_tx_bytes,
            'txTotalBytes': index_index_key_tx_total_bytes,
            'versionId': index_index_key_version_id,
            'coldStartLatencyMs': index_index_key_coldStartLatencyMs,
            'invokeFunctionLatencyMs': index_index_key_invokeFunctionLatencyMs, 
            'prepareCodeLatencyMs': index_index_key_prepareCodeLatencyMs, 
            'runtimeInitializationMs': index_index_key_runtimeInitializationMs, 
            'scheduleLatencyMs': index_index_key_scheduleLatencyMs,
            'requestId': index_index_key_requestId,
            'invokeFunctionStartTimestamp': index_index_key_start_time
        }
        index = sls_20201230_models.Index(
            keys=index_keys,
            log_reduce=False,
            line=index_line,
            scan_index=False
        )
        create_index_request = sls_20201230_models.CreateIndexRequest(
            body=index
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            resp = self.client.create_index_with_options(self.project, logstore, create_index_request, headers, runtime)
            # print(json.dumps(resp, default=str, indent=2))
        except Exception as error:
            print(error.message)
            # print(error.data.get("Recommend"))
    
    def create_logstore(self, logstore):
        create_log_store_request = sls_20201230_models.CreateLogStoreRequest(
            logstore_name=logstore,
            shard_count=2,
            ttl=2,
            auto_split=True,
            enable_tracking=False,
            max_split_shard=64,
            append_meta=False,
            mode='standard'
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            resp = self.client.create_log_store_with_options(self.project, create_log_store_request, headers, runtime)
            # print(json.dumps(resp, default=str, indent=2))
        except Exception as error:
            print(error.message)
            # print(error.data.get("Recommend"))
        self.create_index(logstore)

    def getlogs(self, logstore, _from, _to, query):
        try:
            get_logs_request = sls_20201230_models.GetLogsRequest(
                    from_=_from,
                    to=_to,
                    query=query
                )
            runtime = util_models.RuntimeOptions()
            headers = {}
            resp = self.client.get_logs_with_options(self.project, logstore, get_logs_request, headers, runtime)

            data = resp.body
            if data:
                row = data[0]
                values = json.loads(row["_col0"]) if "_col0" in row else row
                return {
                    "duration_ms": values[0] if isinstance(values, list) else values.get("durationms"),
                    "memory_usage_mb": values[1] if isinstance(values, list) else values.get("memoryusagemb"),
                    "is_cold_start": values[2] if isinstance(values, list) else values.get("iscoldstart"),
                    "cold_start_latency_ms": values[3] if isinstance(values, list) else values.get("coldStartLatencyMs"),
                    "invoke_function_latency_ms": values[4] if isinstance(values, list) else values.get("invokeFunctionLatencyMs"),
                    "prepare_code_latency_ms": values[5] if isinstance(values, list) else values.get("prepareCodeLatencyMs"),
                    "runtime_initialization_ms": values[6] if isinstance(values, list) else values.get("runtimeInitializationMs"),
                    "schedule_latency_ms": values[7] if isinstance(values, list) else values.get("scheduleLatencyMs"),
                    "invoker_function_ms": values[7] + values[0] if isinstance(values, list) else float(values.get("scheduleLatencyMs", 0)) + float(values.get("durationms", 0)),
                    "invokeFunctionStartTimestamp": values[8] if isinstance(values, list) else values.get("invokeFunctionStartTimestamp"),
                }
            else:
                return None
        except Exception as e:
            print(f"Error querying SLS: {e}")
            return None

    def getbreakdownlogs(self, logstore, _from, _to, query):
        offset = 0
        log_line = 100
        result = []
        try:
            while True:
                resp = None
                for retry_time in range(0, 3):
                    get_logs_request = sls_20201230_models.GetLogsRequest(
                        from_=_from, to=_to, line=log_line, offset=offset, query=query
                    )
                    runtime = util_models.RuntimeOptions()
                    headers = {}
                    resp = self.client.get_logs_with_options(
                        self.project, logstore, get_logs_request, headers, runtime
                    )
                    if (
                        resp is not None
                        and resp.headers.get("x-log-progress") == "Complete"
                    ):
                        break
                    time.sleep(1)
                offset += 100
                data = resp.body if resp else []
                if resp.headers.get("x-log-progress") == "Complete" and len(data) == 0:
                    break
                if resp is not None:
                    for d in data:
                        msg = d.get("message", "")
                        for line in msg.splitlines():
                            if "app_e2e_ms" in line:
                                try:
                                    result.append(json.loads(line))
                                except json.JSONDecodeError:
                                    pass

            return result

        except Exception as e:
            print(f"Error querying SLS: {e}")
            return None


if __name__ == "__main__":
    a = AliSLS()
    b = a.getbreakdownlogs(
        "wikipedia-mcp",
        int(time.time()) - 160000,
        int(time.time()) - 50000,
        '__topic__:"FCLogs:wikipedia-mcp"',
    )
    # print(b)
    print(len(b))
