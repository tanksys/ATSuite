# Install just: brew install just / cargo install just
default:
    @just --list

sync:
    uv sync

sync-ali:
    uv sync --group aliyun

sync-aws:
    uv sync --group aws

sync-gcp:
    uv sync --group gcp

travelplanner-config := "benchmarks/TravelPlanner/config/faas7_mcp2_min.json"
travelplanner-urlmap := "url_results/faas7_mcp2_min.json"

aws-faas-build:
    uv run python -m tools.build --config {{ travelplanner-config }} --provider aws_lambda

aws-faas-deploy:
    uv run python -m tools.deploy --config {{ travelplanner-config }} --provider aws_lambda

aws-faas-replay uid="aws-test-user":
    uv run python -m tools.invoker --config {{ travelplanner-config }} --url-map {{ travelplanner-urlmap }} --provider aws_lambda --uid {{ uid }}

aws-mcp-build:
    uv run python -m tools.build --config {{ travelplanner-config }} --provider aws_agentcore

aws-mcp-deploy:
    uv run python -m tools.deploy --config {{ travelplanner-config }} --provider aws_agentcore

aws-mcp-replay uid="aws-mcp-test-user":
    uv run python -m tools.invoker --config {{ travelplanner-config }} --url-map {{ travelplanner-urlmap }} --provider aws_agentcore --uid {{ uid }}

gcp-faas-build:
    uv run python -m tools.build --config {{ travelplanner-config }} --provider gcp_faas

gcp-faas-deploy:
    uv run python -m tools.deploy --config {{ travelplanner-config }} --provider gcp_faas

gcp-faas-replay uid="gcp-test-user":
    uv run python -m tools.invoker --config {{ travelplanner-config }} --url-map {{ travelplanner-urlmap }} --provider gcp_faas --uid {{ uid }}

gcp-mcp-build:
    uv run python -m tools.build --config {{ travelplanner-config }} --provider gcp_mcp

gcp-mcp-deploy:
    uv run python -m tools.deploy --config {{ travelplanner-config }} --provider gcp_mcp

gcp-mcp-replay uid="gcp-mcp-test-user":
    uv run python -m tools.invoker --config {{ travelplanner-config }} --url-map {{ travelplanner-urlmap }} --provider gcp_mcp --uid {{ uid }}

ali-faas-build:
    uv run python -m tools.build --config {{ travelplanner-config }} --provider ali_fc

ali-faas-deploy:
    uv run python -m tools.deploy --config {{ travelplanner-config }} --provider ali_fc

ali-faas-replay uid="ali-test-user":
    uv run python -m tools.invoker --config {{ travelplanner-config }} --url-map {{ travelplanner-urlmap }} --provider ali_fc --uid {{ uid }}

ali-mcp-build:
    uv run python -m tools.build --config {{ travelplanner-config }} --provider ali_agentrun

ali-mcp-deploy:
    uv run python -m tools.deploy --config {{ travelplanner-config }} --provider ali_agentrun

ali-mcp-replay uid="ali-mcp-test-user":
    uv run python -m tools.invoker --config {{ travelplanner-config }} --url-map {{ travelplanner-urlmap }} --provider ali_agentrun --uid {{ uid }}

trace-viewer port="8000":
    uv run python -m tools.trace_viewer_server --port {{ port }}
