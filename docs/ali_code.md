# Ali 平台部署设计说明

本文档说明如何封装阿里云 SDK，将 node 部署到阿里云上。

**目前支持：**   

**FaaS 形式**：将 node 统一管理与部署到阿里云函数计算（FC）服务上，对外提供统一的部署接口，对内封装镜像推送、函数创建、触发器配置等阿里云平台相关细节，为上层 benchmark / agent 系统提供云函数运行能力。  

**MCP形式**：将 node 统一管理与部署到阿里云 FC 服务上，与 FaaS 不同的是利用阿里云对象存储（OSS）实现 MCP 的**有状态性**。

---

## 1. 类简介

### (1) `atsuite/ali/ali.py` 中的 `Ali` 类

`Ali` 类是阿里云平台的接入与管理入口，负责统一创建和管理阿里云各种服务的 client，并作为服务调用的高层封装接口。

### (2) `atsuite/ali/function.py` 中的 `AliFC` 类

`AliFC` 类实现了 `FunctionBase` 抽象接口，是阿里云 FC 平台上的函数级抽象，用于描述和管理一个具体的云函数实例。该类封装了一个函数“镜像推送、函数创建、触发器创建、URL 获取”的原子化完整部署流程，对外暴露 `deploy()` 接口。

### (3) `atsuite/faas/function.py` 中的 `AliFunctionDeployer` 类

`AliFunctionDeployer` 类是对 `Ali` 和 `AliFC` 的进一步封装，专注于按 benchmark 节点批量部署云函数。初始化时通过 bench_name 标识当前 benchmark 实例，并创建统一的 Ali 客户端。该类屏蔽了函数配置解析、镜像管理、部署执行等低层细节，使 benchmark 任务可快速启动和管理多个函数节点。

### (4) `atsuite/mcp/mcp.py` 中的 `AliMCPDeployer` 类

`AliMCPDeployer` 类与 `AliFunctionDeployer` 类似，是对 `Ali` 和 `AliFC` 的进一步封装，专注于按 benchmark 节点批量部署云函数。

### (5) `atsuite/ali/oss.py` 中的 `AliOSS` 类

`AliOSS` 类实现了 `StorageBase` 抽象接口，是阿里云对象存储（OSS）平台上的函数级抽象，提供对阿里云存储文件的操作接口。

### (6) `atsuite/ali/sls.py` 中的 `AliSLS` 类

`AliSLS` 类是阿里云日志服务（SLS）平台上的函数级抽象，提供对阿里云日志服务的操作接口。

---

## 2. 类结构

### (1) `Ali` 类

**成员属性：**

- `self.fc_client: FC20230330Client | None` ：访问阿里云 FC 的客户端

**方法说明：**

- `get_fc_client(self) -> FC20230330Client`  
  创建并返回阿里云 FC Client

- `deploy_function(self, **kwargs) -> AliFC`  
  创建一个 `AliFC` 对象，`**kwargs` 透传给 `AliFC` 构造函数

- `deploy_mcp(self, **kwargs) -> AliFC`  
  创建一个 `AliFC` 对象，`**kwargs` 透传给 `AliFC` 构造函数

---

### (2) `AliFC` 类

**成员属性：**

- `self.client: FC20230330Client` ：已初始化的 FC Client，由 Ali 类提供    
- `self.typ: str` ：部署类型，默认为 `function`
- `self.url: str | None` ：函数部署完成后的 HTTP 触发器公网 URL  
- `self.function_name: str` ：函数名称  
- `self.entrypoint: list` ：容器入口命令  
- `self.tag: str` ：本地 Docker 镜像的 tag  
- `self.runtime: str` ：运行时类型，默认为 `custom-container`  
- `self.cpu: int` ：CPU 核数，默认为 1  
- `self.memory_size: int` ：内存大小（MB），默认为 1024  
- `self.timeout: int` ：函数超时时间（秒），默认为 60  
- `self.disk_size: int` ：临时磁盘大小（MB），默认为 512  
- `self.trigger_type: str` ：触发器类型，默认为 `http`  
- `self.trigger_config: str` ：触发器配置 JSON，默认为  

```json
{
  "authType": "anonymous",
  "disableURLInternet": false,
  "methods": ["GET","POST","PUT","DELETE"]
}
```

**方法说明：**  

- `deploy(self) -> str`  
  执行完整的函数部署流程，返回 HTTP 触发器公网访问 URL 

- `create_acr(tag: str) -> str`  
  静态方法，接收参数为本地 Docker 镜像的 `tag`，将其推送至阿里云 ACR，返回 ACR 上的完整镜像地址

- `create_function(self, image: str)`  
  接收参数为 ACR 的镜像地址 `image`，使用阿里云 FC SDK 创建函数

