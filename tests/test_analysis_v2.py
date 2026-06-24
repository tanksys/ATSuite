from __future__ import annotations

import json
import contextlib
import io
import importlib
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from atsuite import invoker as invoker_module
from atsuite.analysis.api import AnalyzeOptions, analyze_events, analyze_recorder
from atsuite.analysis.collectors import (
    AWSCloudWatchCollector,
    AliSLSCollector,
    GCPCloudLoggingCollector,
    NoopCollector,
)
from atsuite.analysis.model import CollectionResult, CostLineItem, EvidenceRecord, ProviderMetric
from atsuite.analysis.observer import RunRecorder
from atsuite.analysis.pricing import create_pricing_policy
from atsuite.analysis.timeline import TimelineBuilder
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
                                "request_start_wall_ns": 1_000_000_000,
                                "request_end_wall_ns": 1_030_000_000,
                                "tool_start_wall_ns": 1_005_000_000,
                                "tool_end_wall_ns": 1_025_000_000,
                                "time_source": "sdk_wall_clock",
                                "confidence": "sdk_wall_clock",
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
                client_start_time=1.001,
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
            self.assertTrue(Path(report.trace_path).exists())
            evidence_lines = Path(report.evidence_path).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(evidence_lines), 1)
            self.assertEqual(json.loads(evidence_lines[0])["raw"]["full"]["provider"], "payload")
            trace_payload = json.loads(Path(report.trace_path).read_text(encoding="utf-8"))
            self.assertEqual(trace_payload["displayTimeUnit"], "ms")
            event_names = {event.get("name") for event in trace_payload["traceEvents"]}
            self.assertIn("run", event_names)
            self.assertIn("tool_use:1:tool.run", event_names)
            self.assertNotIn("node:1:tool.run", event_names)
            self.assertIn("app_request:1", event_names)
            self.assertIn("tool_exec:1:tool_run", event_names)
            client_process_sort = [
                event
                for event in trace_payload["traceEvents"]
                if event.get("ph") == "M"
                and event.get("name") == "process_sort_index"
                and event.get("pid") == "client"
            ]
            self.assertEqual(client_process_sort[0]["args"]["sort_index"], 0)

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


