# 1. 底层计算平台：Azure Container Apps (ACA)

ACA 是 Azure 的无服务器容器平台，提供 Agent 工具和 MCP Server 的底层运行与托管能力。

*   **访问地址：** [Azure Container Apps 官方文档主页](https://learn.microsoft.com/azure/container-apps/)

## 代码解释器：
可以借助ACA[构建自己的安全执行环境](https://learn.microsoft.com/en-us/azure/container-apps/sessions-code-interpreter) ，通过使用 Azure Container Apps 的“动态会话”功能,上传和下载文件，以及执行代码。

## mcp

*   通用开发模板 (mcp-container-ts)： 使用 **Node.js/TypeScript** 构建 MCP Server 的具体逻辑。
*   访问地址：  [通用开发模板](https://github.com/Azure-Samples/mcp-container-ts)

在开发好上述mcp之后，可以通过该文档部署mcp工具到远程服务器:
[部署mcp](https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/how-to/deploy-remote-mcp-server-microsoft-foundry)


# 2. AI 智能体平台：Azure AI Foundry

这是 Azure 托管 Agent 和集成 MCP 工具的核心环境。说明了如何在 Foundry 中创建 Agent 并通过自定义工具（Custom Tab）接入 MCP 服务。
*   访问地址： [Azure AI Foundry 平台](https://ai.azure.com/nextgen)。

## mcp

Azure AI Foundry 可以直接[调用在上一阶段配置好的mcp工具](https://learn.microsoft.com/en-us/agent-framework/user-guide/model-context-protocol/using-mcp-with-foundry-agents?pivots=programming-language-csharp)来进行工作


## Azure 代码执行器 (Code Interpreter)

[直接在 AI Agent 中使用代码解释器](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/assistant?view=foundry-classic) ，让ai可以直接生成代码并在解释器中执行。
[更详细的使用](https://learn.microsoft.com/zh-cn/azure/ai-foundry/openai/how-to/code-interpreter?view=foundry-classic&tabs=python)

