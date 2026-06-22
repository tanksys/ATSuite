from __future__ import annotations

import json
import contextlib
import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from atsuite import invoker as invoker_module
from atsuite.analysis.api import AnalyzeOptions, analyze_events, analyze_recorder
from atsuite.analysis.collectors import AWSCloudWatchCollector, GCPCloudLoggingCollector, NoopCollector
from atsuite.analysis.model import CollectionResult, CostLineItem, EvidenceRecord, ProviderMetric
from atsuite.analysis.observer import RunRecorder
from atsuite.analysis.pricing import create_pricing_policy
from atsuite.pipeline import resolve_benchmark
from atsuite.runtime import InvocationResult, RuntimeCapabilities, RuntimeSession


class AnalysisV2RecorderTests(unittest.TestCase):
    def test_recorder_is_thread_safe_and_roundtrips_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recorder = RunRecorder(
                provider="mcp_gateway",
                observability_provider="mcp_gateway",
                benchmark="Bench",
                trace="trace",
                family="session",
                config_path="/tmp/bench/config.json",
                targets={"server": {"family": "session"}},
            )
            recorder.start_run("u1", start_time=10.0)
            recorder.start_node(
                node_id=1,
                node_name="tool.run",
                node_type="mcp",
                runtime_name="server",
                target_id="server",
                family="session",
                runtime_config={"cpu": 1, "memory": 1024},
                start_time=11.0,
            )

            def record(index: int) -> None:
                recorder.record_invocation(
                    node_id=1,
                    node_name="tool.run",
                    target_id="server",
                    runtime_name="server",
                    family="session",
                    tool_name="tool_run",
                    call_id=f"call-{index}",
                    status="ok",
                    provider_request_id=f"provider-{index}",
                    client_elapsed_ms=10 + index,
                )

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(record, range(16)))

            recorder.finish_node(1, end_time=12.0)
            recorder.record_state(
                provider="mcp_gateway",
                operation="cleanup",
                services=["server"],
                size_gb=0.001,
                operation_count=1,
                started_at=12.0,
                ended_at=13.0,
            )
            recorder.finish_run(end_time=13.0)

            events_path = Path(tmp) / "events.json"
            recorder.save_events(events_path)
            restored = RunRecorder.from_events(events_path)

            self.assertEqual(restored.context.uid, "u1")
            self.assertEqual(len(restored.invocations), 16)
            self.assertEqual(restored.nodes[1].elapsed_ms, 1000.0)
            self.assertEqual(restored.state[0].services, ["server"])


