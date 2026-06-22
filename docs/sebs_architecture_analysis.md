# SeBS 架构分析：异构云平台的 Docker 镜像生成与函数/工作流部署机制

## 概述

SeBS (Serverless Benchmark Suite) 是一个支持多云平台的 FaaS 基准测试框架。本文档分析其如何为异构云平台（AWS、Azure、GCP、OpenWhisk、Local）生成 Docker 镜像，以及如何部署不同的函数和工作流。

## 1. 架构设计

### 1.1 核心组件

- **`sebs/`**: 核心 Python 代码库，包含各云平台的适配器
- **`dockerfiles/`**: 各平台和语言的 Dockerfile 模板
- **`config/systems.json`**: 平台配置，定义基础镜像、依赖包等

### 1.2 设计模式

采用**策略模式**和**工厂模式**：
- 每个云平台实现统一的 `System` 接口
- 通过 `SeBS.get_deployment()` 工厂方法创建平台实例
- 统一的函数/工作流抽象类，各平台提供具体实现

## 2. Docker 镜像生成机制

### 2.1 镜像分层架构

```
基础镜像 (Base Image)
    ↓
平台特定 Dockerfile.build (添加平台工具和依赖)
    ↓
运行时镜像 (用于安装依赖和打包)
```

### 2.2 镜像类型

根据 `config/systems.json` 配置，每个平台支持不同的镜像类型：

1. **build**: 用于在容器内安装依赖和打包代码
2. **run**: 用于本地运行和测试（仅 Local）
3. **function**: 用于 OpenWhisk 的函数镜像
4. **manage**: 用于 Azure/GCP 的管理镜像

### 2.3 平台特定的 Dockerfile 结构

#### AWS Lambda (Python)
```dockerfile
# dockerfiles/aws/python/Dockerfile.build
FROM amazon/aws-lambda-python:3.11  # 使用 AWS 官方基础镜像
# 安装构建工具 (yum, shadow-utils)
# 复制安装脚本和入口脚本
CMD /bin/bash /sebs/installer.sh
ENTRYPOINT ["/sebs/entrypoint.sh"]
```

#### Azure Functions (Python)
```dockerfile
# dockerfiles/azure/python/Dockerfile.build
FROM mcr.microsoft.com/azure-functions/python:4-python3.11
# 安装构建工具 (apt-get, gosu)
# 复制安装脚本和入口脚本
```

#### GCP Cloud Functions (Python)
```dockerfile
# dockerfiles/gcp/python/Dockerfile.build
FROM ubuntu:22.04
# 安装 Python 和构建工具
# 创建虚拟环境
```

### 2.4 镜像构建流程

**构建脚本**: `tools/build_docker_images.py`

```python
# 根据配置构建所有镜像
python tools/build_docker_images.py --deployment aws --language python
```

构建过程：
1. 读取 `config/systems.json` 获取基础镜像配置
2. 根据平台、语言、版本选择对应的 Dockerfile
3. 使用 Docker API 构建镜像，标签格式：`{repo}:{type}.{platform}.{language}.{version}`
4. 推送到 Docker Registry（可选）

### 2.5 依赖安装机制

**安装脚本**: `dockerfiles/python_installer.sh`

```bash
# 在容器内执行
cd /mnt/function
pip3 install -r requirements.txt -t .python_packages/lib/site-packages
# 如果存在 package.sh，执行自定义打包脚本
```

**入口脚本**: `dockerfiles/entrypoint.sh`
- 创建非 root 用户（使用 gosu）
- 设置权限和环境变量
- 执行构建命令

## 3. 代码打包流程

### 3.1 Benchmark 类的作用

`sebs/benchmark.py` 中的 `Benchmark` 类负责：

1. **代码收集**: 从基准测试目录复制源代码
2. **添加平台适配器**: 复制平台特定的 handler 文件
3. **添加依赖配置**: 更新 requirements.txt 或 package.json
4. **Docker 构建**: 在 Docker 容器内安装依赖
5. **平台特定打包**: 调用各平台的 `package_code()` 方法

