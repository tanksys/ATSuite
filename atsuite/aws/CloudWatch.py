import json as _json
import os
import time

import boto3
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from datetime import timedelta


class AWSCloudWatch:
    """AWS CloudWatch 指标查询类,支持 Lambda 和 AgentCore"""

    RESOURCE_CONFIG = {
        'lambda': {
            'namespace': 'AWS/Lambda',
            'dimension_name': 'FunctionName',
            'log_group_template': '/aws/lambda/{name}',
        },
        'agentcore': {
            'namespace': 'AWS/Bedrock-AgentCore',
            'dimension_name': 'Name',
            'log_group_template': '/aws/bedrock-agentcore/runtimes/{name}',
        },
    }

    def __init__(self, region: str = "us-east-1"):
        self.cloudwatch = boto3.client("cloudwatch", region_name=region)
        self.logs = boto3.client("logs", region_name=region)
        self.xray = boto3.client("xray", region_name=region)
        self.region = region
        self.xray_poll_window_s = self._read_float_env(
            "ATSUITE_AWS_XRAY_POLL_WINDOW_S",
            30.0,
        )
        self.xray_poll_interval_s = self._read_float_env(
            "ATSUITE_AWS_XRAY_POLL_INTERVAL_S",
            3.0,
        )
        self._agentcore_runtime_log_groups_cache: Dict[str, List[str]] = {}

    @staticmethod
    def _read_float_env(env_name: str, default: float) -> float:
        raw_value = os.environ.get(env_name)
        if raw_value in (None, ""):
            return default
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return default

    def _get_trace_segment_destination(self) -> str:
        cached = getattr(self, "_trace_segment_destination", None)
        if cached:
            return str(cached)

        xray = getattr(self, "xray", None)
        get_destination = getattr(xray, "get_trace_segment_destination", None)
        if not callable(get_destination):
            self._trace_segment_destination = "XRay"
            return "XRay"

        try:
            response = get_destination()
        except Exception:
            self._trace_segment_destination = "XRay"
            return "XRay"

        destination = str(response.get("Destination") or "XRay")
        self._trace_segment_destination = destination
        return destination

    # ==================== 日志查询 ====================

    def _filter_log_group_events(
        self,
        log_group: str,
        start_time: datetime,
        end_time: datetime,
        request_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        filter_pattern = f'"{request_id}"' if request_id else ""
        all_events: List[Dict] = []
        kwargs = {
            'logGroupName': log_group,
            'startTime': int(start_time.timestamp() * 1000),
            'endTime': int(end_time.timestamp() * 1000),
            'filterPattern': filter_pattern,
        }
        while True:
            response = self.logs.filter_log_events(**kwargs)
            all_events.extend(response.get('events', []))
            next_token = response.get('nextToken')
            if not next_token:
                break
            kwargs['nextToken'] = next_token
        return all_events

    @staticmethod
    def _score_agentcore_runtime_log_group(log_group: str, runtime_id: str) -> tuple:
        return (
            0 if '/APP_LOGS/' in log_group else 1,
            0 if '/APPLICATION_LOGS/' in log_group else 1,
            0 if log_group.endswith(f'/{runtime_id}') else 1,
            0 if f'/{runtime_id}' in log_group else 1,
            len(log_group),
            log_group,
        )

    def discover_agentcore_runtime_log_groups(self, runtime_id: str) -> List[str]:
        cache = getattr(self, '_agentcore_runtime_log_groups_cache', None)
        if cache is None:
            cache = {}
            self._agentcore_runtime_log_groups_cache = cache

        cached = cache.get(runtime_id)
        if cached is not None:
            return list(cached)

        prefixes = (
            '/aws/vendedlogs/bedrock-agentcore/runtime/',
            '/aws/bedrock-agentcore/runtime/',
            '/aws/bedrock-agentcore/runtimes/',
            '/aws/vendedlogs/bedrock-agentcore/runtimes/',
        )

        candidates: Dict[str, tuple] = {}
        try:
            for prefix in prefixes:
                kwargs = {'logGroupNamePrefix': prefix}
                while True:
                    resp = self.logs.describe_log_groups(**kwargs)
                    for lg in resp.get('logGroups', []):
                        log_group = lg.get('logGroupName', '')
                        if runtime_id not in log_group:
                            continue
                        if '/USAGE_LOGS/' in log_group:
                            continue
                        candidates[log_group] = self._score_agentcore_runtime_log_group(
                            log_group, runtime_id
                        )
                    next_token = resp.get('nextToken')
                    if not next_token:
                        break
                    kwargs['nextToken'] = next_token
        except Exception as e:
            print(f"    [agentcore-logs] Error discovering runtime log groups for {runtime_id}: {e}")
            cache[runtime_id] = []
            return []

        groups = [
            name for name, _ in sorted(candidates.items(), key=lambda item: item[1])
        ]
        cache[runtime_id] = groups
        if groups:
            print(
                f"    [agentcore-logs] Discovered {len(groups)} runtime log group(s) for {runtime_id}: "
                + ", ".join(groups)
            )
        else:
            print(f"    [agentcore-logs] No runtime log groups found for {runtime_id}")
        return list(groups)

    def discover_agentcore_usage_log_groups(self, runtime_id: str) -> List[str]:
        prefixes = (
            '/aws/vendedlogs/bedrock-agentcore/runtime/USAGE_LOGS/',
            '/aws/bedrock-agentcore/runtime/USAGE_LOGS/',
            '/aws/vendedlogs/bedrock-agentcore/runtimes/USAGE_LOGS/',
            '/aws/bedrock-agentcore/runtimes/USAGE_LOGS/',
        )

        candidates: Dict[str, tuple] = {}
        try:
            for prefix in prefixes:
                kwargs = {'logGroupNamePrefix': prefix}
                while True:
                    resp = self.logs.describe_log_groups(**kwargs)
                    for lg in resp.get('logGroups', []):
                        log_group = lg.get('logGroupName', '')
                        if not log_group.endswith(f'/{runtime_id}'):
                            continue
                        candidates[log_group] = (len(log_group), log_group)
                    next_token = resp.get('nextToken')
                    if not next_token:
                        break
                    kwargs['nextToken'] = next_token
        except Exception as e:
            print(f"    [usage-logs] Error discovering log groups for {runtime_id}: {e}")
            return []

        return [name for name, _ in sorted(candidates.items(), key=lambda item: item[1])]

    def get_logs(
        self,
        resource_type: str,
        resource_name: str,
        start_time: datetime,
        end_time: datetime,
        request_id: Optional[str] = None,
        log_group_override: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取资源的 CloudWatch 日志"""
        try:
            if log_group_override:
                log_groups = [log_group_override]
            elif resource_type == 'agentcore':
                log_groups = self.discover_agentcore_runtime_log_groups(resource_name)
                if not log_groups:
                    return []
            else:
                config = self._get_config(resource_type)
                log_groups = [config['log_group_template'].format(name=resource_name)]

            all_events: List[Dict] = []
            for log_group in log_groups:
                all_events.extend(
                    self._filter_log_group_events(
                        log_group,
                        start_time,
                        end_time,
                        request_id=request_id,
                    )
                )
            return all_events
        except Exception as e:
            print(f"Error getting logs for {resource_type}/{resource_name}: {e}")
            return []

    # ==================== 日志解析 ====================

    def parse_logs(self, resource_type: str, logs: List[Dict]) -> Dict[str, Any]:
        """解析日志，提取性能指标,目前仅支持 Lambda REPORT 行"""
        if resource_type == 'lambda':
            return self._parse_lambda_logs(logs)
        raise ValueError(f"parse_logs not implemented for resource_type: {resource_type}")

    def _parse_lambda_logs(self, logs: List[Dict]) -> Dict[str, Any]:
        """解析 Lambda REPORT / INIT_REPORT 日志行"""
        metrics: Dict[str, Any] = {
            'duration_ms': None,
            'billed_duration_ms': None,
            'memory_used_mb': None,
            'memory_limit_mb': None,
            'is_cold_start': False,
            'init_duration_ms': None,
            'report_request_id': None,
            'xray_trace_id': None,
            'xray_sampled': None,
        }
        for log in logs:
            message = log.get('message', '')
            if 'REPORT' not in message:
                continue

            # INIT_REPORT 行: init 超时时 Init Duration 在此行，不在 REPORT 行
            if message.startswith('INIT_REPORT'):
                for part in message.split('\t'):
                    part = part.strip()
                    if 'Init Duration:' in part:
                        val = part.split('Init Duration:')[1].strip().split()[0]
                        metrics['init_duration_ms'] = float(val)
                        metrics['is_cold_start'] = True
                continue

            for part in message.split('\t'):
                part = part.strip()
                if part.startswith('REPORT RequestId:'):
                    metrics['report_request_id'] = part.split(':', 1)[1].strip().split()[0]
                elif part.startswith('Duration:'):
                    metrics['duration_ms'] = float(part.split(':')[1].strip().split()[0])
                elif part.startswith('Billed Duration:'):
                    metrics['billed_duration_ms'] = float(part.split(':')[1].strip().split()[0])
                elif part.startswith('Memory Size:'):
                    metrics['memory_limit_mb'] = int(part.split(':')[1].strip().split()[0])
                elif part.startswith('Max Memory Used:'):
                    metrics['memory_used_mb'] = int(part.split(':')[1].strip().split()[0])
                elif part.startswith('Init Duration:'):
                    metrics['init_duration_ms'] = float(part.split(':')[1].strip().split()[0])
                    metrics['is_cold_start'] = True
                elif part.startswith('XRAY TraceId:'):
                    metrics['xray_trace_id'] = part.split(':', 1)[1].strip().split()[0]
                elif part.startswith('Sampled:'):
                    sampled = part.split(':', 1)[1].strip().split()[0].lower()
                    if sampled in ('true', '1'):
                        metrics['xray_sampled'] = True
                    elif sampled in ('false', '0'):
                        metrics['xray_sampled'] = False
        return metrics

    # ==================== AgentCore 计费(Usage Logs) ====================

    def get_agentcore_usage_from_logs(
        self,
        runtime_id: str,
        session_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """从 AgentCore Usage Logs 查询计费指标"""

        log_groups = self.discover_agentcore_usage_log_groups(runtime_id)
        if not log_groups:
            message = (
                f"No AgentCore usage log groups found for runtime_id '{runtime_id}' "
                f"in region '{self.region}'"
            )
            print(f"    [usage-logs] {message}")
            return {
                'vcpu_hours': 0.0,
                'memory_gb_hours': 0.0,
                'log_entries': 0,
                'session_id': session_id,
                'missing_log_group': True,
                'error': message,
            }

        print(f"    [usage-logs] Log group: {', '.join(log_groups)}")
        print(f"    [usage-logs] Session ID: {session_id}")

        filter_pattern = f'"{session_id}"'

        # 查询日志
        all_events: List[Dict] = []
        try:
            for log_group in log_groups:
                kwargs = {
                    'logGroupName': log_group,
                    'startTime': int(start_time.timestamp() * 1000),
                    'endTime': int(end_time.timestamp() * 1000),
                    'filterPattern': filter_pattern,
                }
                while True:
                    resp = self.logs.filter_log_events(**kwargs)
                    all_events.extend(resp.get('events', []))
                    next_token = resp.get('nextToken')
                    if not next_token:
                        break
                    kwargs['nextToken'] = next_token
        except Exception as e:
            print(f"    [usage-logs] Error querying logs: {e}")
            return {}

        if not all_events:
            print(f"    [usage-logs] No usage log entries found in time window")
            return {}

        # 汇总
        total_vcpu_hours = 0.0
        total_mem_gb_hours = 0.0

        for event in all_events:
            try:
                data = _json.loads(event.get('message', '{}'))
            except _json.JSONDecodeError:
                continue

            if data.get('attributes', {}).get('session.id') != session_id:
                continue

            metrics = data.get('metrics', {})
            total_vcpu_hours += metrics.get('agent.runtime.vcpu.hours.used', 0)
            total_mem_gb_hours += metrics.get('agent.runtime.memory.gb_hours.used', 0)

        return {
            'vcpu_hours': total_vcpu_hours,
            'memory_gb_hours': total_mem_gb_hours,
            'log_entries': len(all_events),
            'session_id': session_id,
        }

    @staticmethod
    def _duration_ms_from_xray_doc(doc: Dict[str, Any]) -> Optional[float]:
        start_time = doc.get("start_time")
        end_time = doc.get("end_time")
        if start_time is None or end_time is None:
            return None
        try:
            return max(0.0, (float(end_time) - float(start_time)) * 1000.0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _doc_request_id(doc: Dict[str, Any]) -> str:
        aws = doc.get("aws", {}) if isinstance(doc, dict) else {}
        if not isinstance(aws, dict):
            return ""
        for key in ("request_id", "requestId"):
            value = aws.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _annotation_value(
        doc: Dict[str, Any],
        annotation_key: str,
        aws_key: str,
    ) -> Optional[float]:
        annotations = (
            doc.get("annotations", {}) if isinstance(doc.get("annotations", {}), dict) else {}
        )
        aws = doc.get("aws", {}) if isinstance(doc.get("aws", {}), dict) else {}
        value = annotations.get(annotation_key)
        if value is None:
            value = aws.get(aws_key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _max_subsegment_duration_ms(
        self,
        doc: Dict[str, Any],
        *,
        subsegment_name: str,
    ) -> Optional[float]:
        subsegments = doc.get("subsegments", []) if isinstance(doc, dict) else []
        if not isinstance(subsegments, list):
            return None

        want = str(subsegment_name or "")
        max_duration_ms: Optional[float] = None
        stack = list(subsegments)
        while stack:
            subsegment = stack.pop()
            if not isinstance(subsegment, dict):
                continue
            if str(subsegment.get("name") or "") == want:
                duration_ms = self._duration_ms_from_xray_doc(subsegment)
                if duration_ms is not None:
                    if max_duration_ms is None:
                        max_duration_ms = duration_ms
                    else:
                        max_duration_ms = max(max_duration_ms, duration_ms)
            nested = subsegment.get("subsegments", [])
            if isinstance(nested, list) and nested:
                stack.extend(nested)
        return max_duration_ms

    def _trace_contains_request_id(
        self,
        trace: Dict[str, Any],
        request_id: str,
    ) -> bool:
        for segment in trace.get("Segments", []):
            try:
                doc = _json.loads(segment.get("Document", "{}"))
            except _json.JSONDecodeError:
                continue
            if self._doc_request_id(doc) == request_id:
                return True
        return False

    def _xray_debug_context(self) -> Dict[str, str]:
        context = {
            "region": str(getattr(self, "region", "unknown") or "unknown"),
            "account_id": "unknown",
        }

        sts = getattr(self, "sts", None)
        if sts is None:
            try:
                sts = boto3.client("sts")
            except Exception:
                return context
            self.sts = sts

        get_caller_identity = getattr(sts, "get_caller_identity", None)
        if not callable(get_caller_identity):
            return context

        try:
            response = get_caller_identity()
        except Exception:
            return context

        account_id = response.get("Account") if isinstance(response, dict) else None
        if account_id:
            context["account_id"] = str(account_id)
        return context

    @staticmethod
    def _normalize_unprocessed_trace_ids(entries: Any) -> List[Any]:
        if not isinstance(entries, list):
            return []

        normalized: List[Any] = []
        for entry in entries:
            if isinstance(entry, dict):
                normalized.append(
                    {
                        key: value
                        for key, value in entry.items()
                        if key in ("Id", "ErrorCode", "Message")
                    }
                )
            else:
                normalized.append(str(entry))
        return normalized

    @staticmethod
    def _normalize_trace_shape(trace: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(trace, dict):
            return {}
        if isinstance(trace.get("Segments"), list):
            return trace
        spans = trace.get("Spans")
        if not isinstance(spans, list):
            return trace
        normalized = dict(trace)
        normalized["Segments"] = [
            {"Document": span.get("Document", "{}")}
            for span in spans
            if isinstance(span, dict)
        ]
        return normalized

    @staticmethod
    def _chunk_trace_ids(trace_ids: List[str], chunk_size: int = 5) -> List[List[str]]:
        if chunk_size <= 0:
            return [list(trace_ids)]
        return [
            trace_ids[index : index + chunk_size]
            for index in range(0, len(trace_ids), chunk_size)
        ]

    def _retrieve_transaction_search_traces(
        self,
        *,
        trace_ids: List[str],
        start_time: datetime,
        end_time: datetime,
        max_attempts: int,
        retry_sleep_s: float,
    ) -> Tuple[List[Dict[str, Any]], str]:
        start_retrieval = getattr(self.xray, "start_trace_retrieval", None)
        list_retrieved = getattr(self.xray, "list_retrieved_traces", None)
        if not callable(start_retrieval) or not callable(list_retrieved):
            return [], "UNSUPPORTED"

        traces: List[Dict[str, Any]] = []
        last_status = "UNKNOWN"

        for trace_id_chunk in self._chunk_trace_ids(trace_ids):
            try:
                response = start_retrieval(
                    StartTime=start_time,
                    EndTime=end_time,
                    TraceIds=trace_id_chunk,
                )
            except Exception as e:
                print(f"    [xray] Error starting trace retrieval: {e}")
                continue

            retrieval_token = str(response.get("RetrievalToken") or "")
            if not retrieval_token:
                continue

            for attempt in range(1, max_attempts + 1):
                try:
                    result = list_retrieved(
                        RetrievalToken=retrieval_token,
                        TraceFormat="XRAY",
                    )
                except Exception as e:
                    if attempt >= max_attempts:
                        print(f"    [xray] Error listing retrieved traces: {e}")
                        break
                    time.sleep(retry_sleep_s)
                    continue

                last_status = str(result.get("RetrievalStatus") or last_status)
                traces.extend(
                    self._normalize_trace_shape(trace)
                    for trace in (result.get("Traces", []) or [])
                    if isinstance(trace, dict)
                )

                next_token = result.get("NextToken")
                while next_token:
                    page = list_retrieved(
                        RetrievalToken=retrieval_token,
                        TraceFormat="XRAY",
                        NextToken=next_token,
                    )
                    traces.extend(
                        self._normalize_trace_shape(trace)
                        for trace in (page.get("Traces", []) or [])
                        if isinstance(trace, dict)
                    )
                    next_token = page.get("NextToken")
                    last_status = str(page.get("RetrievalStatus") or last_status)

                if last_status == "COMPLETE":
                    break
                if attempt < max_attempts:
                    time.sleep(retry_sleep_s)

        return traces, last_status

    def _summarize_lambda_trace_for_debug(
        self,
        trace: Dict[str, Any],
        *,
        function_name: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        segments_summary: List[Dict[str, Any]] = []
        for segment in trace.get("Segments", [])[:8]:
            try:
                doc = _json.loads(segment.get("Document", "{}"))
            except _json.JSONDecodeError:
                segments_summary.append({"json_error": True})
                continue

            annotations = (
                doc.get("annotations", {})
                if isinstance(doc.get("annotations", {}), dict)
                else {}
            )
            aws = doc.get("aws", {}) if isinstance(doc.get("aws", {}), dict) else {}
            subsegments = doc.get("subsegments", [])
            if not isinstance(subsegments, list):
                subsegments = []

            origin = str(doc.get("origin", "") or "")
            name = str(doc.get("name", "") or "")
            doc_request_id = self._doc_request_id(doc)
            segments_summary.append(
                {
                    "name": name,
                    "origin": origin,
                    "request_id": doc_request_id,
                    "function_match": (
                        origin == "AWS::Lambda::Function" or name == function_name
                    ),
                    "request_match": bool(request_id and doc_request_id == request_id),
                    "annotation_keys": sorted(str(key) for key in annotations.keys())[:12],
                    "aws_keys": sorted(str(key) for key in aws.keys())[:12],
                    "subsegment_names": [
                        str(subsegment.get("name", "") or "")
                        for subsegment in subsegments[:12]
                        if isinstance(subsegment, dict)
                    ],
                }
            )

        return {
            "trace_id": str(trace.get("Id") or ""),
            "segment_count": len(trace.get("Segments", [])),
            "segments": segments_summary,
        }

    @staticmethod
    def _trace_summary_matches_function_name(
        summary: Dict[str, Any],
        function_name: str,
    ) -> Optional[bool]:
        service_ids = summary.get("ServiceIds")
        if not isinstance(service_ids, list) or not service_ids:
            return None

        want = str(function_name or "").strip().lower()
        if not want:
            return None

        names: set[str] = set()
        for service in service_ids:
            if not isinstance(service, dict):
                continue
            for key in ("Name", "name"):
                value = service.get(key)
                if value:
                    names.add(str(value).strip().lower())
            for key in ("Names", "names"):
                values = service.get(key)
                if not isinstance(values, list):
                    continue
                for value in values:
                    if value:
                        names.add(str(value).strip().lower())

        if not names:
            return None
        return want in names

    def _extract_lambda_xray_trace_metrics(
        self,
        trace: Dict[str, Any],
        *,
        function_name: str,
    ) -> Dict[str, float]:
        lambda_init_ms = 0.0
        lambda_function_run_ms = 0.0
        lambda_response_duration_ms = 0.0
        lambda_runtime_overhead_ms = 0.0
        lambda_extension_overhead_ms = 0.0
        saw_new_style_fields = False

        for segment in trace.get("Segments", []):
            try:
                doc = _json.loads(segment.get("Document", "{}"))
            except _json.JSONDecodeError:
                continue

            origin = str(doc.get("origin", "") or "")
            name = str(doc.get("name", "") or "")

            is_lambda_segment = origin in {"AWS::Lambda", "AWS::Lambda::Function"}
            is_target_segment = is_lambda_segment or name == function_name
            if not is_target_segment:
                continue

            init_ms = self._max_subsegment_duration_ms(doc, subsegment_name="Init")
            if init_ms is not None:
                lambda_init_ms = max(lambda_init_ms, init_ms)

            is_function_segment = (
                origin == "AWS::Lambda::Function" or name == function_name
            )
            if not is_function_segment:
                continue

            new_style_fields = (
                self._annotation_value(doc, "aws:responseLatency", "responseLatency"),
                self._annotation_value(doc, "aws:responseDuration", "responseDuration"),
                self._annotation_value(doc, "aws:runtimeOverhead", "runtimeOverhead"),
                self._annotation_value(doc, "aws:extensionOverhead", "extensionOverhead"),
            )
            if any(value is not None for value in new_style_fields):
                saw_new_style_fields = True
                response_latency_ms, response_duration_ms, runtime_overhead_ms, extension_overhead_ms = new_style_fields
                if response_latency_ms is not None:
                    lambda_function_run_ms = max(
                        lambda_function_run_ms,
                        response_latency_ms,
                    )
                if response_duration_ms is not None:
                    lambda_response_duration_ms = max(
                        lambda_response_duration_ms,
                        response_duration_ms,
                    )
                if runtime_overhead_ms is not None:
                    lambda_runtime_overhead_ms = max(
                        lambda_runtime_overhead_ms,
                        runtime_overhead_ms,
                    )
                if extension_overhead_ms is not None:
                    lambda_extension_overhead_ms = max(
                        lambda_extension_overhead_ms,
                        extension_overhead_ms,
                    )

        if not saw_new_style_fields:
            return {}

        platform_time_ms = (
            lambda_init_ms
            + lambda_runtime_overhead_ms
            + lambda_extension_overhead_ms
        )
        if platform_time_ms <= 0:
            return {}

        return {
            "lambda_init_ms": round(lambda_init_ms, 3),
            "lambda_function_run_ms": round(lambda_function_run_ms, 3),
            "lambda_response_duration_ms": round(lambda_response_duration_ms, 3),
            "response_transfer_ms": round(lambda_response_duration_ms, 3),
            "lambda_runtime_overhead_ms": round(lambda_runtime_overhead_ms, 3),
            "lambda_extension_overhead_ms": round(lambda_extension_overhead_ms, 3),
            "platform_time_ms": round(platform_time_ms, 3),
        }

    def get_lambda_xray_trace_metrics(
        self,
        *,
        function_name: str,
        start_time: datetime,
        end_time: datetime,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, float]:
        if not getattr(self, "xray", None):
            return {}

        trace_ids: List[str] = []
        if trace_id:
            trace_ids = [trace_id]
        else:
            try:
                trace_summaries: List[Dict[str, Any]] = []
                next_token: Optional[str] = None
                while True:
                    kwargs = {
                        "StartTime": start_time,
                        "EndTime": end_time,
                        "Sampling": False,
                    }
                    if next_token:
                        kwargs["NextToken"] = next_token
                    response = self.xray.get_trace_summaries(**kwargs)
                    trace_summaries.extend(response.get("TraceSummaries", []))
                    next_token = response.get("NextToken")
                    if not next_token:
                        break
            except Exception as e:
                print(f"    [xray] Error querying trace summaries: {e}")
                return {}

            matching_summaries: List[Dict[str, Any]] = []
            unscoped_summaries: List[Dict[str, Any]] = []
            for summary in trace_summaries:
                matches = self._trace_summary_matches_function_name(
                    summary,
                    function_name,
                )
                if matches is True:
                    matching_summaries.append(summary)
                elif matches is None:
                    unscoped_summaries.append(summary)

            if matching_summaries:
                trace_summaries = matching_summaries
            elif unscoped_summaries:
                trace_summaries = unscoped_summaries

            trace_ids = [
                str(summary.get("Id"))
                for summary in trace_summaries
                if summary.get("Id")
            ]

        if not trace_ids:
            return {}

        retry_window_s = max(
            0.0,
            float(getattr(self, "xray_poll_window_s", 30.0) or 0.0),
        )
        retry_sleep_s = max(
            0.1,
            float(getattr(self, "xray_poll_interval_s", 3.0) or 3.0),
        )
        max_attempts = max(1, int(retry_window_s / retry_sleep_s) + 1)
        debug_traces: List[Dict[str, Any]] = []
        last_unprocessed_trace_ids: List[Any] = []
        destination = self._get_trace_segment_destination()
        retrieval_status = "NOT_STARTED"

        if destination == "CloudWatchLogs":
            debug_traces, retrieval_status = self._retrieve_transaction_search_traces(
                trace_ids=trace_ids,
                start_time=start_time,
                end_time=end_time,
                max_attempts=max_attempts,
                retry_sleep_s=retry_sleep_s,
            )
            for trace in debug_traces:
                if request_id and not trace_id and not self._trace_contains_request_id(trace, request_id):
                    continue
                metrics = self._extract_lambda_xray_trace_metrics(
                    trace,
                    function_name=function_name,
                )
                if metrics:
                    matched_trace_id = str(trace.get("Id") or trace_id or "")
                    if matched_trace_id and not metrics.get("trace_id"):
                        metrics["trace_id"] = matched_trace_id
                    return metrics

            if trace_id:
                if not debug_traces:
                    debug_context = self._xray_debug_context()
                    print(
                        "    [xray][debug] trace retrieval returned no traces: "
                        + _json.dumps(
                            {
                                "trace_id": trace_id,
                                "destination": destination,
                                "retrieval_status": retrieval_status,
                                "region": debug_context["region"],
                                "account_id": debug_context["account_id"],
                            },
                            sort_keys=True,
                        )
                    )
                else:
                    for trace in debug_traces[:2]:
                        summary = self._summarize_lambda_trace_for_debug(
                            trace,
                            function_name=function_name,
                            request_id=request_id,
                        )
                        print(
                            "    [xray][debug] Trace shape: "
                            + _json.dumps(summary, sort_keys=True)
                        )
            return {}

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.xray.batch_get_traces(TraceIds=trace_ids)
            except Exception as e:
                if attempt >= max_attempts:
                    print(f"    [xray] Error querying traces: {e}")
                    return {}
                time.sleep(retry_sleep_s)
                continue

            debug_traces = response.get("Traces", []) or []
            last_unprocessed_trace_ids = self._normalize_unprocessed_trace_ids(
                response.get("UnprocessedTraceIds")
            )
            for trace in response.get("Traces", []):
                if request_id and not trace_id and not self._trace_contains_request_id(trace, request_id):
                    continue
                metrics = self._extract_lambda_xray_trace_metrics(
                    trace,
                    function_name=function_name,
                )
                if metrics:
                    matched_trace_id = str(trace.get("Id") or trace_id or "")
                    if matched_trace_id and not metrics.get("trace_id"):
                        metrics["trace_id"] = matched_trace_id
                    return metrics

            if attempt < max_attempts:
                time.sleep(retry_sleep_s)

        if trace_id:
            if not debug_traces:
                debug_context = self._xray_debug_context()
                print(
                    "    [xray][debug] batch_get_traces returned no traces: "
                    + _json.dumps(
                        {
                            "trace_id": trace_id,
                            "region": debug_context["region"],
                            "account_id": debug_context["account_id"],
                            "unprocessed_trace_ids": last_unprocessed_trace_ids,
                        },
                        sort_keys=True,
                    )
                )
            else:
                for trace in debug_traces[:2]:
                    summary = self._summarize_lambda_trace_for_debug(
                        trace,
                        function_name=function_name,
                        request_id=request_id,
                    )
                    print(
                        "    [xray][debug] Trace shape: "
                        + _json.dumps(summary, sort_keys=True)
                    )
        return {}


    # ==================== AgentCore Span Latency ====================

    def get_agentcore_span_latencies(
        self,
        session_id: str,
        start_time: datetime,
        end_time: datetime,
        request_ids: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """从 aws/spans 日志组查询 AgentCore InvokeAgentRuntime 的 per-invocation latency_ms 和 duration_ms。

        Span JSON 结构:
            .attributes."aws.request.id"  → request_id
            .attributes."session.id"      → session_id
            .attributes."latency_ms"      → 云端延迟 (ms)
            .durationNano                 → span 总持续时间 (ns → ms)

        Returns:
            Tuple of (latencies, durations):
                latencies: Dict mapping request_id → latency_ms (from attributes)
                durations: Dict mapping request_id → duration_ms (from durationNano)
        """
        log_group = "aws/spans"

        print(f"    [spans] Querying {log_group} for session '{session_id}'")

        filter_pattern = f'"{session_id}"' if session_id else ""

        all_events: List[Dict] = []
        kwargs = {
            "logGroupName": log_group,
            "startTime": int(start_time.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000),
            "filterPattern": filter_pattern,
        }
        try:
            while True:
                resp = self.logs.filter_log_events(**kwargs)
                all_events.extend(resp.get("events", []))
                next_token = resp.get("nextToken")
                if not next_token:
                    break
                kwargs["nextToken"] = next_token
        except Exception as e:
            print(f"    [spans] Error querying {log_group}: {e}")
            print(f"    [spans] Hint: ensure Observability & Tracing are enabled on your AgentCore runtime")
            return {}, {}

        if not all_events:
            print(f"    [spans] No span events found (is Tracing enabled on the runtime?)")
            return {}, {}

        request_id_set = set(request_ids) if request_ids else None
        latencies: Dict[str, float] = {}
        durations: Dict[str, float] = {}

        for event in all_events:
            try:
                data = _json.loads(event.get("message", "{}"))
            except _json.JSONDecodeError:
                continue
            duration_nano = data.get("durationNano")
            duration_ms = duration_nano / 1_000_000 if duration_nano is not None else None
            attrs = data.get("attributes", {}) if isinstance(data, dict) else {}
            rid = attrs.get("aws.request.id")
            lat = attrs.get("latency_ms")

            if lat is None:
                lat = duration_ms

            if lat is None or rid is None:
                continue
            if request_id_set is None or rid in request_id_set:
                latencies[rid] = float(lat)
                if duration_ms is not None:
                    durations[rid] = float(duration_ms)

        print(f"    [spans] Found {len(latencies)} latencies and {len(durations)} durations out of {len(all_events)} events")
        return latencies, durations

    def _get_config(self, resource_type: str) -> Dict[str, Any]:
        if resource_type not in self.RESOURCE_CONFIG:
            raise ValueError(f"Unknown resource type: {resource_type}. Must be one of {list(self.RESOURCE_CONFIG)}")
        return self.RESOURCE_CONFIG[resource_type]

    

    def get_agentcore_span_latencies(
        self,
        session_id: str,
        start_time: datetime,
        end_time: datetime,
        request_ids: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """从 aws/spans 日志组查询 AgentCore 每次调用的 latency_ms 和 duration_ms。

        Returns:
            Tuple of (latencies, durations):
                latencies: {request_id: latency_ms} (from attributes.latency_ms)
                durations: {request_id: duration_ms} (from durationNano)
        """
        log_group = "aws/spans"
        filter_pattern = f'"{session_id}"'

        all_events: List[Dict] = []
        kwargs = {
            'logGroupName': log_group,
            'startTime': int(start_time.timestamp() * 1000),
            'endTime': int(end_time.timestamp() * 1000),
            'filterPattern': filter_pattern,
        }
        try:
            while True:
                resp = self.logs.filter_log_events(**kwargs)
                all_events.extend(resp.get('events', []))
                next_token = resp.get('nextToken')
                if not next_token:
                    break
                kwargs['nextToken'] = next_token
        except Exception as e:
            print(f"    [spans] Error querying aws/spans: {e}")
            return {}, {}

        if not all_events:
            return {}, {}

        latencies: Dict[str, float] = {}
        durations: Dict[str, float] = {}
        want_ids = set(request_ids) if request_ids else None

        for event in all_events:
            try:
                data = _json.loads(event.get('message', '{}'))
            except _json.JSONDecodeError:
                continue

            attrs = data.get('attributes', {})
            if attrs.get('session.id') != session_id:
                continue

            rid = attrs.get('aws.request.id')
            if not rid:
                continue
            if want_ids and rid not in want_ids:
                continue

            duration_nano = data.get('durationNano')
            duration_ms = float(duration_nano) / 1_000_000 if duration_nano is not None else None

            latency = attrs.get('latency_ms')
            if latency is not None:
                latencies[rid] = float(latency)
            elif duration_ms is not None:
                latencies[rid] = duration_ms

            if duration_ms is not None:
                durations[rid] = duration_ms

        print(f"    [spans] Found {len(latencies)} latencies and {len(durations)} durations out of {len(all_events)} events")
        return latencies, durations

    def _discover_agentcore_runtime_id(self, runtime_prefix: str) -> Optional[str]:
        """发现 AgentCore Runtime ID

        日志组可能出现在多种前缀下，例如：
        - /aws/vendedlogs/bedrock-agentcore/runtime/USAGE_LOGS/{runtime_prefix}-{suffix}
        - /aws/bedrock-agentcore/runtimes/{runtime_prefix}-{suffix}-DEFAULT

        要求 prefix 后紧跟 '-'，避免 atsuite_foo 错误匹配 atsuite_foo_bar-xxx。
        """
        base_prefixes = (
            "/aws/vendedlogs/bedrock-agentcore/runtime/USAGE_LOGS/",
            "/aws/bedrock-agentcore/runtime/USAGE_LOGS/",
            "/aws/vendedlogs/bedrock-agentcore/runtimes/USAGE_LOGS/",
            "/aws/bedrock-agentcore/runtimes/USAGE_LOGS/",
            "/aws/vendedlogs/bedrock-agentcore/runtime/",
            "/aws/bedrock-agentcore/runtime/",
            "/aws/vendedlogs/bedrock-agentcore/runtimes/",
            "/aws/bedrock-agentcore/runtimes/",
        )
        candidates = []

        try:
            for base in base_prefixes:
                log_prefix = f"{base}{runtime_prefix}"
                kwargs = {"logGroupNamePrefix": log_prefix}
                while True:
                    resp = self.logs.describe_log_groups(**kwargs)
                    for lg in resp.get("logGroups", []):
                        log_group_name = lg.get("logGroupName", "")
                        suffix = log_group_name[len(log_prefix):]
                        if not (suffix.startswith("-") and len(suffix) > 1):
                            continue
                        runtime_suffix = suffix[1:]
                        if runtime_suffix.endswith("-DEFAULT"):
                            runtime_suffix = runtime_suffix[: -len("-DEFAULT")]
                        if not runtime_suffix:
                            continue
                        candidates.append(f"{runtime_prefix}-{runtime_suffix}")
                    next_token = resp.get("nextToken")
                    if not next_token:
                        break
                    kwargs["nextToken"] = next_token
        except Exception as e:
            print(f"    [usage-logs] Error discovering runtime_id: {e}")
            return None

        if not candidates:
            return None
        # 保持顺序去重并优先返回第一个命中的 runtime_id
        deduped = list(dict.fromkeys(candidates))
        return deduped[0]

if __name__ == "__main__":
    cloudwatch = AWSCloudWatch()
    usage = cloudwatch.get_agentcore_usage_from_logs(
        runtime_id="atsuite_travelplanner-AStSB0BNLc",
        session_id="73209ffa-3ea0-4cc3-b882-c8a08ce6897f",
        start_time=datetime.now() - timedelta(hours=5),
        end_time=datetime.now(),
    )
    print(usage)
