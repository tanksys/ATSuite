import argparse
from pathlib import Path

from atsuite.invoker import run_trace
from atsuite.state_snapshot import load_state_snapshot_bundle


def main():
    parser = argparse.ArgumentParser(description="Replay a trace against deployed node URLs.")
    parser.add_argument("--config", required=True, help="Path to benchmark config JSON.")
    parser.add_argument("--url-map", required=True, help="Path to JSON mapping node name to URL.")
    parser.add_argument(
        "--provider",
        required=True,
        choices=["ali_fc", "aws_lambda", "gcp_faas", "ali_agentrun", "aws_agentcore", "gcp_mcp", "mcp_gateway"],
        help="Provider name",
    )
    parser.add_argument("--uid", required=True, help="User ID.")
    parser.add_argument(
        "--trace-file",
        default=None,
        help="Optional trace file path to override trace_file in the config.",
    )
    parser.add_argument("--skip-sleep", action="store_true", default=False, help="Skip sleep between nodes.")
    parser.add_argument("--max-workers", type=int, default=None, help="Maximum number of concurrent ready nodes to execute.")
    parser.add_argument(
        "--state-snapshot",
        default=None,
        help="Optional path to state snapshot JSON (aws_agentcore injects in-request; aws_lambda pre-seeds S3 per UID).",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    url_map_path = Path(args.url_map).resolve()
    state_snapshot_bundle = load_state_snapshot_bundle(Path(args.state_snapshot).resolve()) if args.state_snapshot else None
    run_trace(
        config_path,
        url_map_path,
        args.uid,
        provider=args.provider,
        trace_file=args.trace_file,
        skip_sleep=args.skip_sleep,
        max_workers=args.max_workers,
        state_snapshot_bundle=state_snapshot_bundle,
    )


if __name__ == "__main__":
    main()
