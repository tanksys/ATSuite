ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG VERSION=3.9
ARG ENTRYPOINT
ARG ATSUITE_NODE_MODULE
ARG ATSUITE_MCP_NAME
ARG PROVIDER
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST
ARG ATSUITE_SYSTEM_PACKAGES=""

ENV PROVIDER=${PROVIDER}
ENV PYTHON_VERSION=${VERSION}
ENV PATH=/usr/sbin:$PATH
ENV PYTHONUSERBASE=/app/.python_user
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}
ENV PROJECT="atsuite11"

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

RUN python3 -m pip -q install --user -r /app/requirements.txt

ENV PYTHONPATH=/app:/app/.python_user/lib/python${PYTHON_VERSION}/site-packages
ENV ATSUITE_NODE_MODULE=${ATSUITE_NODE_MODULE}
ENV ATSUITE_MCP_NAME=${ATSUITE_MCP_NAME}
ENV ATSUITE_RUNTIME=mcp

EXPOSE 8000
ENTRYPOINT []
CMD ["python", "-m", "atsuite_sdk.mcp_server"]
