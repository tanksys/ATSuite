# ScientificComputation Benchmark

## 节点设置
| 核心流程                         | 节点数 | 对应节点 id          | 类型分布       |
| -------------------------------- | ------ | -------------------- | -------------- |
| 流程起点                         | 1      | 0                    | logic（start） |
| 任务加载（LLM）                  | 1      | 1                    | llm            |
| 张量创建（MCP）                  | 4      | 2-5                  | mcp            |
| 顺序矩阵运算（MCP）              | 4      | 6-9（含 det 分支）  | mcp+llm        |
| 行列式分支（MCP+LLM）            | 3      | 9-11                 | llm+mcp        |
| 特征 / QR / 基变换（MCP）        | 4      | 12-15                | mcp            |
| 秩计算（MCP）                    | 1      | 16                   | mcp            |
| 并行分支（向量 / 符号 / 绘图）   | 5      | 17-21                | mcp            |
| 中间汇总（LLM）                  | 2      | 22-23                | llm            |
| 清理张量（MCP）                  | 1      | 24                   | mcp            |
| 最终汇总（LLM）                  | 1      | 25                   | llm            |

## Workload Model

ScientificComputation 现在保持 trace 与 tool 返回结构不变，但会在选定的张量计算与 visualization 工具内部执行固定的高强度数值验证、重建和高密度采样路径。这样可以在不增加额外对象存储往返和不放大 LLM 上下文的前提下，显著提高每次 FaaS 调用中的 CPU / 内存计算负载。

保持轻量的工具仍然是张量生命周期和简单代数接口，例如 `scicom_create_tensor`、`scicom_view_tensor`、`scicom_add_matrices`、`scicom_subtract_matrices`、`scicom_scale_matrix`、`scicom_transpose` 以及向量基础运算；高强度路径主要集中在矩阵乘法、逆、分解、秩、基变换和绘图相关工具。

## Node Layout

- `tensor_workspace`: all tensor-backed tools, including tensor lifecycle, matrix algebra, decompositions, and vector algebra
- `vector_calculus`: gradient/curl/divergence/laplacian/directional derivative
- `visualization`: vector-field/function plotting

`task000.json` 现在不再使用单个 `scientific_computing` node，而是显式声明上述 3 个 node。`tensor_workspace` 内部使用现有 `atsuite_sdk.state` 维护同一 target 下的张量工作区，因此不需要额外的 benchmark 专用共享状态层。

## 运行示例

```bash
uv run python -m tools.build \
  --config benchmarks/ScientificComputation/config/faas3_mcp2_min.json \
  --provider aws_lambda

uv run python -m tools.deploy \
  --config benchmarks/ScientificComputation/config/faas3_mcp2_min.json \
  --provider aws_lambda

uv run python -m tools.invoker \
  --config benchmarks/ScientificComputation/config/faas3_mcp2_min.json \
  --url-map url_results/faas3_mcp2_min.json \
  --uid test_user_001 \
  --provider aws_lambda \
  --skip-sleep
```
