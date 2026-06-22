# Dockerfile - AgentCore MCP 服务器容器镜像
#    平台必须为 linux/arm64（AgentCore 运行环境为 ARM64）
#    final ARM64 stage avoids RUN instructions so x86 hosts do not need QEMU.
ARG VERSION=3.11

FROM --platform=linux/amd64 public.ecr.aws/docker/library/python:${VERSION}-slim AS installer

ARG VERSION=3.11
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

WORKDIR /build
COPY requirements.txt .

# 跨平台下载所有包的 wheel（binary 包取 aarch64，纯 Python 包取 none-any），并直接安装到 /pkg
RUN pip install -q \
    --platform manylinux2014_aarch64 \
    --platform manylinux_2_17_aarch64 \
    --platform linux_aarch64 \
    --platform any \
    --python-version $(python3 -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')") \
    --only-binary=:all: \
    --target /pkg \
    -r requirements.txt

FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:${VERSION}-slim

ARG VERSION=3.11
ARG ATSUITE_NODE_MODULE
ARG ATSUITE_MCP_NAME
ARG PROVIDER
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST
ENV PROVIDER=${PROVIDER}
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}
ENV PROJECT="atsuite"

ENV PYTHON_VERSION=${VERSION}

# Keep the final ARM64 stage free of RUN instructions so hosts without stable
# ARM64 binfmt/QEMU can still cross-build AgentCore images. Python dependencies
# are prepared in the amd64 installer stage and copied below. Benchmarks that
# require OS packages such as git should use an AgentCore base image that already
# contains them, or enable a separate native ARM64/system-package build path.

WORKDIR /app
COPY . /app

COPY --from=installer /pkg /app/deps

ENV PYTHONPATH=/app/deps:/app
ENV ATSUITE_NODE_MODULE=${ATSUITE_NODE_MODULE}
ENV ATSUITE_MCP_NAME=${ATSUITE_MCP_NAME}

ENV ATSUITE_RUNTIME=mcp
ENV ATSUITE_MCP_PORT=8000
ENV ATSUITE_MCP_PATH=/mcp/
ENV ATSUITE_MCP_TRANSPORT=http
ENV ATSUITE_MCP_STATELESS=true

EXPOSE 8000

CMD ["python", "/app/atsuite_sdk/mcp_server.py"]