class AnalysisV2TimelineTests(unittest.TestCase):
    def test_timeline_builder_emits_client_only_trace_with_missing_cloud_diagnostic(self) -> None:
        recorder = RunRecorder(
            provider="mcp_gateway",
            observability_provider="none",
            benchmark="Bench",
            trace="trace",
            family="session",
            config_path="/tmp/config.json",
        )
        recorder.start_run("u1", start_time=100.0)
        recorder.record_session_open(
            target_id="server",
            runtime_name="server",
            provider_session_id="session-1",
            initialize_request_id="init-1",
            opened_at=100.005,
        )
        recorder.start_node(node_id=1, node_name="tool.run", node_type="mcp", start_time=100.01)
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
            client_start_time=100.02,
            client_elapsed_ms=15.0,
        )
        recorder.finish_node(1, end_time=100.04)
        recorder.finish_run(end_time=100.05)

        trace_payload = TimelineBuilder().build(
            recorder.context,
            nodes=recorder.nodes,
            invocations=recorder.invocations,
            sessions=recorder.sessions,
            metrics=[],
            diagnostics=[{"kind": "unmatched_request_id", "request_id": "provider-1"}],
        )
        event_names = {event.get("name") for event in trace_payload["traceEvents"]}
        self.assertIn("client_send:1", event_names)
        self.assertIn("client_receive:1", event_names)
        self.assertIn("missing_cloud_receive_timestamp:1", event_names)
        self.assertIn("diagnostic:unmatched_request_id", event_names)
        session_events = [
            event
            for event in trace_payload["traceEvents"]
            if event.get("name") == "session_open:server"
        ]
        self.assertEqual(session_events[0]["pid"], "provider:server")
        self.assertNotEqual(session_events[0]["pid"], "client")

    def test_timeline_builder_preserves_overlapping_client_lanes(self) -> None:
        recorder = RunRecorder(
            provider="mcp_gateway",
            observability_provider="none",
            benchmark="Bench",
            trace="trace",
            family="session",
            config_path="/tmp/config.json",
        )
        recorder.start_run("u1", start_time=100.0)
        recorder.start_node(node_id=1, node_name="a", node_type="llm", start_time=100.0)
        recorder.finish_node(1, end_time=100.1)
        recorder.start_node(node_id=2, node_name="b", node_type="llm", start_time=100.05)
        recorder.finish_node(2, end_time=100.15)
        recorder.start_node(node_id=3, node_name="tool.a", node_type="mcp", start_time=100.0)
        recorder.record_invocation(
            node_id=3,
            node_name="tool.a",
            target_id="server-a",
            runtime_name="server-a",
            family="session",
            tool_name="tool_a",
            call_id="call-a",
            status="ok",
            provider_request_id="provider-a",
            client_start_time=100.02,
            client_elapsed_ms=100.0,
        )
        recorder.finish_node(3, end_time=100.12)
        recorder.start_node(node_id=4, node_name="tool.b", node_type="mcp", start_time=100.03)
        recorder.record_invocation(
            node_id=4,
            node_name="tool.b",
            target_id="server-b",
            runtime_name="server-b",
            family="session",
            tool_name="tool_b",
            call_id="call-b",
            status="ok",
            provider_request_id="provider-b",
            client_start_time=100.04,
            client_elapsed_ms=100.0,
        )
        recorder.finish_node(4, end_time=100.14)
        recorder.finish_run(end_time=100.2)

        trace_payload = TimelineBuilder().build(
            recorder.context,
            nodes=recorder.nodes,
            invocations=recorder.invocations,
            sessions=[],
            metrics=[],
        )
        spans = {
            event["name"]: event
            for event in trace_payload["traceEvents"]
            if event.get("ph") == "X"
        }
        self.assertLess(spans["llm:1:a"]["ts"], spans["llm:2:b"]["ts"])
        self.assertGreater(
            spans["llm:1:a"]["ts"] + spans["llm:1:a"]["dur"],
            spans["llm:2:b"]["ts"],
        )
        self.assertNotEqual(spans["llm:1:a"]["tid"], spans["llm:2:b"]["tid"])
        self.assertNotEqual(
            spans["tool_use:3:tool.a"]["tid"],
            spans["tool_use:4:tool.b"]["tid"],
        )
        self.assertTrue(spans["tool_use:3:tool.a"]["tid"].startswith("tool_use/"))
        self.assertTrue(spans["tool_use:4:tool.b"]["tid"].startswith("tool_use/"))


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

    def test_ali_collector_joins_sls_metrics_and_sdk_breakdown(self) -> None:
        class FakeSLS:
            def __init__(self) -> None:
                self.metric_queries = []
                self.breakdown_queries = []

            def getlogs(self, logstore, from_time, to_time, query):
                self.metric_queries.append((logstore, query))
                return {
                    "duration_ms": 25.0,
                    "memory_usage_mb": 128.0,
                    "is_cold_start": "false",
                    "schedule_latency_ms": 3.0,
                    "invoker_function_ms": 28.0,
                    "invokeFunctionStartTimestamp": 1_782_287_896_500,
                }

            def getbreakdownlogs(self, logstore, from_time, to_time, query):
                self.breakdown_queries.append((logstore, query))
                return [
                    {
                        "event": "uaib_function_breakdown",
                        "request_id": "call-1",
                        "app_e2e_ms": 20.0,
                        "tool_exec_ms": 12.0,
                        "pre_tool_ms": 4.0,
                        "post_tool_ms": 4.0,
                        "request_start_wall_ns": 1_782_287_896_501_000_000,
                        "request_end_wall_ns": 1_782_287_896_521_000_000,
                        "tool_start_wall_ns": 1_782_287_896_505_000_000,
                        "tool_end_wall_ns": 1_782_287_896_517_000_000,
                    }
                ]

        recorder = RunRecorder(
            provider="ali_fc",
            observability_provider="ali_sls",
            benchmark="Bench",
            trace="trace",
            family="faas",
            config_path="/tmp/config.json",
        )
        recorder.start_run("u1", start_time=1.0)
        recorder.start_node(
            node_id=1,
            node_name="tool.run",
            node_type="function",
            runtime_name="server",
            target_id="server",
            family="faas",
            runtime_config={"memory": 128},
            start_time=1.0,
        )
        recorder.record_invocation(
            node_id=1,
            node_name="tool.run",
            target_id="server",
            runtime_name="server",
            family="faas",
            tool_name="tool_run",
            call_id="call-1",
            status="ok",
            provider_request_id="provider-1",
            client_elapsed_ms=30.0,
        )

        fake = FakeSLS()
        collector = AliSLSCollector(project="atsuite", location="us-east-1")
        collector._sls = fake
        collector._sls_clients["uaibs"] = fake
        collector._log_destinations["server-function"] = ("uaibs", "server-function")
        result = collector.collect(
            recorder.context,
            nodes=recorder.nodes,
            invocations=recorder.invocations,
            sessions=recorder.sessions,
        )

        metric = result.metrics[0]
        self.assertEqual(fake.metric_queries[0][0], "server-function")
        self.assertEqual(result.evidence[0].query["project"], "uaibs")
        self.assertEqual(result.evidence[0].query["configured_project"], "atsuite")
        self.assertIn("durationMs", fake.metric_queries[0][1])
        self.assertEqual(fake.breakdown_queries, [("server-function", "app_e2e_ms")])
        self.assertEqual(metric.fields["app_e2e_ms"], 20.0)
        self.assertEqual(metric.fields["tool_exec_ms"], 12.0)
        self.assertEqual(metric.fields["provider_receive_wall_ns"], 1_782_287_896_500_000_000)
        self.assertEqual(metric.fields["provider_response_wall_ns"], 1_782_287_896_525_000_000)
        self.assertFalse(
            any(item.get("kind") == "unmatched_request_id" for item in result.diagnostics)
        )

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
                "timestamp": "1970-01-01T00:00:10.123Z",
                "resource": {"labels": {"service_name": "svc"}},
            },
            {
                "jsonPayload": {
                    "event": "atsuite_mcp_breakdown",
                    "request_id": "rid-1",
                    "tool_exec_ms": 42.0,
                    "request_start_wall_ns": 10_000_000_000,
                    "request_end_wall_ns": 10_050_000_000,
                    "tool_start_wall_ns": 10_005_000_000,
                    "tool_end_wall_ns": 10_047_000_000,
                }
            },
        ]
        indexed = GCPCloudLoggingCollector()._index_entries(entries)
        self.assertAlmostEqual(indexed["rid-1"]["latency_ms"], 123.0)
        self.assertEqual(indexed["rid-1"]["tool_exec_ms"], 42.0)
        self.assertEqual(indexed["rid-1"]["request_start_wall_ns"], 10_000_000_000)
        self.assertEqual(indexed["rid-1"]["provider_receive_wall_ns"], 10_000_000_000)
        self.assertEqual(indexed["rid-1"]["provider_response_wall_ns"], 10_123_000_000)

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

    def test_aws_lambda_collector_populates_breakdown_and_provider_timestamps(self) -> None:
        class FakeCloudWatch:
            def get_logs(self, resource_type, resource_name, start_time, end_time, request_id=None):
                return [
                    {
                        "timestamp": "1970-01-01T00:00:10.050Z",
                        "message": json.dumps(
                            {
                                "event": "atsuite_function_breakdown",
                                "request_id": "aws-request-1",
                                "app_e2e_ms": 20.0,
                                "tool_exec_ms": 12.0,
                                "request_start_wall_ns": 10_000_000_000,
                                "request_end_wall_ns": 10_020_000_000,
                                "tool_start_wall_ns": 10_004_000_000,
                                "tool_end_wall_ns": 10_016_000_000,
                            }
                        ),
                    }
                ]

            def parse_logs(self, resource_type, logs):
                return {
                    "duration_ms": 25.0,
                    "billed_duration_ms": 100,
                    "memory_used_mb": 64,
                    "memory_limit_mb": 128,
                    "init_duration_ms": 0.0,
                    "is_cold_start": False,
                }

        recorder = RunRecorder(
            provider="aws_lambda",
            observability_provider="aws_lambda_cloudwatch",
            benchmark="Bench",
            trace="trace",
            family="faas",
            config_path="/tmp/config.json",
        )
        recorder.start_run("u1", start_time=1.0)
        recorder.start_node(
            node_id=1,
            node_name="tool.run",
            node_type="function",
            runtime_name="server",
            target_id="server",
            family="faas",
            runtime_config={"memory": 128},
            start_time=1.0,
        )
        recorder.record_invocation(
            node_id=1,
            node_name="tool.run",
            target_id="server",
            runtime_name="server",
            family="faas",
            tool_name="tool_run",
            call_id="call-1",
            status="ok",
            provider_request_id="aws-request-1",
            client_elapsed_ms=30.0,
        )

        collector = AWSCloudWatchCollector(agentcore=False, region="us-east-1")
        collector._cloudwatch = FakeCloudWatch()
        result = collector.collect(
            recorder.context,
            nodes=recorder.nodes,
            invocations=recorder.invocations,
            sessions=recorder.sessions,
        )

        metric = result.metrics[0]
        self.assertEqual(metric.fields["request_start_wall_ns"], 10_000_000_000)
        self.assertEqual(metric.fields["tool_end_wall_ns"], 10_016_000_000)
        self.assertEqual(metric.fields["provider_response_wall_ns"], 10_050_000_000)
        self.assertEqual(metric.fields["provider_receive_wall_ns"], 10_025_000_000)

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
                                "request_start_wall_ns": 1_000_000_000,
                                "request_end_wall_ns": 1_012_000_000,
                                "tool_start_wall_ns": 1_002_000_000,
                                "tool_end_wall_ns": 1_009_500_000,
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
        self.assertEqual(cloudwatch_metric.fields["request_start_wall_ns"], 1_000_000_000)
        self.assertEqual(cloudwatch_metric.fields["tool_end_wall_ns"], 1_009_500_000)
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


