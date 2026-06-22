# ClaudeCodeReview Benchmark

`ClaudeCodeReview` is a replayable benchmark for Claude-style multi-PR code review runs.

It models a single review session that:

- enumerates every pending PR from fixture data
- reviews them one by one in a single trace
- cross-checks structured PR patches against a materialized git repository
- returns `reviews: [...]`, one verdict per PR

The benchmark exposes two nodes through one MCP server:

- `workspace_tools`
  - `LS`
  - `Glob`
  - `Grep`
  - `Read`
  - `TodoWrite`
- `repo_git`
  - `repo_git_list_pull_requests`
  - `repo_git_get_pr_overview`
  - `repo_git_list_changed_files`
  - `repo_git_get_patch`
  - `repo_git_diff_between_refs`
  - `repo_git_show_file_at_ref`
  - `repo_git_log_for_path`
  - `repo_git_blame_range`
  - `repo_git_show_commit`

## Benchmark Layout

- `nodes/repo_files`: Claude-style workspace tools
- `nodes/repo_git`: explicit PR and git inspection tools
- `data/repo_fixture.json`: base repository history
- `data/pr_fixture.json`: structured pending PR records with full patch/diff payloads
- `data/materialize_fixture_repo.py`: materializes `main`, `pr/<id>`, and `refs/pull/<id>/head`
- `task_prompt.md`: recommended Claude Code prompt
- `claude/settings.template.json`: Claude Code MCP config template
- `trace/claude-code-review-task000.json`: replayable trace that reviews all PRs in one run

## Build

```bash
uv run python -m tools.build \
  --config benchmarks/ClaudeCodeReview/config/faas2_mcp1_min.json \
  --provider aws_lambda
```

## Deploy

```bash
uv run python -m tools.deploy \
  --config benchmarks/ClaudeCodeReview/config/faas2_mcp1_min.json \
  --provider aws_lambda
```

## Replay

```bash
uv run python -m tools.invoker \
  --config benchmarks/ClaudeCodeReview/config/faas2_mcp1_min.json \
  --url-map url_results/faas2_mcp1_min.json \
  --uid claude_code_review_demo \
  --provider aws_lambda \
  --trace-file benchmarks/ClaudeCodeReview/trace/gemini-flash-task001.json \
  --skip-sleep
```

## Claude Code Capture Flow

The previous local capture flow depended on the removed local runtime and trace-catcher module. Keep newly captured traces in `trace/` and replay them through the supported ATSuite providers.
