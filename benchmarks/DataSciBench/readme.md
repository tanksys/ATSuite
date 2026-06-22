# DataSciBench Benchmark

DataSciBench contains data-science workflows and state-heavy tool execution traces.

```bash
uv run python -m tools.build \
  --config benchmarks/DataSciBench/config/faas1_mcp1_min.json \
  --provider aws_lambda

uv run python -m tools.deploy \
  --config benchmarks/DataSciBench/config/faas1_mcp1_min.json \
  --provider aws_lambda

uv run python -m tools.invoker \
  --config benchmarks/DataSciBench/config/faas1_mcp1_min.json \
  --url-map url_results/faas1_mcp1_min.json \
  --uid test_user_001 \
  --provider aws_lambda
```

State synchronization experiments were part of the removed experiment-script set. Keep new state tests under `tests/` or promote them into supported benchmark configs before documenting them here.
