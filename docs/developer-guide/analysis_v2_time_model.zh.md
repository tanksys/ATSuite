# Analyzer V2 时间模型

本文说明 ATSuite Analysis V2 中几个端到端时间字段的来源、打点位置和计算方式。目标是让报告中的 `run_user_e2e_ms`、`client_e2e_ms`、`app_e2e_ms`、`tool_exec_ms`、`compute_time_ms`、`idle_time_ms` 等字段可以被一致解释。

## 1. 总体原则

V2 同时记录两类时间：

- **Client/replay 时间**：由本地 replay executor 记录，使用 `time.time()`。用于描述 benchmark run、trace node、runtime invoke 在客户端视角下经历了多久。
- **Cloud/app 时间**：由容器内 `atsuite_sdk` wrapper 记录，使用 `time.perf_counter_ns()`。用于描述请求进入 ATSuite wrapper 后，工具函数真正执行了多久，以及 wrapper 自身带来的开销。

V2 不用 client 和云端机器的绝对 timestamp 直接相减。跨机器时钟只用于日志检索窗口和 evidence join；真正进入报告的时间基本都是单侧测得的 duration。

## 2. 文字泳道图：FaaS 调用

下面是一次 FaaS tool invocation 的时间边界。

```text
Client / Replay
  run_start
    ...
    node_start
      parse args / attach state snapshot / scheduler bookkeeping
      call_id = <uid>_<node_id>_<client_time_us>
      client_invoke_start
        RuntimeAdapter.invoke()
        HTTP POST /run, X-Request-Id = call_id
      client_invoke_end
      record InvocationObservation(client_elapsed_ms)
    node_end
    ...
  run_end

Cloud Provider
  provider ingress
    queue / routing / cold start / container startup
    invoke ATSuite function wrapper
  provider egress
  provider logs: request id, duration, init/cold-start, memory, etc.

ATSuite SDK Function Wrapper
  receive HTTP request
  parse request / find tool
  request_start_ns
    tool_start_ns
      user tool code executes
      optional state backend load/save/sync
    tool_end_ns
    build response
  request_end_ns
  print atsuite_function_breakdown JSON log

Analyzer V2
  read events.json
  collect provider logs
  join by provider_request_id and/or call_id
  normalize ProviderMetric
  aggregate node/run totals
```

FaaS 的 cloud/app breakdown 来自 `atsuite_sdk.function` 输出的 `atsuite_function_breakdown` 日志。关键字段：

- `request_id`: client 传入的 `call_id`。
- `request_start_ns`: wrapper 内部开始计时。FaaS 当前在 body 解析和 tool 定位之后打点；MCP 当前在 middleware 读取 body 后、FastMCP dispatch 前打点。
- `tool_start_ns`: 调用 tool function 前。
- `tool_end_ns`: tool function 返回或抛错后。
- `request_end_ns`: wrapper 发送响应前。

## 3. 文字泳道图：Session / MCP 调用

Session-MCP 与 FaaS 的主要差异是 session 可能先于 tool call 打开，并且状态一致性由平台或 MCP server 侧处理。

```text
Client / Replay
  run_start
    ...
    node_start
      parse args / attach state snapshot
      call_id = <uid>_<node_id>_<client_time_us>
      open_session(target, uid)             # first call for this target only
        MCP initialize or provider session binding
      client_invoke_start
        RuntimeAdapter.invoke()
        MCP tools/call, X-Request-Id = call_id
        JSON-RPC id = call_id
      client_invoke_end
      record InvocationObservation(client_elapsed_ms, session_id)
    node_end
    ...
  run_end

Cloud Provider / MCP Platform
  provider ingress
    route to existing session/server
    enforce provider-side state concurrency
    invoke MCP server
  provider egress
  provider logs: request id, session id, runtime logs, usage logs

ATSuite SDK MCP Wrapper
  middleware receives HTTP/MCP request
  request_start_ns
    FastMCP dispatch
    tool_start_ns
      user tool code executes
      optional state runtime sync
    tool_end_ns
    emit atsuite_mcp_breakdown JSON log
  response completes

Analyzer V2
  read events.json
  collect provider/runtime logs
  join breakdown by call_id / jsonrpc_id / provider_request_id
  collect delayed session usage logs for pricing when available
  aggregate node/run totals
```

当前 MCP wrapper 在 tool wrapper 的 `finally` 中发出 `atsuite_mcp_breakdown`，因此成功 tool call 的 `request_end_ns` 通常等于 `tool_end_ns`。也就是说，MCP 的 `app_e2e_ms` 表示从 middleware 收到请求到 tool 执行结束的时间；响应序列化和网络回传主要体现在 client/provider latency 中，而不一定进入 `app_e2e_ms`。

## 4. 字段计算

### 4.1 Run 级别

`run_user_e2e_ms`

```text
run_user_e2e_ms = (run_end - run_start) * 1000
```