- `create_trigger(self) -> str`  
  为函数创建 HTTP 触发器，返回公网访问 URL 

---

### (3) `AliFunctionDeployer` 类

**成员属性：**

- `self.bench_name: ` ：benchmark 的名字
- `self.ali: ` ：`Ali` 对象实例

**方法说明：**

- `deploy_node(self, node_name: str, node_dir: Path) -> Optional[str]`  
  接收参数为节点名和节点目录，加载函数配置，自动调用 `Ali` 的 `deploy_function` 方法以及 `AliFC` 的 `deploy` 方法完成部署并返回公网访问 URL

---

### (4) `AliMCPDeployer` 类

**成员属性：**

- `self.bench_name: ` ：benchmark 的名字
- `self.ali: ` ：`Ali` 对象实例

**方法说明：**

- `deploy_node(self, service_name: str, node_dir: Path) -> Optional[str]`  
  接收参数为节点的服务名称和节点目录，加载函数配置，自动调用 `Ali` 的 `deploy_mcp` 方法以及 `AliFC` 的 `deploy` 方法完成部署并返回公网访问 URL

---

### (5) `AliOSS` 类

**成员属性：**

- `self.bucket` ：项目在 OSS 上的存储空间   
- `self.client` ：访问阿里云 OSS 的客户端     

**方法说明：**  

- `create_oss_client(self, location: str)`  
  接收参数 `location` 为阿里云服务所在地域，该函数创建并返回阿里云 OSS Client   
  
- `ensure_bucket_exists(self)`  
  确保存储空间存在，不存在则创建   

- `upload(self, key: str, filepath: str)`  
  接收参数为对象（object）的名称 `key` 与本地文件路径，该方法可以直接将本地完整文件上传到指定的 bucket 中   

- `download(self, key: str, filepath: str)`  
  接收参数为 object 的名称与要保存到的本地路径，该方法可以直接将指定 object 下载到本地

- `append(self, key: str, data)`  
  接收参数为 object 的名称与要写入的数据，该方法可以在已上传的 object 中直接追加 `data`，注意 object 必须是追加类型文件，返回当前 object 中下一次追加的位置

- `read(self, key: str)`  
  接收参数为 object 的名称，该方法直接读取指定 object 中的内容，以字符串的形式返回

- `deleteobj(self, key: str)`  
  接收参数为 object 的名称，该方法用于将指定的 object 删除

- `clearobj(self, key: str)`   
  接收参数为 object 的名称，该方法可以在保持指定 object 为追加类型文件的基础上，将其清空

---

### (6) `AliSLS` 类

**成员属性：**

- `self.project: str` ：SLS 中存放日志的项目     
- `self.location: str` ：阿里云服务所在地域   
- `self.client:` ：访问阿里云 SLS 的客户端      

**方法说明：**  

- `create_sls_client(self)`  
  该函数创建并返回阿里云 SLS Client   

- `create_project(self)`  
  该函数创建 SLS 上面的存储项目    

- `create_index(self, logstore)`  
  接收参数为存储单元的名称 `logstore`，为存储单元创建索引    

- `create_logstore(self， logstore)`  
  接收参数为存储单元的名称 `logstore`，创建指定名称的存储单元  

- `getlogs(location, project, logstore)`  
  静态方法，接收参数为阿里云服务地域 `location`、日志项目名称 `project` 以及存储单元的名称 `logstore`，改方法用于查询日志内容     

## 3. 外部调用方式

### (1) FaaS 形式部署

一个 `AliFC` 实例严格对应一个具体的 FC 函数，外部代码不应直接实例化 `AliFC`，而是通过 `AliFunctionDeployer` 统一创建。一个完整的 FaaS 形式部署到阿里云的外部调用分为两步:  

1. 首先根据 benchmark 创建 `AliFunctionDeployer` 实例

```python
function_deployer = AliFunctionDeployer(bench_name)
```

2. 然后根据 node 的名字和目录调用 `AliFunctionDeployer` 的 `deploy_node` 方法，即可得到 URL

```python
url = function_deployer.deploy_node(node_name, node_dir)
```

---

### (2) MCP 形式部署

与 **FaaS 形式部署**类似，通过 `AliMCPDeployer` 统一创建 `AliFC` 实例。一个完整的 MCP 形式部署到阿里云的外部调用分为两步:  

1. 首先根据 benchmark 创建 `AliMCPDeployer` 实例

```python
mcp_deployer = AliMCPDeployer(bench_name)
```

2. 然后根据 node 的名字和目录调用 `AliMCPDeployer` 的 `deploy_node` 方法，即可得到 URL

```python
url = mcp_deployer.deploy_node(service_name, node_dir)
```

对于 OSS 平台的调用，在有状态工具逻辑代码中实例化并使用相应方法