class AnalysisV2PipelineTests(unittest.TestCase):
    def test_analyze_events_exports_v2_report_and_full_evidence_jsonl(self) -> None:
        class FakeCollector:
            default_ingestion_delay_s = 0.0
            observability_provider = "fake"

            def collect(self, context, *, nodes, invocations, sessions):
                invocation = invocations[0]
                return CollectionResult(
                    metrics=[
                        ProviderMetric(
                            metric_id="m1",
                            provider="mcp_gateway",
                            source="fake",
                            node_id=invocation.node_id,
                            invocation_call_id=invocation.call_id,
                            provider_request_id=invocation.provider_request_id,
                            fields={
                                "elapsed_time_ms": 25.0,
                                "duration_ms": 25.0,
                                "client_e2e_ms": 30.0,
                                "tool_exec_ms": 20.0,
                                "memory_usage_mb": 128.0,
                            },
                            evidence_refs=["ev1"],
                        )
                    ],
                    evidence=[
                        EvidenceRecord(
                            evidence_id="ev1",
                            provider="mcp_gateway",
                            source="fake",
                            query={"request_id": invocation.provider_request_id},
                            raw={"full": {"provider": "payload"}},
                        )
                    ],
                )

        class FakePricing:
            def price(self, context, *, metrics, state):
                return [
                    CostLineItem(
                        category="request",
                        provider="mcp_gateway",
                        amount=0.123,
                        currency="USD",
                        node_id=1,
                        invocation_call_id="call-1",
                    )
                ]

        with tempfile.TemporaryDirectory() as tmp:
            recorder = RunRecorder(
                provider="mcp_gateway",
                observability_provider="mcp_gateway",
                benchmark="Bench",
                trace="trace",
                family="session",
                config_path="/tmp/bench/config.json",
            )
            recorder.start_run("u1", start_time=1.0)
            recorder.start_node(node_id=1, node_name="tool.run", node_type="mcp", start_time=1.0)
            recorder.record_invocation(
                node_id=1,
                node_name="tool.run",
                target_id="server",
                runtime_name="server",
                family="session",
                tool_name="tool_run",
                call_id="call-1",
                status="ok",
                provider_request_id="provider-1",
                client_elapsed_ms=30.0,
            )
            recorder.finish_node(1, end_time=1.03)
            recorder.finish_run(end_time=1.03)
            events_path = Path(tmp) / "events.json"
            recorder.save_events(events_path)

            report = analyze_events(
                events_path,
                AnalyzeOptions(output_dir=tmp, timestamp="run1"),
                collector=FakeCollector(),
                pricing_policy=FakePricing(),
            )

            self.assertEqual(report.schema_version, 2)
            self.assertEqual(report.summary["total_price"], 0.123)
            self.assertEqual(report.nodes["1"]["tool_exec_ms"], 20.0)
            self.assertTrue(Path(report.report_path).exists())
            evidence_lines = Path(report.evidence_path).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(evidence_lines), 1)
            self.assertEqual(json.loads(evidence_lines[0])["raw"]["full"]["provider"], "payload")

    def test_analyze_recorder_delegates_ingestion_wait_to_collector(self) -> None:
        class WaitingCollector:
            default_ingestion_delay_s = 999.0
            observability_provider = "fake"

            def __init__(self) -> None:
                self.waited = False

            def wait_for_ingestion(self, context, *, nodes, invocations, sessions):
                self.waited = True

            def collect(self, context, *, nodes, invocations, sessions):
                return CollectionResult()

        with tempfile.TemporaryDirectory() as tmp:
            recorder = RunRecorder(
                provider="mcp_gateway",
                observability_provider="mcp_gateway",
                benchmark="Bench",
                trace="trace",
                family="session",
                config_path="/tmp/bench/config.json",
            )
            recorder.start_run("u1", start_time=1.0)
            recorder.finish_run(end_time=2.0)
            collector = WaitingCollector()

            analyze_recorder(
                recorder,
                options=AnalyzeOptions(
                    output_dir=tmp,
                    wait_for_ingestion=True,
                    timestamp="waited",
                ),
                collector=collector,
            )

        self.assertTrue(collector.waited)