- `run_start`: analyzer `start_run()` 时记录，发生在 trace replay 开始前。
- `run_end`: trace DAG 执行完成后传入 analyzer，发生在 cleanup 和日志采集等待之前。
- 包含：trace replay 的 wall-clock 时间、LLM sleep、edge interval sleep、tool node 执行、scheduler 等待。
- 不包含：run 后的 FaaS state cleanup、provider log ingestion wait、analysis/export 时间。

`total_node_user_e2e_ms`

```text
total_node_user_e2e_ms = sum(node.user_e2e_ms for all nodes)
```

它是节点时间求和，不是 wall-clock。存在并发节点时，它可以大于 `run_user_e2e_ms`。

### 4.2 Node 级别

`user_e2e_ms`

```text
node.user_e2e_ms = (node_end - node_start) * 1000
```

- `node_start`: replay executor 准备执行该 trace node 时记录。
- `node_end`: 该 node 完成时记录。
- 对 tool node，包含 client 侧参数解析、state snapshot 注入、首次 session open、runtime invoke 和事件记录。
- 对 LLM node，主要是按 trace 中记录的 LLM 时间 sleep。
- 对 logic node，通常接近 0。

`idle_time_ms`

```text
idle_time_ms = max(0, node.user_e2e_ms - compute_time_ms - initialize_time_ms)
```

这里的 idle 是 residual。它不一定只代表云平台 idle，也可能包括 client 侧调度、参数准备、session open、等待依赖、LLM sleep 或 collector 没有拿到更细 breakdown 时留下的未解释时间。

### 4.3 Invocation 级别

`client_e2e_ms`

```text
client_e2e_ms = client_invoke_end - client_invoke_start
```

- 由 `RuntimeAdapter.invoke()` 内部测量。
- FaaS：覆盖 `FunctionClient.invoke()` 的 HTTP request/response。
- MCP：覆盖 MCP `tools/call` request/response。
- 不包含：tool node 里 runtime invoke 之前的参数解析和 session open。
- 包含：本地 HTTP client、网络、provider gateway、平台排队/冷启动、container/app 执行、响应回传。

`provider_duration_ms`

报告的 invocation row 中 `provider_duration_ms` 取：

```text
provider_duration_ms = duration_ms if available else elapsed_time_ms
```

`duration_ms` 通常来自 provider logs，例如 AWS Lambda REPORT、GCP Cloud Run request latency、Ali SLS duration。若 collector 没有拿到 provider duration，则 fallback 到 runtime 返回的 `client_e2e_ms`。

## 5. Cloud/app breakdown

FaaS 和 MCP wrapper 都会输出结构化 JSON 日志：

- `atsuite_function_breakdown`
- `atsuite_mcp_breakdown`

Analyzer collector 从 provider logs 中解析这些字段，并写入 `ProviderMetric.fields`。

`app_e2e_ms`

```text
app_e2e_ms = request_end_ns - request_start_ns
```

含义：请求进入 ATSuite wrapper 后，到 wrapper 认为本次 app/tool 处理结束之间的时间。

`tool_exec_ms`

```text
tool_exec_ms = tool_end_ns - tool_start_ns
```

含义：用户 tool function 本身的执行时间。它是最接近论文里“tool execution”的时间。

`pre_tool_ms`

```text
pre_tool_ms = tool_start_ns - request_start_ns
```

含义：wrapper 收到请求后，到真正调用 tool 前的时间，例如解析、调度、FastMCP wrapper 等。

`post_tool_ms`

```text
post_tool_ms = request_end_ns - tool_end_ns
```

含义：tool 返回后，到 wrapper 结束处理前的时间，例如结果转换和响应构造。当前 MCP 成功路径通常在 `tool_end_ns` 处发出 breakdown，因此 `post_tool_ms` 多数为 0。

`framework_overhead_ms`

```text
framework_overhead_ms = max(0, app_e2e_ms - tool_exec_ms)
```

它包括 `pre_tool_ms + post_tool_ms`，以及 wrapper 层其它非 tool 代码时间。

`state_sync_overhead_ms`

```text
state_sync_overhead_ms = get_state_runtime().get_sync_metrics()["total_ms"]
```

它由 SDK state runtime 上报。FaaS/state-decoupled 模式下主要对应状态对象 load/save/sync；Session/MCP 模式下通常由平台侧保持状态，具体值取决于 SDK state runtime 是否实际执行同步。

## 6. Aggregator 如何得到报告字段

每个 node 会聚合属于该 node 的 invocation metrics。

`compute_time_ms`

```text
if sum(tool_exec_ms) > 0:
    compute_time_ms = sum(tool_exec_ms)
elif sum(duration_ms) > 0:
    compute_time_ms = sum(duration_ms)
else:
    compute_time_ms = sum(elapsed_time_ms)
```

因此优先级是：

1. SDK wrapper 上报的 tool execution 时间。
2. provider 上报的 duration。
3. runtime/client fallback elapsed。

