# aws lambda/ecs
在 AWS 上，Lambda/ecs 是运行 MCP Server 最主流的方式  
在AWS 的官方 GitHub 示例中，展示了将 MCP Server 封装进 Lambda，并通过 Function URL 暴露出去的方法，[实现示例](https://github.com/aws-samples/sample-serverless-mcp-servers) 

而对于代码解释器，AWS 在后台使用类似 Lambda 的技术实现了沙箱，只需要调用 API即可,具体文档在下方
# aws agentcore
## 代码解释器

而对于代码解释器，在agentcore层面提供了封装并提供了两种方式，[使用代码解释器](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html)，包括: 
* [通过agent执行代码](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-building-agents.html)(ai 自己生成代码并执行)、
* 编写代码并[直接使用代码解释器](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-using-directly.html)

直接使用代码解释器示例
``` python
from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
import json

# Initialize the Code Interpreter client for your region
code_client = CodeInterpreter('<Region>')

# Start a Code Interpreter session
code_client.start()

try:
    # Execute Python code
    response = code_client.invoke("executeCode", {
        "language": "python",
        "code": 'print("Hello World!!!")'
    })

    # Process and print the response
    for event in response["stream"]:
        print(json.dumps(event["result"], indent=2))

finally:
    # Always clean up the session
    code_client.stop()
```

## mcp
在agentcore中，参考文档提供了完整的流程，从创建到本地测试到远程部署最终调用：
[开发并部署mcp](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html)