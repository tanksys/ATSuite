# Workflow Specification

ATSuite uses `trace-flow.json` to describe a complete workflow execution, including node inputs, outputs, dependencies, and timing information.

## Node Fields

- `id`: unique node identifier. Node `0` is the source node.
- `name`: call name from the trace. For `tool_use` nodes, this name must be resolvable from the benchmark config.
- `type`: node type.
  - `llm`: simulated or recorded LLM call.
  - `tool_use`: external tool invocation.
  - `logic`: control-flow node with no runtime execution.
  - `sandbox`: legacy type. It is no longer supported by the current runtime path; expose sandbox behavior through an external MCP-Gateway instead.
- `edge_to`: outgoing edges.
  - `id`: next node id.
  - `params`: input parameters passed to the next node.
  - `interval`: delay after this node finishes before the next node starts, in milliseconds.
- `time`: execution time in milliseconds.
- `output`: node output.

## Example

```json
{
  "name": "Travel Planner Easy Task 1",
  "description": "A simple travel planning task using LLM and tools.",
  "deploy_config": "./configs/task1.json",
  "nodes": [
    {
      "id": 0,
      "name": "start",
      "type": "logic",
      "edge_to": [
        {
          "id": 1,
          "params": {
            "input": "Plan a trip from New York to Paris for 2 days."
          },
          "interval": 0
        }
      ],
      "time": 0,
      "output": ""
    },
    {
      "id": 1,
      "name": "llm",
      "type": "llm",
      "edge_to": [
        {
          "id": 2,
          "params": {
            "input": {
              "origin": "New York",
              "destination": "Paris"
            }
          },
          "interval": 20
        }
      ],
      "time": 2357.483837,
      "output": "TrainSearch[New York, Paris]"
    },
    {
      "id": 2,
      "name": "TrainSearch",
      "type": "tool_use",
      "edge_to": [
        {
          "id": 3,
          "params": {
            "input": {
              "destination": "Paris",
              "time": "2023-10"
            }
          },
          "interval": 14
        }
      ],
      "time": 57.986365,
      "output": ""
    }
  ]
}
```