这个 fallback 很重要：如果 provider log 没 join 上，`compute_time_ms` 可能退化为 client elapsed；如果 provider log join 上但没有 SDK breakdown，则 `tool_exec_ms` 会是 0，而 `compute_time_ms` 可能来自 provider duration。

`initialize_time_ms`

```text
initialize_time_ms = sum(init_duration_ms)
```

当前只有 collector 明确写入 `init_duration_ms` 的 provider 会贡献该字段，例如 AWS Lambda REPORT 的 init duration。Session 初始化事件不会自动计入这个字段；它通常体现在 node `user_e2e_ms` 或 client/provider latency 中。

`platform_time_ms`

```text
if collector provides platform_time_ms:
    platform_time_ms = sum(platform_time_ms)
elif client_e2e_ms > 0 and app_e2e_ms > 0:
    platform_time_ms = max(0, client_e2e_ms - app_e2e_ms)
else:
    platform_time_ms = 0
```

含义：client 看到的端到端时间中，未被 app wrapper 时间覆盖的部分。它混合了网络、gateway、平台排队、冷启动和响应传输等因素。若 provider collector 能给出更细平台指标，则使用 collector 的字段。

`network_time_ms`

```text
network_time_ms = sum(network_time_ms from collector)
```

当前 V2 不强行估算 network；collector 没提供时为 0。

Summary 中的 `total_*`

```text
total_client_e2e_ms = sum(node.client_e2e_ms)
total_app_e2e_ms = sum(node.app_e2e_ms)
total_tool_exec_ms = sum(node.tool_exec_ms)
total_compute_time_ms = sum(node.compute_time_ms)
total_idle_time_ms = sum(node.idle_time_ms)
total_platform_time_ms = sum(node.platform_time_ms)
total_network_time_ms = sum(node.network_time_ms)
```

这些是 node totals 的求和，不是整个 run 的 wall-clock 分解。并发执行时，总和可以大于 `run_user_e2e_ms`。

## 7. Provider join 差异

### AWS Lambda

- Client 传 `X-Request-Id = call_id`。
- Runtime 返回 AWS request id。
- Collector 按 Lambda log group 查询 CloudWatch logs，解析 REPORT 得到 `duration_ms`、`billed_duration_ms`、`memory_usage_mb`、`init_duration_ms`。
- Collector 同时解析 `atsuite_function_breakdown` / `atsuite_mcp_breakdown`，用 provider request id 或 `call_id` join app/tool breakdown。

### AWS AgentCore

- Client 传 `X-Request-Id = call_id`，JSON-RPC `id = call_id`。
- Runtime 返回 `x-amzn-RequestId` 和 `Mcp-Session-Id`。
- Collector 按 runtime 拉 CloudWatch application logs，再用 `call_id`、provider request id 或 JSON-RPC id join `atsuite_mcp_breakdown`。
- Usage logs 可能延迟约 30 分钟。Analyzer 在线路径会轮询 usage logs 后再计费；这影响 price，不改变 run/app/tool 时间边界。

### GCP

- Client 传 `X-Request-Id = call_id`。
- Function wrapper 会输出 request id 与 Cloud Trace id 的映射。
- Collector 从 Cloud Logging 中将 `request_id -> trace -> httpRequest.latency` 连接起来，得到 provider request latency。
- Collector 解析 JSON payload / text payload 中的 ATSuite breakdown，补齐 `app_e2e_ms` 和 `tool_exec_ms`。

### Ali

- Collector 当前主要查询 SLS `InvokeFunction` 记录，得到 provider duration、memory、cold-start 相关字段。
- V2 当前 Ali collector 没有把 SDK breakdown logs 合并进主 metrics；因此 Ali 报告中 `app_e2e_ms` / `tool_exec_ms` 可能为 0，`compute_time_ms` 会 fallback 到 provider duration 或 client elapsed。

### MCP Gateway / none

- 若没有 gateway observability collector，V2 使用 runtime 返回的 request metadata 和 client elapsed。
- 此时 `client_e2e_ms` 有值，`app_e2e_ms` 和 `tool_exec_ms` 通常为 0。

## 8. 读报告时的注意事项

- `run_user_e2e_ms` 是 run wall-clock；`total_*` 大多是按 node/invocation 求和。
- `node.user_e2e_ms` 和 `client_e2e_ms` 不同：前者包含 replay node 内的 client 侧准备和可能的 session open；后者只覆盖一次 runtime invoke。
- `app_e2e_ms` 和 `tool_exec_ms` 依赖 SDK breakdown log join。日志没 join 上时，这两个字段会是 0。
- `compute_time_ms` 是按优先级 fallback 得到的“可解释 compute”；它不一定等于 `tool_exec_ms`。
- `platform_time_ms = client_e2e_ms - app_e2e_ms` 是 duration 级估算，不是跨机器 timestamp 相减。
- Analyzer 的日志采集等待、report export、state cleanup 不进入 `run_user_e2e_ms`；cleanup 单独作为 state event 服务计费。