### 3.2 平台特定的打包方式

#### AWS Lambda
```python
# sebs/aws/aws.py - package_code()
# 1. 创建 function/ 目录，移动所有文件
# 2. handler.py 保留在根目录
# 3. 创建 ZIP 压缩包
zip -r {benchmark}.zip * .
```

#### Azure Functions
```python
# sebs/azure/azure.py - package_code()
# 1. 创建 function/ 目录结构
# 2. 添加 function.json 绑定配置
# 3. 添加 host.json 配置文件
# 4. 保持目录结构（不压缩）
```

#### GCP Cloud Functions
```python
# sebs/gcp/gcp.py - package_code()
# 1. 创建 ZIP 压缩包
# 2. 上传到 GCS bucket
```

### 3.3 Docker 构建集成

在 `Benchmark.install_dependencies()` 中：

```python
# 1. 拉取或使用本地构建镜像
image_name = f"build.{deployment}.{language}.{runtime}"
docker_client.images.get(repo_name + ":" + image_name)

# 2. 挂载代码目录到容器
volumes = {output_dir: {"bind": "/mnt/function", "mode": "rw"}}

# 3. 运行容器安装依赖
docker_client.containers.run(
    image_name,
    volumes=volumes,
    environment={"CONTAINER_UID": str(os.getuid()), ...},
    remove=True
)
```

## 4. 函数部署机制

### 4.1 统一的部署接口

所有平台实现 `System` 抽象类：

```python
class System(ABC):
    @abstractmethod
    def create_function(self, code_package: Benchmark, func_name: str) -> Function:
        pass
    
    @abstractmethod
    def package_code(self, code_package: Benchmark, directory: str, 
                     is_workflow: bool, is_cached: bool) -> Tuple[str, int]:
        pass
```

### 4.2 AWS Lambda 部署

**流程**:
1. `package_code()`: 创建 ZIP 包
2. 上传到 S3（如果包太大）
3. `create_function()`: 调用 boto3 Lambda API
4. 配置运行时、内存、超时等参数
5. 创建 IAM 角色和策略

**关键代码** (`sebs/aws/aws.py`):
```python
def create_function(self, code_package: Benchmark, func_name: str):
    # 上传代码包
    if code_size > 50 * 1024 * 1024:  # 50MB
        # 上传到 S3
        s3_client.upload_file(package, bucket, key)
        code = {"S3Bucket": bucket, "S3Key": key}
    else:
        with open(package, "rb") as f:
            code = {"ZipFile": f.read()}
    
    # 创建 Lambda 函数
    response = lambda_client.create_function(
        FunctionName=func_name,
        Runtime=f"python{version}",
        Role=role_arn,
        Handler="handler.handler",
        Code=code,
        Timeout=timeout,
        MemorySize=memory
    )
```

### 4.3 Azure Functions 部署

**流程**:
1. `package_code()`: 创建目录结构，添加 `function.json`
2. 使用 Azure CLI 部署函数应用
3. 配置应用设置和连接字符串

**关键代码** (`sebs/azure/azure.py`):
```python
def create_function(self, code_package: Benchmark, func_name: str):
    # 使用 Azure CLI 部署
    azure_cli.functionapp_deployment_source_config_zip(
        resource_group, function_app_name, package_path
    )
    
    # 创建函数
    azure_cli.functionapp_function_create(
        resource_group, function_app_name, func_name, function_json
    )
```

### 4.4 GCP Cloud Functions 部署

**流程**:
1. `package_code()`: 创建 ZIP 包
2. 上传到 Cloud Storage
3. 使用 Cloud Functions API 部署

**关键代码** (`sebs/gcp/gcp.py`):
```python
def create_function(self, code_package: Benchmark, func_name: str):
    # 上传到 GCS
    storage_client.upload_file(package, bucket, object_name)
    
    # 部署函数
    functions_client.create_function(
        parent=parent,
        function={
            "name": func_name,
            "source_archive_url": f"gs://{bucket}/{object_name}",
            "runtime": f"python{version}",
            "entry_point": "handler",
            ...
        }
    )
```

