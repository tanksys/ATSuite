# LLM UAIBS Trace Export Design

**Date:** 2026-03-22

**Goal:** Make `llm` export traces directly in the UAIBS trace format so captured traces can be used by current UAIBS benchmarks without a separate conversion script.

## Problem

The current `llm` exporter does not match UAIBS expectations in two important ways:

- Tool nodes are emitted as legacy `tool` nodes, while UAIBS only accepts `tool_use`.
- Tool names are emitted as runtime names such as `openapi_explorer_get_api_overview`, while benchmark configs commonly bind trace names like `openapi_explorer.get_api_overview`.

This forces a post-processing step before a captured trace can be replayed by `tools.invoker`.

## Decision

Change `llm` to export UAIBS-compatible traces by default.

- Emit tool nodes as `type: "tool_use"`.
- Keep `logic` and `llm` nodes in the current graph shape.
- Add optional benchmark-config-aware name resolution so runtime tool names can be rewritten to the trace names expected by a benchmark config.
- Fail early when a benchmark config is supplied but a captured tool name cannot be mapped to a trace name.

## Scope

Files to change:

- `llm/trace_catcher_cli.py`
- `llm/trace_catcher.py`
- `llm/deduplicator.py`
- new tests under `tests/`

## Data Flow

1. Proxy captures LLM requests and responses.
2. `TraceCatcher` builds raw `LLMCall` records.
3. `TraceDeduplicator` emits a UAIBS trace.
4. If `--benchmark-config` is provided, tool names are rewritten from runtime names to benchmark trace names during export.

## Error Handling

- If the benchmark config path is invalid, CLI should fail immediately.
- If a captured tool name is not represented by the benchmark config, export should fail with a clear error.
- If no benchmark config is provided, export still succeeds and keeps runtime tool names.

## Testing

Add tests for:

- default tool node type is `tool_use`
- benchmark config rewrites tool names to benchmark trace names
- missing benchmark mapping raises an error
