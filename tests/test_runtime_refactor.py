from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atsuite.pipeline import CliOverrides, get_provider_spec, resolve_benchmark
from atsuite.runtime import (
    FunctionRuntimeAdapter,
    GatewayClient,
    InvocationRequest,
    MCPRuntimeAdapter,
    RuntimeTarget,
)
from atsuite.scheduler import AccessScheduler, ToolAccess


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class PipelineSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "Bench"
        (self.root / "nodes" / "notebook").mkdir(parents=True)
        _write_json(
            self.root / "trace" / "trace.json",
            {
                "nodes": [
                    {"id": 0, "name": "start", "type": "logic", "edge_to": [{"id": 1, "params": {"input": {}}}]},
                    {"id": 1, "name": "notebook.write", "type": "tool_use", "edge_to": []},
                ]
            },
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()
        resolve_benchmark.cache_clear()

    def test_legacy_stateful_maps_to_domain_access(self) -> None:
        config = self.root / "config" / "bench.json"
        _write_json(
            config,
            {
                "trace_file": "./trace/trace.json",
                "nodes": [
                    {
                        "name": "notebook",
                        "dir": "./nodes/notebook",
                        "trace_names": [{"name": "notebook.write", "stateful": True}],
                    }
                ],
                "pipeline": {
                    "faas": {
                        "units": [
                            {
                                "name": "notebook",
                                "node": "notebook",
                                "trace_names": ["notebook.write"],
                                "deploy": {"cpu": 1, "memory": 1024, "disk": 512, "timeout": 30},
                            }
                        ]
                    }
                },
            },
        )
        resolved = resolve_benchmark(config, "aws_lambda", CliOverrides())
        route = resolved.routes["notebook.write"]
        self.assertEqual(route.domain, "notebook")
        self.assertEqual(route.access, "rw")
        self.assertTrue(route.tool_access.is_stateful)

    def test_sandbox_config_is_unsupported(self) -> None:
        config = self.root / "config" / "sandbox.json"
        _write_json(
            config,
            {
                "trace_file": "./trace/trace.json",
                "nodes": [{"name": "sandbox", "type": "sandbox", "dir": "./nodes/notebook"}],
            },
        )
        with self.assertRaises(SystemExit):
            resolve_benchmark(config, "aws_lambda", CliOverrides())

    def test_provider_registry_excludes_local_and_includes_gateway(self) -> None:
        self.assertEqual(get_provider_spec("mcp_gateway").family, "session")
        with self.assertRaises(SystemExit):
            get_provider_spec("local")


class AccessSchedulerTests(unittest.TestCase):
    def test_faas_read_write_lock_semantics(self) -> None:
        scheduler = AccessScheduler(enabled=True)
        read = ToolAccess.from_values("notes", "r")
        write = ToolAccess.from_values("notes", "rw")

        scheduler.start(read)
        self.assertTrue(scheduler.can_start(read))
        self.assertFalse(scheduler.can_start(write))
        scheduler.finish(read)

        scheduler.start(write)
        self.assertFalse(scheduler.can_start(read))
        scheduler.finish(write)
        self.assertTrue(scheduler.can_start(read))

    def test_session_scheduler_is_passthrough(self) -> None:
        scheduler = AccessScheduler(enabled=False)
        first = ToolAccess.from_values("notes", "rw")
        second = ToolAccess.from_values("notes", "rw")
        scheduler.start(first)
        self.assertTrue(scheduler.can_start(second))


class RuntimeContractTests(unittest.TestCase):
    def test_function_runtime_invokes_with_namespace_session(self) -> None:
        class FakeFunctionClient:
            def __init__(self, url: str):
                self.url = url

            def invoke(self, tool_name, args, request_id=None):
                self.seen = (tool_name, args, request_id)
                return "provider-request", True

        adapter = FunctionRuntimeAdapter("aws_lambda")
        adapter.connect({"targets": {"notebook": "https://example.test"}})
        with mock.patch("atsuite.faas.function.FunctionClient", FakeFunctionClient):
            session = adapter.open_session(RuntimeTarget("notebook", "faas", "https://example.test"), "u1")
            result = adapter.invoke(
                InvocationRequest(
                    target_id="notebook",
                    tool_name="notebook_write",
                    args={"uid": "u1"},
                    uid="u1",
                    call_id="client-request",
                    session=session,
                )
            )
        self.assertEqual(session.provider_session_id, "")
        self.assertEqual(result.provider_request_id, "provider-request")
        self.assertTrue(result.provider_metadata["is_stateful"])

    def test_session_runtime_opens_once_and_reuses_client(self) -> None:
        class FakeMCPClient:
            init_calls = 0

            def __init__(self, url: str, uid: str = ""):
                self.url = url
                self.uid = uid
                self.session_id = "session-1"
                self._initialized = False

            def initialize(self):
                FakeMCPClient.init_calls += 1
                self._initialized = True
                return "init-request"

            def invoke(self, tool_name, args, request_id=None):
                return "tool-request"

        adapter = MCPRuntimeAdapter("gcp_mcp")
        adapter.connect({"targets": {"server": "https://example.test"}})
        with mock.patch("atsuite.mcp.mcp.MCPClient", FakeMCPClient):
            target = RuntimeTarget("server", "session", "https://example.test")
            session_a = adapter.open_session(target, "u1")
            session_b = adapter.open_session(target, "u1")
            result = adapter.invoke(
                InvocationRequest(
                    target_id="server",
                    tool_name="tool",
                    args={"uid": "u1"},
                    uid="u1",
                    session=session_b,
                )
            )
        self.assertEqual(FakeMCPClient.init_calls, 1)
        self.assertEqual(session_a.provider_session_id, "session-1")
        self.assertEqual(result.provider_request_id, "tool-request")

    def test_gateway_registration_consumes_endpoint(self) -> None:
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"endpoint": "https://gateway.example/mcp"}

        with mock.patch.dict("os.environ", {"MCP_GATEWAY_URL": "https://gateway.example"}):
            with mock.patch("requests.post", return_value=FakeResponse()) as post:
                endpoint = GatewayClient().register_target(
                    name="server",
                    image="registry.example/server:latest",
                    resources={"cpu": 1},
                    manifest={"allowed_tools": ["tool"]},
                )
        self.assertEqual(endpoint, "https://gateway.example/mcp")
        self.assertEqual(post.call_args.kwargs["json"]["image"], "registry.example/server:latest")


if __name__ == "__main__":
    unittest.main()
