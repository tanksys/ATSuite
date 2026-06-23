# Google Cloud 运行时介绍

ATSuite 的 GCP 支持主要围绕容器化部署到 Cloud Run，并配合 Artifact Registry、Cloud Storage、Cloud Logging 和 Cloud Monitoring。

## 计算服务

Cloud Run 是当前 function 风格工具和 MCP 服务的主要部署目标。ATSuite 会构建容器镜像、推送到配置的镜像仓库、通过 `gcloud run deploy` 部署服务，并记录服务 URL。

## 存储和日志

- Cloud Storage 可用于保存有状态工具数据和 benchmark 相关文件。
- Cloud Logging 和 Cloud Monitoring 可用于收集 provider 侧日志与指标证据。

## 常用服务

- Artifact Registry 或 GCR：容器镜像仓库。
- Cloud Run：部署运行服务。
- Cloud Storage：对象存储。
- Cloud Logging：云端日志。