class AnalysisV2CollectorAndPricingTests(unittest.TestCase):
    def test_noop_collector_uses_runtime_invocation_metadata(self) -> None:
        recorder = RunRecorder(
            provider="mcp_gateway",
            observability_provider="none",
            benchmark="Bench",
            trace="trace",
            family="session",
            config_path="/tmp/config.json",
        )
        recorder.start_run("u1")
        recorder.record_invocation(
            node_id=1,
            node_name="tool",
            target_id="server",
            runtime_name="server",
            family="session",
            tool_name="tool",
            call_id="call",
            status="ok",
            provider_request_id="provider",
            client_elapsed_ms=12.5,
        )
        result = NoopCollector().collect(
            recorder.context,
            nodes=recorder.nodes,
            invocations=recorder.invocations,
            sessions=recorder.sessions,
        )
        self.assertEqual(result.metrics[0].fields["client_e2e_ms"], 12.5)
        self.assertEqual(result.metrics[0].provider_request_id, "provider")

    def test_gcp_collector_indexes_trace_join_and_breakdown(self) -> None:
        entries = [
            {
                "jsonPayload": {"request_id": "rid-1", "trace": "trace-1"},
                "trace": "trace-1",
                "resource": {"labels": {"service_name": "svc"}},
            },
            {
                "trace": "trace-1",
                "httpRequest": {"latency": "0.123s", "status": 200},
                "resource": {"labels": {"service_name": "svc"}},
            },
            {
                "jsonPayload": {
                    "event": "atsuite_mcp_breakdown",
                    "request_id": "rid-1",
                    "tool_exec_ms": 42.0,
                }
            },
        ]
        indexed = GCPCloudLoggingCollector()._index_entries(entries)
        self.assertAlmostEqual(indexed["rid-1"]["latency_ms"], 123.0)
        self.assertEqual(indexed["rid-1"]["tool_exec_ms"], 42.0)

    def test_gcp_pricing_uses_100ms_request_rounding(self) -> None:
        metric = ProviderMetric(
            metric_id="m",
            provider="gcp",
            source="fake",
            fields={"elapsed_time_ms": 250.0, "cpu": 1, "memory": 1024},
        )
        costs = create_pricing_policy("gcp").price(
            RunRecorder(
                provider="gcp_faas",
                observability_provider="gcp_cloud_logging",
                benchmark="Bench",
                trace="trace",
                family="faas",
                config_path="/tmp/config.json",
            ).context,
            metrics=[metric],
            state=[],
        )
        total = sum(item.amount for item in costs)
        self.assertAlmostEqual(total, 0.0000072 + 0.00000075 + 0.0000004)

    def test_agentcore_collector_joins_breakdown_by_call_id(self) -> None:
        class FakeCloudWatch:
            def __init__(self) -> None:
                self.log_calls = []

            def get_logs(self, resource_type, resource_name, start_time, end_time, request_id=None):
                self.log_calls.append(
                    {
                        "resource_type": resource_type,
                        "resource_name": resource_name,
                        "request_id": request_id,
                    }
                )
                return [
                    {
                        "message": json.dumps(
                            {
                                "event": "atsuite_mcp_breakdown",
                                "request_id": "call-1",
                                "jsonrpc_id": "call-1",
                                "app_e2e_ms": 12.0,
                                "tool_exec_ms": 7.5,
                                "framework_overhead_ms": 4.5,
                            }
                        )
                    }
                ]

            def get_agentcore_usage_from_logs(self, runtime_id, session_id, start_time, end_time):
                return {}

        recorder = RunRecorder(
            provider="aws_agentcore",
            observability_provider="aws_agentcore_cloudwatch",
            benchmark="Bench",
            trace="trace",
            family="session",
            config_path="/tmp/config.json",
            endpoint_map={
                "targets": {
                    "server": {
                        "endpoint": (
                            "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/"
                            "arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A111%3Aruntime%2F"
                            "atsuite_server-AbC123/invocations?qualifier=DEFAULT"
                        )
                    }
                }
            },
        )
        recorder.start_run("u1", start_time=1.0)
        recorder.start_node(
            node_id=1,
            node_name="tool.run",
            node_type="mcp",
            runtime_name="server",
            target_id="server",
            family="session",
            runtime_config={"cpu": 2, "memory": 2048},
            start_time=1.0,
        )
        recorder.record_invocation(
            node_id=1,
            node_name="tool.run",
            target_id="server",
            runtime_name="server",
            family="session",
            tool_name="tool_run",
            call_id="call-1",
            status="ok",
            provider_request_id="aws-request-1",
            provider_session_id="session-1",
            client_elapsed_ms=20.0,
            provider_metadata={"session_id": "session-1"},
        )

        fake = FakeCloudWatch()
        collector = AWSCloudWatchCollector(agentcore=True, region="us-east-1")
        collector._cloudwatch = fake
        result = collector.collect(
            recorder.context,
            nodes=recorder.nodes,
            invocations=recorder.invocations,
            sessions=recorder.sessions,
        )

        self.assertEqual(fake.log_calls[0]["resource_name"], "atsuite_server-AbC123")
        self.assertIsNone(fake.log_calls[0]["request_id"])
        cloudwatch_metric = next(metric for metric in result.metrics if metric.source == "cloudwatch")
        self.assertEqual(cloudwatch_metric.fields["app_e2e_ms"], 12.0)
        self.assertEqual(cloudwatch_metric.fields["tool_exec_ms"], 7.5)
        self.assertFalse(
            any(item.get("kind") == "unmatched_request_id" for item in result.diagnostics)
        )

    def test_agentcore_usage_uses_session_id_from_invocations(self) -> None:
        class FakeCloudWatch:
            def __init__(self) -> None:
                self.usage_calls = []

            def get_logs(self, resource_type, resource_name, start_time, end_time, request_id=None):
                return []

            def get_agentcore_usage_from_logs(self, runtime_id, session_id, start_time, end_time):
                self.usage_calls.append((runtime_id, session_id))
                return {
                    "vcpu_hours": 0.5,
                    "memory_gb_hours": 1.5,
                    "log_entries": 1,
                    "session_id": session_id,
                }

        recorder = RunRecorder(
            provider="aws_agentcore",
            observability_provider="aws_agentcore_cloudwatch",
            benchmark="Bench",
            trace="trace",
            family="session",
            config_path="/tmp/config.json",
            endpoint_map={
                "targets": {
                    "server": {
                        "endpoint": (
                            "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/"
                            "arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A111%3Aruntime%2F"
                            "atsuite_server-AbC123/invocations?qualifier=DEFAULT"
                        )
                    }
                }
            },
        )
        recorder.start_run("u1", start_time=1.0)
        recorder.record_session_open(target_id="server", runtime_name="server")
        recorder.record_invocation(
            node_id=1,
            node_name="tool.run",
            target_id="server",
            runtime_name="server",
            family="session",
            tool_name="tool_run",
            call_id="call-1",
            status="ok",
            provider_request_id="aws-request-1",
            provider_session_id="session-1",
            client_elapsed_ms=20.0,
            provider_metadata={"session_id": "session-1"},
        )

        fake = FakeCloudWatch()
        collector = AWSCloudWatchCollector(agentcore=True, region="us-east-1")
        collector._cloudwatch = fake
        result = collector.collect(
            recorder.context,
            nodes=recorder.nodes,
            invocations=recorder.invocations,
            sessions=recorder.sessions,
        )
        costs = create_pricing_policy("aws_agentcore").price(
            recorder.context,
            metrics=result.metrics,
            state=[],
        )

        self.assertEqual(fake.usage_calls, [("atsuite_server-AbC123", "session-1")])
        usage_metric = next(metric for metric in result.metrics if metric.source == "agentcore_usage")
        self.assertEqual(usage_metric.fields["vcpu_hours"], 0.5)
        self.assertGreater(sum(item.amount for item in costs), 0.0)

    def test_agentcore_wait_polls_until_usage_logs_are_ready(self) -> None:
        class FakeCloudWatch:
            def __init__(self) -> None:
                self.calls = 0

            def get_agentcore_usage_from_logs(self, runtime_id, session_id, start_time, end_time):
                self.calls += 1
                if self.calls == 1:
                    return {"log_entries": 0}
                return {
                    "vcpu_hours": 0.1,
                    "memory_gb_hours": 0.2,
                    "log_entries": 1,
                    "session_id": session_id,
                }

        recorder = RunRecorder(
            provider="aws_agentcore",
            observability_provider="aws_agentcore_cloudwatch",
            benchmark="Bench",
            trace="trace",
            family="session",
            config_path="/tmp/config.json",
            endpoint_map={
                "targets": {
                    "server": {
                        "endpoint": (
                            "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/"
                            "arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A111%3Aruntime%2F"
                            "atsuite_server-AbC123/invocations?qualifier=DEFAULT"
                        )
                    }
                }
            },
        )
        recorder.start_run("u1", start_time=1.0)
        recorder.finish_run(end_time=2.0)
        recorder.record_invocation(
            node_id=1,
            node_name="tool.run",
            target_id="server",
            runtime_name="server",
            family="session",
            tool_name="tool_run",
            call_id="call-1",
            status="ok",
            provider_request_id="aws-request-1",
            provider_session_id="session-1",
            client_elapsed_ms=20.0,
        )

        fake = FakeCloudWatch()
        collector = AWSCloudWatchCollector(agentcore=True, region="us-east-1")
        collector._cloudwatch = fake
        with mock.patch.dict(
            os.environ,
            {
                "ATSUITE_AGENTCORE_USAGE_WAIT_TIMEOUT_S": "10",
                "ATSUITE_AGENTCORE_USAGE_POLL_INTERVAL_S": "1",
            },
        ):
            with mock.patch("atsuite.analysis.collectors.time.sleep"):
                with contextlib.redirect_stdout(io.StringIO()):
                    collector.wait_for_ingestion(
                        recorder.context,
                        nodes=recorder.nodes,
                        invocations=recorder.invocations,
                        sessions=recorder.sessions,
                    )

        self.assertEqual(fake.calls, 2)


