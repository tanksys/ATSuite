# 阿里云运行时介绍

## 函数计算 FC

阿里云函数计算（FC）是一种事件驱动的全托管计算服务，可为 ATSuite 的工具服务和代码执行环境提供底层运行与托管能力。

- [产品概览](https://help.aliyun.com/zh/functioncompute/fc/product-overview/what-is-function-compute)
- [SDK 参考](https://help.aliyun.com/zh/functioncompute/fc-3-0/developer-reference/sdk-reference-20230330)

### Code Interpreter

FC 不直接以独立 Code Interpreter 产品形态对外提供，但它的实例隔离、临时文件系统、资源限制和执行超时控制可用于构建代码执行环境。

### MCP

[AgentRun](https://help.aliyun.com/zh/functioncompute/fc/what-is-agentrun) 构建在 FC 之上，增加 Agent 语义、沙箱执行能力和工具调用支持。MCP 工具可以作为 HTTP 函数托管。若工具需要有状态能力，通常需要配合 OSS 等外部存储。

### FaaS

FC 本身就是 FaaS 平台。工具逻辑可以以事件函数形式部署，并通过触发器对外调用。

## Function AI

Function AI 是基于 FC 的应用开发平台，可以托管 MCP Server，并接入阿里云百炼 Agent、本地 Agent 或第三方 MCP 客户端。

参见：[开发 MCP 服务](https://help.aliyun.com/zh/cap/user-guide/mcp-server)。
