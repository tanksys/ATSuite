# 一、 介绍

## 1. 阿里云函数计算（FC）

阿里云函数计算（FC）是一种事件驱动的全托管计算服务，遵循 Serverless 架构，为 Agent 的工具服务和代码执行提供底层运行与托管能力。
[文档主页](https://help.aliyun.com/zh/functioncompute/fc/product-overview/what-is-function-compute)、[SDK参考](https://help.aliyun.com/zh/functioncompute/fc-3-0/developer-reference/sdk-reference-20230330?spm=a2c4g.11186623.help-menu-2508973.d_9_7_0.5cac2c8eDH0I1S&scm=20140722.H_2679176._.OR_help-T_cn~zh-V_1)

### (1) Code Interpreter

FC 并不直接以 Code Interpreter 作为独立产品形态对外提供，但其实例级隔离、临时文件系统、资源限制和执行超时控制等能力，为构建 Code Interpreter 类代码执行环境提供了底层支撑。

### (2) MCP

[AgentRun](https://help.aliyun.com/zh/functioncompute/fc/what-is-agentrun?spm=a2c4g.11186623.help-menu-2508973.d_3_0.19887d0e6LhJVx&scm=20140722.H_2998769._.OR_help-T_cn~zh-V_1) 构建在 FC 之上，复用其 Serverless 执行、隔离与弹性伸缩能力，并在此基础上引入 Agent 语义层，为 LLM-based Agent 提供托管运行环境、沙箱执行能力及工具调用支持。AgentRun 提供对 MCP 的原生支持，可以托管 MCP 工具对应的执行代码，编写的工具会以 FC 的 HTTP 函数形式运行。用户既可以通过[代码方式创建并注册工具](https://help.aliyun.com/zh/functioncompute/fc/using-the-code-creation-tool?spm=a2c4g.11186623.help-menu-2508973.d_3_7_0.2e0714eeSWwGQn&scm=20140722.H_2999149._.OR_help-T_cn~zh-V_1)，也可以[导入已有工具](https://help.aliyun.com/zh/functioncompute/fc/import-a-tool?spm=a2c4g.11186623.help-menu-2508973.d_3_7_1.74ad4d8fojwLDe&scm=20140722.H_2999151._.OR_help-T_cn~zh-V_1)。由于底层仍为 FC 函数，所以需要引入阿里云对象存储（OSS）实现**有状态**的特性。

### (3) FaaS  
阿里云 FC 本身就是一种 FaaS，用户可以把工具逻辑代码以[创建事件函数](https://help.aliyun.com/zh/functioncompute/fc/user-guide/creating-an-event-function?spm=a2c4g.11186623.help-menu-2508973.d_2_1_0.55e85dd78POSvn&scm=20140722.H_2715295._.OR_help-T_cn~zh-V_1)的形式部署到 FC 上，[创建触发器](https://help.aliyun.com/zh/functioncompute/fc/user-guide/trigger-overview?spm=a2c4g.11186623.help-menu-2508973.d_2_8_0_0.3b22291aFkahi7&scm=20140722.H_2513549._.OR_help-T_cn~zh-V_1)供外界调用。

---

## 2. Function AI

Function AI 是一个基于 FC 的应用开发平台与 AI 服务套件，为开发者提供更高层、更便捷的 AI 应用开发流程。依托 FC 提供的弹性并发能力与对 SSE 等协议的支持， Function AI 提供了用于托管 MCP Server 的运行环境。开发者可以通过 Function AI 控制台将自定义或现有的 MCP Server 部署为云端服务。在获得 MCP 服务的访问配置后，该服务既可以被接入阿里云百炼平台中的 Agent，也可以被本地或第三方 Agent 框架通过 MCP 协议进行调用。具体参见[开发 MCP 服务](https://help.aliyun.com/zh/cap/user-guide/mcp-server?spm=a2c4g.11186623.help-menu-2786334.d_2_2_0.66e271d0NnnQZi&scm=20140722.H_2928696._.OR_help-T_cn~zh-V_1)。

# 二、 部署

下面内容是以 FaaS、MCP 等形式部署到阿里云的示例步骤。

## 1. FaaS

以 benchmarks/soccer/config/detect_league_function.json 为例，将 node 以 FaaS 形式部署到阿里云的步骤为：  

1. [获取](https://help.aliyun.com/zh/ram/user-guide/create-an-accesskey-pair)阿里云 AccessKey ID 和 AccessKey Secret；[获取](https://help.aliyun.com/zh/functioncompute/fc/developer-reference/fc-endpoints)阿里云 FC 的 endpoint；在阿里云 ACR [创建](https://help.aliyun.com/zh/acr/user-guide/create-a-container-registry-personal-edition-instance?spm=a2c4g.11174283.help-menu-60716.d_2_15_0.5efa671beg2IDn&scm=20140722.H_205066._.OR_help-T_cn~zh-V_1)容器仓库并获取仓库地址

2. 在本地 ~/.bashrc 文件中添加

```text
export ALIBABA_CLOUD_ACCESS_KEY_ID="你的阿里云 AccessKey ID"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="你的阿里云 AccessKey Secret"
export ALI_ENDPOINT="你的阿里云FC endpoint"
export ACR_NAME="你的阿里云容器仓库地址"
```

之后在终端运行   

```bash
source ~/.bashrc
```

3. 构建本地 docker 镜像，在项目根目录运行  

```bash
uv run -m tools.build_docker_images --config benchmarks/soccer/config/detect_league_function.json --provider ali_fc
```

4. 将本地镜像上传到阿里云 ACR，在 FC 创建事件函数与对应 HTTP 触发器，在项目根目录运行

```bash
uv run -m tools.deploy --config benchmarks/soccer/config/detect_league_function.json --provider ali_fc
```

> [!TIP]  
> 首次运行可能需要登录阿里云 Container Registry：
```bash
docker login --username="你的阿里云账号用户名" "仓库域名"
```

运行成功后，会在 url_results/ 文件夹下看到新生成的 json 文件（示例文件是 detect_league_function.json），里面保存了 HTTP 触发器的公网访问地址   

5. 运行 invoker 进行测试，在项目根目录运行

```bash
uv run -m tools.invoker --config benchmarks/soccer/config/detect_league_function.json --url-map url_results/detect_league_function.json --provider ali_fc --uid abc
```

其中 uid 是当前用户 id，在 FaaS 形式中无所谓，主要为了 MCP 形式的有状态特性。如果输出类似

```text
Running node: 0, name: start, type: logic, time: 0.0
Running node: 1, name: llm-thought-step1, type: llm, time: 1521.4295029873028
Running node: 2, name: llm-action-step1, type: llm, time: 1346.1970059433952
Running node: 3, name: detect_league.run, type: tool_use, time: 0.003196997568011284
Running node: 4, name: llm-thought-step2, type: llm, time: 2301.0629700729623
Running node: 5, name: llm-action-step2, type: llm, time: 1195.8588510751724
```

说明部署成功

---

## 2. MCP

以 benchmarks/TravelPlanner/config/notebook_mcp.json 为例，将 node 以 MCP 形式部署到阿里云的步骤为：  

1. 在 **以 FaaS 形式部署** 的基础上，开通[阿里云 OSS 服务](https://help.aliyun.com/zh/oss/user-guide/what-is-oss?spm=a2c4g.11186623.help-menu-31815.d_0_0_0.1e1246efkYMToy&scm=20140722.H_31817._.OR_help-T_cn~zh-V_1)并在本地 ~/.bashrc 文件中添加

```text
export OSS_ACCESS_KEY_ID="你的阿里云 AccessKey ID"
export OSS_ACCESS_KEY_SECRET="你的阿里云 AccessKey Secret"
```

之后在终端运行   

```bash
source ~/.bashrc
```

2. 构建本地 docker 镜像，在项目根目录运行  

```bash
uv run -m tools.build_docker_images --config benchmarks/TravelPlanner/config/notebook_mcp.json --provider ali_agentrun
```

3. 将本地镜像上传到阿里云 ACR，在 FC 创建事件函数与对应 HTTP 触发器，在项目根目录运行

```bash
uv run -m tools.deploy --config benchmarks/TravelPlanner/config/notebook_mcp.json --provider ali_agentrun
```

运行成功后，会在 url_results/ 文件夹下看到新生成的 json 文件（示例文件是 notebook_mcp.json），里面保存了 HTTP 触发器的公网访问地址   

4. 运行 invoker 进行测试，在项目根目录运行

```bash
uv run -m tools.invoker --config benchmarks/TravelPlanner/config/notebook_mcp.json --url-map url_results/notebook_mcp.json --provider ali_agentrun --uid abc
```

如果输出类似

```text
Running node: 0, name: start, type: logic, time: 0.0
Running node: 1, name: notebook.reset, type: tool_use, time: 0.0007040071068331599
Running node: 2, name: llm-thought-step2, type: llm, time: 3369.629763998091
Running node: 3, name: llm-action-step3, type: llm, time: 6710.714197004563
Running node: 4, name: notebook.write, type: tool_use, time: 0.006777991075068712
Running node: 5, name: llm-thought-step4, type: llm, time: 2036.3573969952995
Running node: 6, name: llm-action-step8, type: llm, time: 1782.11894701235
Running node: 7, name: notebook.write, type: tool_use, time: 0.002658998710103333
Running node: 8, name: llm-action-step12, type: llm, time: 2124.9955730017973
Running node: 9, name: notebook.list_all, type: tool_use, time: 10.144970001420006
Running node: 10, name: llm-action-step12, type: llm, time: 2124.9955730017973
```

说明部署成功

---
