# Alibaba Cloud Runtime Notes

## Function Compute

Alibaba Cloud Function Compute (FC) is an event-driven managed compute service. For ATSuite, FC can host tool services and code execution environments.

- [Product overview](https://help.aliyun.com/zh/functioncompute/fc/product-overview/what-is-function-compute)
- [SDK reference](https://help.aliyun.com/zh/functioncompute/fc-3-0/developer-reference/sdk-reference-20230330)

### Code Interpreter

FC is not exposed as a standalone code interpreter product, but its instance isolation, temporary filesystem, resource limits, and timeout controls can be used to build code-interpreter style runtimes.

### MCP

[AgentRun](https://help.aliyun.com/zh/functioncompute/fc/what-is-agentrun) is built on top of FC. It adds agent-oriented runtime semantics, sandbox execution capabilities, and tool calling support. It can host MCP tools as HTTP functions. Stateful behavior usually needs OSS or another external storage service.

### FaaS

FC itself is a FaaS platform. Tool code can be deployed as event functions and exposed through triggers.

## Function AI

Function AI is an FC-based application development platform. It can host MCP servers and expose them to Alibaba Cloud Bailian agents, local agents, or third-party MCP clients.

See [Develop MCP services](https://help.aliyun.com/zh/cap/user-guide/mcp-server).
