# E2B Runtime Notes

E2B is a cloud runtime based on microVMs.

- [Website](https://e2b.dev/)
- [Documentation](https://e2b.dev/docs)

The SDK can create a sandbox and run code directly:

```python
from e2b_code_interpreter import Sandbox

with Sandbox() as sandbox:
    sandbox.run_code("x = 1")
    execution = sandbox.run_code("x += 1; x")
    print(execution.text)
```

For MCP, E2B supports installing MCP servers from source and running local MCP servers:

- [Custom MCP servers](https://e2b.dev/docs/mcp/custom-servers)
- [MCP quickstart](https://e2b.dev/docs/mcp/quickstart)