## 5. 工作流部署机制

### 5.1 工作流抽象

工作流由多个函数组成，通过平台特定的编排服务连接：

- **AWS**: Step Functions (SFN)
- **Azure**: Durable Functions
- **GCP**: Cloud Workflows

### 5.1.1 工作流定义格式

工作流使用统一的 JSON 格式定义（`definition.json`），然后转换为平台特定格式：

```json
{
  "root": "start",
  "states": {
    "start": {
      "type": "task",
      "func_name": "function1",
      "next": "middle"
    },
    "middle": {
      "type": "parallel",
      "parallel_functions": [
        {
          "root": "branch1_start",
          "states": {
            "branch1_start": {
              "type": "task",
              "func_name": "function2"
            }
          }
        },
        {
          "root": "branch2_start",
          "states": {
            "branch2_start": {
              "type": "task",
              "func_name": "function3"
            }
          }
        }
      ],
      "next": "end"
    },
    "end": {
      "type": "task",
      "func_name": "function4"
    }
  }
}
```

**支持的状态类型**:
- `task`: 执行单个函数
- `parallel`: 并行执行多个子工作流
- `switch`: 条件分支
- `map`: 对数组中的每个元素执行函数
- `loop`: 循环执行函数
- `repeat`: 重复执行函数指定次数

### 5.2 工作流定义生成

使用 **FSM (Finite State Machine)** 抽象：

```python
# sebs/faas/fsm.py
class State(ABC):
    pass

class Task(State):  # 执行函数
class Parallel(State):  # 并行执行
class Switch(State):  # 条件分支
class Map(State):  # 映射执行
class Loop(State):  # 循环执行
```

### 5.3 AWS Step Functions 生成

**生成器**: `sebs/aws/generator.py` - `SFNGenerator`

```python
class SFNGenerator(Generator):
    def __init__(self, func_arns: Dict[str, str]):
        # func_arns: 函数名 -> Lambda ARN 的映射
        self._func_arns = func_arns
    
    def encode_task(self, state: Task) -> dict:
        return {
            "Name": state.name,
            "Type": "Task",
            "Resource": self._func_arns[state.func_name],  # Lambda ARN
            "Parameters": {
                "request_id.$": "$.request_id",
                "payload.$": "$.payload",
            },
            "ResultPath": "$.payload",
            "Next": state.next,
        }
    
    def encode_parallel(self, state: Parallel) -> dict:
        # 为每个并行分支生成状态机定义
        branches = []
        for subworkflow in state.funcs:
            states = {n: State.deserialize(n, s) for n, s in subworkflow["states"].items()}
            branch = {
                "StartAt": subworkflow["root"],
                "States": {n: self.encode_state(s) for n, s in states.items()}
            }
            branches.append(branch)
        
        return {
            "Name": state.name,
            "Type": "Parallel",
            "Branches": branches,
            "ResultSelector": {
                "payload": {...},  # 合并各分支结果
                "request_id.$": "$[0].request_id",
            },
        }
```

**部署流程** (`sebs/aws/aws.py` - `create_workflow()`):
1. 读取工作流定义文件 `definition.json`
2. 部署所有组成函数（Lambda）：
   ```python
   code_files = list(code_package.get_code_files(include_config=False))
   func_names = [os.path.splitext(os.path.basename(p))[0] for p in code_files]
   funcs = [self.create_function(code_package, workflow.name + "___" + fn) 
            for fn in func_names]
   ```
3. 生成 Step Functions 状态机定义：
   ```python
   gen = SFNGenerator({n: f.arn for (n, f) in zip(func_names, funcs)})
   gen.parse(definition_path)  # 解析 definition.json
   definition = gen.generate()  # 生成 SFN JSON
   ```