class InvokerAnalyzerBoundaryTests(unittest.TestCase):
    def test_invoker_no_longer_mentions_provider_specific_analyzer_hooks(self) -> None:
        source = Path("atsuite/invoker.py").read_text(encoding="utf-8")
        for forbidden in (
            "record_gcp_request",
            "add_client_request_id",
            "add_initialize_request",
            "agentcore_session_ids",
            "get_price_for_gcpstorage",
            "get_price_for_alistorage",
        ):
            self.assertNotIn(forbidden, source)

    def test_run_trace_returns_compact_v2_result_with_universal_call_id(self) -> None:
        class FakeRuntime:
            def __init__(self) -> None:
                self.endpoint_map = {}
                self.seen_call_ids = []

            def capabilities(self):
                return RuntimeCapabilities(
                    family="session",
                    requires_open_session=True,
                    platform_handles_state_concurrency=True,
                    supports_external_state_ops=False,
                    observability="mcp_gateway",
                )

            def connect(self, endpoint_map):
                self.endpoint_map = endpoint_map

            def open_session(self, target, uid):
                return RuntimeSession(
                    uid=uid,
                    target_id=target.target_id,
                    provider_session_id="session-1",
                    metadata={"initialize_request_id": "init-1"},
                )

            def invoke(self, request):
                self.seen_call_ids.append(request.call_id)
                return InvocationResult(
                    provider_request_id="provider-1",
                    client_elapsed_ms=12.0,
                    provider_metadata={"session_id": "session-1"},
                )

            def close_session(self, session):
                return None

            def cleanup_run(self, uid):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bench"
            (root / "nodes" / "tool").mkdir(parents=True)
            (root / "trace").mkdir()
            (root / "config").mkdir()
            (root / "trace" / "trace.json").write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "id": 0,
                                "name": "start",
                                "type": "logic",
                                "edge_to": [{"id": 1, "params": {"input": {"x": 1}}}],
                            },
                            {
                                "id": 1,
                                "name": "tool.run",
                                "type": "tool_use",
                                "edge_to": [],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config = root / "config" / "bench.json"
            config.write_text(
                json.dumps(
                    {
                        "trace_file": "./trace/trace.json",
                        "nodes": [
                            {
                                "name": "tool",
                                "dir": "./nodes/tool",
                                "trace_names": [{"name": "tool.run", "tool": "tool_run"}],
                            }
                        ],
                        "pipeline": {
                            "mcp_serverless": {
                                "servers": [
                                    {
                                        "name": "server",
                                        "nodes": ["tool"],
                                        "deploy": {"cpu": 1, "memory": 1024, "disk": 512, "timeout": 30},
                                    }
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            url_map = root / "url_map.json"
            url_map.write_text(
                json.dumps({"provider": "mcp_gateway", "targets": {"server": "https://gateway.test/mcp"}}),
                encoding="utf-8",
            )

            old_cwd = Path.cwd()
            fake_runtime = FakeRuntime()
            try:
                os.chdir(tmp)
                with mock.patch.object(invoker_module, "create_runtime_adapter", return_value=fake_runtime):
                    with mock.patch.object(invoker_module, "cleaner", return_value=0.0):
                        with contextlib.redirect_stdout(io.StringIO()):
                            result = invoker_module.run_trace(
                                config,
                                url_map,
                                "u1",
                                provider="mcp_gateway",
                                skip_sleep=True,
                                skip_analyzer=True,
                            )
            finally:
                os.chdir(old_cwd)
                resolve_benchmark.cache_clear()

        self.assertEqual(result["run"]["uid"], "u1")
        self.assertEqual(result["run"]["provider"], "mcp_gateway")
        self.assertIn("summary", result)
        self.assertEqual(result["summary"]["total_price"], 0.0)
        self.assertEqual(len(fake_runtime.seen_call_ids), 1)
        self.assertTrue(fake_runtime.seen_call_ids[0].startswith("u1_1_"))


if __name__ == "__main__":
    unittest.main()
