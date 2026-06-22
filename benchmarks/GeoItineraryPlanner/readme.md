# GeoItineraryPlanner Benchmark

当前 `google_maps` 已按能力域拆分为 4 个独立 node：`google_maps_geocoding`、`google_maps_routing`、`google_maps_places`、`google_maps_elevation`，以减少 FaaS / MCP 冷启动时不必要的全量导入。

| 核心流程 | 节点数 | 对应节点 id | 类型分布 |
| --- | --- | --- | --- |
| 流程起点 | 1 | 0 | logic (start) |
| 任务加载 (LLM) | 1 | 1 | llm |
| 初始映射链（地理编码 + 公园搜索） | 5 | 2-6 | mcp |
| 公园筛选（按车程选 Top3） | 1 | 7 | llm |
| 并行公园富集（分发 LLM） | 1 | 8 | llm |
| 并行公园富集（MCP 操作） | 24 | 9-32 | mcp |
| 富集数据聚合（LLM） | 1 | 33 | llm |
| 风险评估与行程重排序 | 1 | 34 | llm |
| 行程腿构建（LLM） | 1 | 35 | llm |
| 最终路线规划（距离 / 路线 / 海拔） | 3 | 36-38 | mcp |
| 最终行程汇总报告（LLM） | 1 | 39 | llm |

## API Key
运行前通过环境变量或部署平台 secret 注入以下 key。不要把真实 key 提交进仓库。

- `NPS_API_KEY`
- `WEATHER_API_KEY`
- `GOOGLE_MAPS_API_KEY`

## 运行示例

内置 local provider 已移除。使用当前支持的 FaaS 或 Session-MCP provider，例如：

```bash
uv run python -m tools.build \
  --config benchmarks/GeoItineraryPlanner/config/faas17_mcp6_min.json \
  --provider aws_lambda

uv run python -m tools.deploy \
  --config benchmarks/GeoItineraryPlanner/config/faas17_mcp6_min.json \
  --provider aws_lambda

uv run python -m tools.invoker \
  --config benchmarks/GeoItineraryPlanner/config/faas17_mcp6_min.json \
  --url-map url_results/faas17_mcp6_min.json \
  --provider aws_lambda \
  --uid test_user_001 \
  --skip-sleep
```
