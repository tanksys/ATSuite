import argparse
import subprocess
import sys
from pathlib import Path

from atsuite.deploy import deploy

def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy nodes on provider.")
    parser.add_argument("--config", required=True, help="Build config JSON path")
    parser.add_argument(
        "--provider",
        required=True,
        choices=["ali_fc", "aws_lambda", "gcp_faas", "ali_agentrun", "aws_agentcore", "gcp_mcp", "mcp_gateway"],
        help="Provider name",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")
    deploy(config_path, args.provider)

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {exc.cmd}", file=sys.stderr)
        if exc.stderr:
            print(f"Error output: {exc.stderr}", file=sys.stderr)
        if exc.stdout:
            print(f"Standard output: {exc.stdout}", file=sys.stderr)
        raise SystemExit(exc.returncode)