4. 创建状态机：
   ```python
   sfn_client.create_state_machine(
       name=workflow_name,
       definition=definition,
       roleArn=lambda_role_arn
   )
   ```

### 5.4 Azure Durable Functions 生成

**特点**: 使用代码定义工作流（而非 JSON）

```python
# sebs/azure/azure.py - package_code()
if is_workflow:
    # 重命名 main_workflow.py 为 main.py
    # 添加 function.json 绑定配置
    # 配置 orchestrator 和 activity triggers
```

**部署**: 与函数部署相同，但需要特殊的绑定配置

### 5.5 GCP Cloud Workflows 生成

**生成器**: `sebs/gcp/generator.py` - `GCPGenerator`

```python
class GCPGenerator(Generator):
    def __init__(self, workflow_name: str, func_triggers: Dict[str, str]):
        # func_triggers: 函数名 -> HTTP trigger URL 的映射
        self._func_triggers = func_triggers
    
    def encode_task(self, state: Task) -> List[dict]:
        url = self._func_triggers[state.func_name]
        return [
            {
                state.name: {
                    "call": "http.post",
                    "args": {
                        "url": url,
                        "body": {"request_id": "${request_id}", "payload": "${payload}"},
                        "timeout": 900,
                    },
                    "result": "payload"
                }
            },
            {
                f"assign_payload_{state.name}": {
                    "assign": [{"payload": "${payload.body}"}]
                }
            }
        ]
    
    def encode_parallel(self, state: Parallel) -> List[dict]:
        # GCP Workflows 使用 parallel 步骤
        branches = []
        for subworkflow in state.funcs:
            states = {n: State.deserialize(n, s) for n, s in subworkflow["states"].items()}
            branch_steps = [self.encode_state(s) for s in states.values()]
            branches.append({"steps": branch_steps})
        
        return [{
            state.name: {
                "parallel": {
                    "shared": ["payload", ...],  # 共享变量
                    "branches": branches
                }
            }
        }]
    
    def postprocess(self, payloads: List[dict]) -> dict:
        # 添加输入处理和最终返回
        assign_input = {
            "assign_input": {
                "assign": [
                    {"payload": "${input.payload}"},
                    {"request_id": "${input.request_id}"}
                ]
            }
        }
        return_res = {"final": {"return": ["${payload}"]}}
        return {
            "main": {
                "params": ["input"],
                "steps": [assign_input] + payloads + [return_res]
            }
        }
```

**部署流程** (`sebs/gcp/gcp.py`):
1. 部署所有组成函数（Cloud Functions）
2. 获取函数的 HTTP trigger URLs
3. 生成工作流定义（YAML/JSON）
4. 创建 Cloud Workflow：
   ```python
   workflows_client.create_workflow(
       parent=parent,
       workflow={
           "name": workflow_name,
           "source_contents": yaml.dump(definition)
       }
   )
   ```

## 6. 缓存机制

### 6.1 代码包缓存

- **位置**: `Cache` 类管理本地缓存目录
- **键**: `{deployment}/{language}/{benchmark}/{hash}`
- **内容**: 代码包路径、大小、哈希值

### 6.2 函数缓存

- **存储**: JSON 文件，包含函数 ARN、配置等
- **验证**: 比较代码哈希，决定是否需要更新

### 6.3 缓存更新策略

```python
# sebs/faas/system.py - get_function()
if function.code_package_hash != code_package.hash:
    # 代码已更改，更新云函数
    self.update_function(function, code_package)
else:
    # 使用缓存
    self.logging.info("Using cached function")
```

## 7. 配置系统

### 7.1 systems.json 结构

```json
{
  "general": {
    "docker_repository": "spcleth/serverless-benchmarks"
  },
  "aws": {
    "languages": {
      "python": {
        "base_images": {
          "3.11": "amazon/aws-lambda-python:3.11"
        },
        "images": ["build"],
        "deployment": {
          "files": ["handler_function.py", "storage.py"],
          "packages": ["redis"]
        }
      }
    }
  }
}
```

