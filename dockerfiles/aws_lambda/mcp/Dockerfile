ARG VERSION=3.11
ARG BASE_IMAGE=public.ecr.aws/lambda/python:${VERSION}

FROM ${BASE_IMAGE}

# 在 FROM 之后重新声明需要使用的 ARG
ARG VERSION=3.11
ARG ATSUITE_NODE_MODULE
ARG ATSUITE_MCP_NAME
ARG PROVIDER
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST
ARG ATSUITE_SYSTEM_PACKAGES=""
ENV PROVIDER=${PROVIDER}
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}
ENV PROJECT="atsuite"

# 安装 AWS Lambda Web Adapter
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 /lambda-adapter /opt/extensions/lambda-adapter

ENV PYTHON_VERSION=${VERSION}
ENV PATH=/app/.python_user/bin:/usr/sbin:$PATH
ENV PYTHONUSERBASE=/app/.python_user

RUN set -eux; \
    if [ -n "${ATSUITE_SYSTEM_PACKAGES}" ]; then \
        if command -v apt-get >/dev/null 2>&1; then \
            apt-get update; \
            apt-get install -y --no-install-recommends ${ATSUITE_SYSTEM_PACKAGES}; \
            rm -rf /var/lib/apt/lists/*; \
        elif command -v dnf >/dev/null 2>&1; then \
            dnf install -y ${ATSUITE_SYSTEM_PACKAGES}; \
            dnf clean all; \
        elif command -v microdnf >/dev/null 2>&1; then \
            microdnf install -y ${ATSUITE_SYSTEM_PACKAGES}; \
            microdnf clean all; \
        elif command -v yum >/dev/null 2>&1; then \
            yum install -y ${ATSUITE_SYSTEM_PACKAGES}; \
            yum clean all; \
        elif command -v apk >/dev/null 2>&1; then \
            apk add --no-cache ${ATSUITE_SYSTEM_PACKAGES}; \
        else \
            echo "No supported package manager found to install ATSuite system packages: ${ATSUITE_SYSTEM_PACKAGES}" >&2; \
            exit 1; \
        fi; \
    fi

WORKDIR /app
COPY . /app

# 依赖安装遵循 requirements.txt 中的索引源配置，避免先访问默认 PyPI。
RUN python3 -m pip install --user --prefer-binary -r /app/requirements.txt

ENV PYTHONPATH=/app:/app/.python_user/lib/python${PYTHON_VERSION}/site-packages
ENV ATSUITE_NODE_MODULE=${ATSUITE_NODE_MODULE}
ENV ATSUITE_MCP_NAME=${ATSUITE_MCP_NAME}
ENV ATSUITE_RUNTIME=mcp

# AWS Lambda Web Adapter 配置：适配器监听 8080 端口并转发到 MCP 服务器
ENV AWS_LWA_PORT=8080
ENV ATSUITE_MCP_PORT=8080
# Lambda 使用无状态 HTTP 模式，每次请求独立处理
ENV ATSUITE_MCP_STATELESS=true

EXPOSE 8080

# 覆盖 Lambda 基础镜像的 ENTRYPOINT，使用 Lambda Web Adapter 模式
ENTRYPOINT []
CMD ["python", "/app/atsuite_sdk/mcp_server.py"]
