### **阶段一：MVP 与 核心链路验证 (The Skeleton)**

**目标**：不追求自动化，优先跑通**“本地 Agent + 云端 Tool”**的混合运行模式。手动抽离和部署流程的可行性。

#### 1. 定义数据交互协议 (The Wire Protocol)

* **任务**：制定 Trace 的格式，能够手动讲本地的 Benchmark 的运行过程保存成 workflow 形式的描述。
* **产出**：
- [X] [workflow_spec.md](./workflow_spec.md)：定义 Trace 的结构.
- [X] benchmark/travel_planner/traces/：具体的 Trace 示例文件，记录 TravelPlanner Benchmark 的完整运行。

#### 2. 手动抽离与容器化 (Manual Node Extraction)

* **任务**：对一个 Benchmark（如 TravelPlanner）的一个工具函数进行完整的部署。
* **产出**：
- [X] 制定容器化标准
- [ ] 编写 `Dockerfile`：将提取的工具代码打包进去。
  - [ ] Ali 的 Dockerfile
  - [X] AWS 的 Dockerfile

#### 3. 云端部署与联调 (Manual Deployment)

* **任务**：能够手动把一个 Node 推送到云厂商（如阿里云 FC 或 AWS Lambda）。
* **产出**：
- [ ] 获取云端具体的 Endpoint URL。
- [ ] 编写本地测试脚本 `invoke.py`，验证网络连通性和参数传递是否正确。
  - [X] 调通 local 的 sandbox

---

### **阶段二：自动化与标准化体系 (The System)**

**目标**：自动将整个 benchmark 的所有结点进行云端部署，能够根据 workflow 进行重新运行

#### 1. 自动化部署引擎 (Automated Deployer)

* **任务**：取代手动 Docker Build 和手动上传。
* **产出**：
- [ ] 编写 `deployer.py`：读取 `manifest.yaml`，自动完成 `Build -> Push -> Deploy -> Return URL` 的全过程。


#### 2. 执行器

- **任务**：依据 workflow 进行执行
- [ ] 编写 执行器：读取具体的 Benchmark 的 workflow 定义，进行执行
- [ ] 允许切换模式：
  - [ ] 本地
  - [ ] 替换 Tool Node
  - [ ] 替换 LLM Node

---

### **阶段三：全链路指标观测系统 (The Observer)**

**目标**：在链路通畅的基础上，引入**分布式追踪（Tracing）**和**指标收集（Metrics）**，解决“黑盒无法归因”的问题。

#### 1. 三维指标收集 (Metric Collection)

* **任务**：分别在“本地”和“云端”埋点，捕捉关键时间戳。
* **关键指标定义**：
* **Agent 编排耗时** (): 框架本身的处理开销。
* **网络传输耗时**: 客户端发出请求到服务端收到请求的时间差。
* **云端冷启动与执行**: 从云平台日志（CloudWatch/SLS）中提取 `Billing Duration` 和 `Init Duration`。
* **内存消耗**: 记录云端峰值内存（Max Memory Used）。

#### 2. 数据持久化与初步分析

* **任务**：将收集到的日志落盘。
* **产出**：
- [ ] 编写一个简单的分析脚本 `analyzer.py`，读取日志并计算出：对于同一个 Task，不同云厂商（手动切换 URL 测试）的总耗时对比。

#### 3. 标准化手册与 SDK (Documentation & SDK)

* **任务**：让其他人能接入新的 Benchmark 或新的云厂商。
* **产出**：
* **Integration Manual**：教用户如何写 `manifest.yaml` 来描述他们的工具 DAG。
* **Cost Calculator**：内置各大云厂商计费公式，直接输出“完成这个 Benchmark 需要多少钱”。
