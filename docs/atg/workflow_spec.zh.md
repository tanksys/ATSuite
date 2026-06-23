# Workflow Specification

使用 `trace-flow.json` 来描述整个工作流的执行过程，包括各个步骤的输入输出、依赖关系等信息。

- 节点 (Node) 字段
  - id: 唯一标识符，0 为源点
  - name: trace 中的调用名称；`tool_use.name` 需要能在 benchmark config 中找到对应项
  - type: 节点类型
    - llm: 大模型调用
    - tool_use: 工具调用
    - logic: 逻辑结点，不进行处理
    - sandbox: legacy 类型，当前不再支持；请通过外部 MCP-Gateway 暴露为 `tool_use`
  - edge_to: 出边数组
    - id: 下一个节点的id
    - params: 给下个节点的输入参数
    - interval: 这个 node 执行完，到下个 node 开始执行的时间，单位毫秒
  - time: 执行时间，单位毫秒
  - output: 输出结果

样例：

```
{
  "name": "Travel Planner Easy Task 1",
  "discription": "A simple travel planning task using LLM and tools.",
  "deploy_config", "./configs/task1.json",
  "nodes": [
    {
      "id": 0,
      "name": "start",
      "type": "logic",
      "edge_to": [
        {
          id: 1,
          params: {
            "input": "Plan a trip From to Paris for 2 days."
          },
          interval: 0
        }
      ],
      time: 0,
      output: ""
    },
    {
      "id": 1,
      "name": "llm",
      "type": "llm",
      "edge_to": [
        {
          id: 2,
          params: {
            "input": { 
              "origin": "New York",
              "destination": "Paris",
            }
          },
          interval: 20
        }
      ],
      time: 2357.483837,
      output: "TrainSearch[New York, Paris]"
    },
    {
      "id": 2,
      "name": "TrainSearch",
      "type": "tool_use",
      "edge_to": [
        {
          id: 3,
          params: {
            "input": { 
              "destination": "Paris",
              "time": "2023-10",
            }
          },
          interval: 14
        },
        {
          id: 4,
          params: {
            "input": { 
              "destination": "Paris",
              "time": "2023-10",
            }
          },
          interval: 14
        }
      ],
      time: 57.986365,
      output: ""
    }
  ]
}
```
