# Azure Runtime Notes

## Azure Container Apps

Azure Container Apps (ACA) is a serverless container platform. It can host agent tools and MCP servers.

- [Azure Container Apps documentation](https://learn.microsoft.com/azure/container-apps/)

### Code Interpreter

ACA dynamic sessions can be used to build isolated code execution environments with file upload, file download, and code execution support:

- [Code interpreter sessions](https://learn.microsoft.com/en-us/azure/container-apps/sessions-code-interpreter)

### MCP

Microsoft provides an MCP container template based on Node.js and TypeScript:

- [mcp-container-ts](https://github.com/Azure-Samples/mcp-container-ts)

After implementing the MCP server, it can be deployed as a remote MCP server:

- [Deploy a remote MCP server](https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/how-to/deploy-remote-mcp-server-microsoft-foundry)

## Azure AI Foundry

Azure AI Foundry can host agents and integrate custom MCP tools:

- [Azure AI Foundry](https://ai.azure.com/nextgen)
- [Use MCP with Foundry agents](https://learn.microsoft.com/en-us/agent-framework/user-guide/model-context-protocol/using-mcp-with-foundry-agents?pivots=programming-language-csharp)

Azure OpenAI also provides assistant-level code interpreter support:

- [Assistants](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/assistant?view=foundry-classic)
- [Code interpreter](https://learn.microsoft.com/zh-cn/azure/ai-foundry/openai/how-to/code-interpreter?view=foundry-classic&tabs=python)
