# LLM UAIBS Trace Export Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `llm` export UAIBS-compatible traces directly, with optional benchmark-config-based tool-name rewriting.

**Architecture:** Keep the existing proxy capture flow and deduplication logic, but change the graph emitter to output UAIBS node types and metadata. Add a small benchmark config resolver that reuses UAIBS naming rules so runtime tool names can be translated to benchmark trace names during export.

**Tech Stack:** Python 3.12, `pytest`, existing `llm` and `uaibs` modules

---

### Task 1: Add failing tests for default UAIBS export

**Files:**
- Create: `tests/test_llm_uaibs_export.py`
- Modify: none
- Test: `tests/test_llm_uaibs_export.py`

**Step 1: Write the failing test**

```python
def test_build_trace_graph_emits_tool_use_nodes():
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_uaibs_export.py::test_build_trace_graph_emits_tool_use_nodes -v`
Expected: FAIL because exporter still emits `tool`

**Step 3: Write minimal implementation**

Update `llm/deduplicator.py` so tool nodes export as `tool_use`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_uaibs_export.py::test_build_trace_graph_emits_tool_use_nodes -v`
Expected: PASS

### Task 2: Add failing tests for benchmark-config name resolution

**Files:**
- Modify: `tests/test_llm_uaibs_export.py`
- Modify: `llm/trace_catcher.py`
- Modify: `llm/deduplicator.py`
- Modify: `llm/trace_catcher_cli.py`

**Step 1: Write the failing test**

```python
def test_build_trace_graph_rewrites_tool_names_from_benchmark_config():
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_uaibs_export.py::test_build_trace_graph_rewrites_tool_names_from_benchmark_config -v`
Expected: FAIL because exporter keeps runtime tool names

**Step 3: Write minimal implementation**

Add benchmark config loading and pass a name resolver into trace building.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_uaibs_export.py::test_build_trace_graph_rewrites_tool_names_from_benchmark_config -v`
Expected: PASS

### Task 3: Add failing tests for unmapped tool names

**Files:**
- Modify: `tests/test_llm_uaibs_export.py`
- Modify: `llm/trace_catcher.py`
- Modify: `llm/trace_catcher_cli.py`

**Step 1: Write the failing test**

```python
def test_build_trace_graph_with_benchmark_config_rejects_unmapped_tool_names():
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_uaibs_export.py::test_build_trace_graph_with_benchmark_config_rejects_unmapped_tool_names -v`
Expected: FAIL because exporter silently keeps the unknown name

**Step 3: Write minimal implementation**

Raise a clear `ValueError` when a benchmark-backed resolver cannot map a tool name.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_uaibs_export.py::test_build_trace_graph_with_benchmark_config_rejects_unmapped_tool_names -v`
Expected: PASS

### Task 4: Verify the full test file

**Files:**
- Modify: `tests/test_llm_uaibs_export.py`
- Modify: `llm/trace_catcher.py`
- Modify: `llm/deduplicator.py`
- Modify: `llm/trace_catcher_cli.py`

**Step 1: Run the focused test file**

Run: `pytest tests/test_llm_uaibs_export.py -v`
Expected: all tests PASS

**Step 2: Sanity-check CLI help if arguments changed**

Run: `python -m llm -h`
Expected: help output includes the new benchmark-config option where relevant
