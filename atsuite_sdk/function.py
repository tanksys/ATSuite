import importlib
import json
import os
import time

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Type, Optional
from urllib.parse import urlparse

from atsuite_sdk.abstract import registry
from atsuite_sdk.state import get_state_runtime

module_name = os.environ.get("ATSUITE_NODE_MODULE", "implementation")
importlib.import_module(module_name)

TOOLS = registry.functions


def _now_ns() -> int:
    return time.perf_counter_ns()

def _wall_ns() -> int:
    return time.time_ns()


def _ns_to_ms(delta_ns: int) -> float:
    return round(delta_ns / 1_000_000, 3)


def _extract_xray_root_trace_id() -> str:
    header = os.environ.get("_X_AMZN_TRACE_ID", "").strip()
    if not header:
        return ""
    for part in header.split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip() == "Root":
            return value.strip()
    return ""


def _build_function_breakdown_payload(
    ctx: Dict[str, object] | None,
    *,
    request_end_ns: int,
    status: int,
) -> Dict[str, object] | None:
    if not ctx:
        return None
    request_start_ns = ctx.get("request_start_ns")
    tool_start_ns = ctx.get("tool_start_ns")
    tool_end_ns = ctx.get("tool_end_ns")
    if request_start_ns is None or tool_start_ns is None or tool_end_ns is None:
        return None

    app_e2e_ms = _ns_to_ms(request_end_ns - int(request_start_ns))
    tool_exec_ms = _ns_to_ms(int(tool_end_ns) - int(tool_start_ns))
    pre_tool_ms = _ns_to_ms(int(tool_start_ns) - int(request_start_ns))
    post_tool_ms = _ns_to_ms(request_end_ns - int(tool_end_ns))
    framework_overhead_ms = round(max(0.0, app_e2e_ms - tool_exec_ms), 3)
    state_sync_overhead_ms = round(
        float(ctx.get("state_sync_overhead_ms") or 0.0),
        3,
    )

    request_wall_ns = ctx.get("request_wall_ns")
    
    return {
        "event": "atsuite_function_breakdown",
        "request_id": str(ctx.get("request_id") or ""),
        "tool_name": str(ctx.get("tool_name") or ""),
        "status": int(status),
        "app_e2e_ms": app_e2e_ms,
        "tool_exec_ms": tool_exec_ms,
        "state_sync_overhead_ms": state_sync_overhead_ms,
        "framework_overhead_ms": framework_overhead_ms,
        "request_wall_ns": request_wall_ns,
        "pre_tool_ms": pre_tool_ms,
        "post_tool_ms": post_tool_ms,
        "trace_id": _extract_xray_root_trace_id(),
        "service_name": os.environ.get(
            "AWS_LAMBDA_FUNCTION_NAME",
            os.environ.get("K_SERVICE", "atsuite-function"),
        ),
        "timestamp_ms": int(time.time() * 1000),
    }


def _load_allowed_tools() -> set[str] | None:
    manifest_path = os.environ.get("ATSUITE_MANIFEST_PATH", "/app/atsuite-manifest.json")
    if not manifest_path:
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None
    allowed = payload.get("allowed_tools")
    if not isinstance(allowed, list):
        return None
    return {str(item).strip() for item in allowed if str(item).strip()}


_ALLOWED_TOOLS = _load_allowed_tools()
if _ALLOWED_TOOLS is not None:
    TOOLS = {name: tool for name, tool in TOOLS.items() if name in _ALLOWED_TOOLS}


def create_handler() -> Type[BaseHTTPRequestHandler]:
    class ToolHandler(BaseHTTPRequestHandler):
        server_version = "ATSUITEFUNCTION/1.0"

        def log_message(self, format, *args):
            return

        def _clean_path(self) -> str:
            """规范化请求路径，去除访问时的查询参数和尾部斜杠，解决aws lambda web adapter 的请求路径问题"""
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            return path if path else "/"

        def _send_json(self, status: int, payload: Dict, custom_headers: Optional[Dict] = None):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if custom_headers:
                for key, value in custom_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self._clean_path()
            if path in ("/", "/health"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"ok")
                return

            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            path = self._clean_path()
            if path not in ("/run", "/invoke"):
                self._send_json(404, {"error": f"not found (path={self.path!r})"})
                return

            request_id = self.headers.get("X-Request-Id", "").strip()
            trace_header = self.headers.get("X-Cloud-Trace-Context", "").strip()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
            if request_id and project_id:
                trace_full = ""
                if trace_header:
                    part = trace_header.split(";")[0].strip().split("/")[0].strip()
                    if part:
                        trace_full = f"projects/{project_id}/traces/{part}"
                print(json.dumps({"request_id": request_id, "trace": trace_full, "message": "atsuite_request"}, ensure_ascii=False), flush=True)

            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else ""

            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return

            tool_name = payload.get("tool")
            args = payload.get("args", {})

            if not tool_name:
                self._send_json(400, {"error": "missing tool name"})
                return
            
            tool_obj = TOOLS.get(tool_name)
            if not tool_obj:
                self._send_json(404, {"error": f"Tool '{tool_name}' not found"})
                return
            is_stateful = str(tool_obj.stateful).lower()

            request_ctx: Dict[str, object] = {
                "request_id": request_id,
                "tool_name": str(tool_name),
                "request_start_ns": _now_ns(),
                "request_wall_ns": _wall_ns(),
            }
            status = 200
            try:
                request_ctx["tool_start_ns"] = _now_ns()
                try:
                    result = TOOLS[tool_name].execute_from_dict(args)
                finally:
                    request_ctx["tool_end_ns"] = _now_ns()
                    request_ctx["state_sync_overhead_ms"] = (
                        get_state_runtime().get_sync_metrics().get("total_ms", 0.0)
                    )
                if hasattr(result, 'to_dict'):
                    result = result.to_dict(orient="records")
            except Exception as e:
                status = 500
                breakdown = _build_function_breakdown_payload(
                    request_ctx,
                    request_end_ns=_now_ns(),
                    status=status,
                )
                if breakdown is not None:
                    print(json.dumps(breakdown, ensure_ascii=False), flush=True)
                self._send_json(500, {"error": str(e)})
                return

            breakdown = _build_function_breakdown_payload(
                request_ctx,
                request_end_ns=_now_ns(),
                status=status,
            )
            if breakdown is not None:
                print(json.dumps(breakdown, ensure_ascii=False), flush=True)
            self._send_json(200, {"result": result}, custom_headers={"X-Tool-Stateful": is_stateful})

    return ToolHandler


def main():
    host = os.environ.get("FC_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("FC_SERVER_PORT", "9000"))
    handler = create_handler()
    server = HTTPServer((host, port), handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