### 7.2 配置作用

- **base_images**: 定义各版本的基础镜像
- **images**: 定义需要构建的镜像类型
- **deployment.files**: 平台特定的包装文件
- **deployment.packages**: 平台特定的依赖包

## 8. 总结

### 8.1 关键设计决策

1. **统一接口**: 所有平台实现相同的 `System` 接口
2. **Docker 隔离**: 使用 Docker 容器确保依赖安装的一致性
3. **平台适配**: 通过不同的 Dockerfile 和打包逻辑适配各平台
4. **缓存优化**: 避免重复构建和部署
5. **工作流抽象**: 使用 FSM 统一工作流定义，然后转换为平台特定格式

### 8.2 扩展性

- **添加新平台**: 实现 `System` 类，添加 Dockerfile 和配置
- **添加新语言**: 在 `systems.json` 中添加配置，创建对应的 Dockerfile
- **添加新基准测试**: 实现基准测试接口，放置在 `benchmarks/` 目录

### 8.3 优势

1. **跨平台一致性**: 同一基准测试可在多个平台运行
2. **自动化**: 完全自动化的构建和部署流程
3. **可重现性**: Docker 镜像确保环境一致性
4. **灵活性**: 支持函数和工作流两种部署模式

## 9. 完整部署流程图

### 9.1 函数部署流程

```
用户代码 (benchmark)
    ↓
Benchmark.build()
    ├─ 复制源代码
    ├─ 添加平台适配器 (handler.py, storage.py)
    ├─ 添加依赖配置 (requirements.txt)
    └─ install_dependencies()
        └─ Docker 容器内安装依赖
            ├─ 拉取/使用 build 镜像
            ├─ 挂载代码目录
            └─ 执行 pip install
    ↓
System.package_code()
    ├─ AWS: 创建 ZIP 包
    ├─ Azure: 创建目录结构 + function.json
    └─ GCP: 创建 ZIP 包
    ↓
System.create_function()
    ├─ AWS: boto3 Lambda API
    ├─ Azure: Azure CLI
    └─ GCP: Cloud Functions API
    ↓
函数部署完成
```

### 9.2 工作流部署流程

```
工作流定义 (definition.json)
    ↓
解析 FSM 状态
    ├─ Task, Parallel, Switch, Map, Loop
    ↓
部署所有组成函数
    └─ 为每个函数调用 create_function()
    ↓
生成平台特定工作流定义
    ├─ AWS: SFNGenerator → Step Functions JSON
    ├─ Azure: 代码生成 → Durable Functions Python
    └─ GCP: GCPGenerator → Cloud Workflows YAML
    ↓
部署工作流
    ├─ AWS: sfn_client.create_state_machine()
    ├─ Azure: functionapp_function_create()
    └─ GCP: workflows_client.create_workflow()
    ↓
工作流部署完成
```

## 10. 文件结构总结

```
sebs-flow-implementation/
├── dockerfiles/              # Docker 镜像定义
│   ├── aws/
│   │   └── python/Dockerfile.build
│   ├── azure/
│   │   └── python/Dockerfile.build
│   ├── gcp/
│   │   └── python/Dockerfile.build
│   └── local/
│       └── python/Dockerfile.build
├── sebs/                     # 核心代码库
│   ├── aws/                  # AWS 适配器
│   │   ├── aws.py           # 主类
│   │   ├── function.py      # Lambda 函数
│   │   ├── workflow.py      # Step Functions 工作流
│   │   └── generator.py     # SFN 定义生成器
│   ├── azure/                # Azure 适配器
│   ├── gcp/                  # GCP 适配器
│   ├── benchmark.py          # 代码打包逻辑
│   ├── sebs.py              # 主入口
│   └── faas/
│       ├── system.py         # 系统抽象接口
│       └── function.py       # 函数抽象
├── config/
│   └── systems.json          # 平台配置
└── tools/
    └── build_docker_images.py # 镜像构建脚本
```
