# E2B

E2B 是个基于 microVM 的云端运行时，[官网主页](https://e2b.dev/)，[文档主页](https://e2b.dev/docs)

通过官方提供的 SDK 可以直接在上面创建沙箱并运行代码：

```python
# pip install e2b-code-interpreter
from e2b_code_interpreter import Sandbox

# Create a E2B Sandbox
with Sandbox() as sandbox:
    # Run code
    sandbox.run_code("x = 1")
    execution = sandbox.run_code("x+=1; x")

    print(execution.text) # outputs 2
```

对于 MCP 的支持，E2B 允许[安装来自源 的 MCP Servers](https://e2b.dev/docs/mcp/custom-servers)，也支持[本地运行 MCP Servers](https://e2b.dev/docs/mcp/quickstart)