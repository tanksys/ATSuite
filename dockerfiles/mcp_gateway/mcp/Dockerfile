ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG VERSION=3.11
ARG ATSUITE_NODE_MODULE
ARG ATSUITE_MCP_NAME
ARG PROVIDER
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST

ENV PROVIDER=${PROVIDER}
ENV PYTHON_VERSION=${VERSION}
ENV PYTHONUSERBASE=/app/.python_user
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}
ENV PROJECT=atsuite

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends git ca-certificates; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN python3 -m pip -q install --user -r /app/requirements.txt

ENV PYTHONPATH=/app:/app/.python_user/lib/python${PYTHON_VERSION}/site-packages
ENV ATSUITE_NODE_MODULE=${ATSUITE_NODE_MODULE}
ENV ATSUITE_MCP_NAME=${ATSUITE_MCP_NAME}
ENV ATSUITE_RUNTIME=mcp
ENV ATSUITE_MCP_PORT=8000
ENV ATSUITE_MCP_PATH=/mcp
ENV ATSUITE_MCP_TRANSPORT=http

EXPOSE 8000
ENTRYPOINT []
CMD ["python", "-m", "atsuite_sdk.mcp_server"]