class SDKBreakdownTimestampTests(unittest.TestCase):
    def test_function_breakdown_payload_contains_absolute_wall_timestamps(self) -> None:
        sys.modules.pop("atsuite_sdk.function", None)
        with mock.patch.dict(os.environ, {"ATSUITE_NODE_MODULE": "json"}):
            function_module = importlib.import_module("atsuite_sdk.function")

        ctx = {
            "request_id": "rid-1",
            "tool_name": "tool_run",
            "request_start_ns": 1_000,
            "request_wall_ns": 10_000_000_000,
            "tool_start_ns": 2_000,
            "tool_end_ns": 5_000,
            "state_sync_overhead_ms": 1.0,
        }
        payload = function_module._build_function_breakdown_payload(
            ctx,
            request_end_ns=7_000,
            status=200,
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["request_start_wall_ns"], 10_000_000_000)
        self.assertEqual(payload["tool_start_wall_ns"], 10_000_001_000)
        self.assertEqual(payload["tool_end_wall_ns"], 10_000_004_000)
        self.assertEqual(payload["request_end_wall_ns"], 10_000_006_000)

    def test_mcp_breakdown_payload_contains_absolute_wall_timestamps(self) -> None:
        sys.modules.pop("atsuite_sdk.mcp_server", None)
        mcp_module = importlib.import_module("atsuite_sdk.mcp_server")

        ctx = {
            "request_id": "rid-1",
            "jsonrpc_id": "call-1",
            "jsonrpc_method": "tools/call",
            "tool_name": "tool_run",
            "request_start_ns": 1_000,
            "request_wall_ns": 20_000_000_000,
            "tool_start_ns": 3_000,
            "tool_end_ns": 8_000,
            "state_sync_overhead_ms": 0.5,
        }
        payload = mcp_module._build_mcp_breakdown_payload(
            ctx,
            request_end_ns=10_000,
            status=200,
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["request_start_wall_ns"], 20_000_000_000)
        self.assertEqual(payload["tool_start_wall_ns"], 20_000_002_000)
        self.assertEqual(payload["tool_end_wall_ns"], 20_000_007_000)
        self.assertEqual(payload["request_end_wall_ns"], 20_000_009_000)


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
        self.assertIn("trace_path", result)
        self.assertEqual(len(fake_runtime.seen_call_ids), 1)
        self.assertTrue(fake_runtime.seen_call_ids[0].startswith("u1_1_"))


if __name__ == "__main__":
    unittest.main()
