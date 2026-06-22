from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from atsuite.cli.trace_viewer_metadata import build_enriched_trace_payload


def _repo_root() -> Path:
    cwd = Path.cwd().resolve()
    if (cwd / "web" / "trace_viewer").is_dir():
        return cwd
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
DEFAULT_TRACE = "benchmarks/TravelPlanner/trace/gemini-flash-task002.json"


class TraceViewerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.path = "/web/trace_viewer/"
            return super().do_GET()

        if parsed.path == "/api/trace":
            self._handle_trace_api(parsed)
            return

        return super().do_GET()

    def _handle_trace_api(self, parsed) -> None:
        query = parse_qs(parsed.query)
        rel_path = query.get("path", [DEFAULT_TRACE])[0]
        if not rel_path:
            self._send_json({"error": "Missing path parameter."}, status=400)
            return

        trace_path = (REPO_ROOT / rel_path).resolve()
        if not self._is_safe_path(trace_path):
            self._send_json({"error": "Invalid path."}, status=400)
            return

        if not trace_path.exists():
            self._send_json({"error": "Trace not found."}, status=404)
            return

        try:
            data = build_enriched_trace_payload(trace_path, repo_root=REPO_ROOT)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON file."}, status=400)
            return
        except OSError:
            self._send_json({"error": "Failed to read trace file."}, status=500)
            return

        self._send_json(data)

    def _is_safe_path(self, path: Path) -> bool:
        try:
            path.relative_to(REPO_ROOT)
            return True
        except ValueError:
            return False

    def _send_json(self, data, status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace viewer HTTP server.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host.")
    parser.add_argument("--port", type=int, default=8000, help="Bind port.")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), TraceViewerHandler)
    print(
        f"Serving on http://{args.host}:{args.port}/web/trace_viewer/ "
        f"(API: /api/trace?path=...)"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
