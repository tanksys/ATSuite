# AWS Runtime Notes

## Lambda and ECS

On AWS, Lambda and ECS are common ways to host MCP servers or tool runtimes. AWS provides an official sample that packages an MCP server into Lambda and exposes it through a Function URL: [sample-serverless-mcp-servers](https://github.com/aws-samples/sample-serverless-mcp-servers).

## AgentCore

AWS Bedrock AgentCore provides a managed layer for agent runtimes and tools.

### Code Interpreter

AgentCore offers a code interpreter API. It can be used either through an agent that generates code or directly through client calls:

- [Build agents with code interpreter](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-building-agents.html)
- [Use code interpreter directly](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-using-directly.html)

Direct usage example:

```python
from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
import json

code_client = CodeInterpreter("<Region>")
code_client.start()

try:
    response = code_client.invoke("executeCode", {
        "language": "python",
        "code": 'print("Hello World!!!")'
    })

    for event in response["stream"]:
        print(json.dumps(event["result"], indent=2))
finally:
    code_client.stop()
```

### MCP

AgentCore also documents the full MCP flow from development to local testing, remote deployment, and invocation: [Deploy an MCP runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html).
