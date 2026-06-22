ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG VERSION=3.9
ARG ENTRYPOINT
ARG ATSUITE_NODE_MODULE
ARG ATSUITE_MCP_NAME
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST

ENV PYTHON_VERSION=${VERSION}
ENV PATH=/usr/sbin:$PATH
ENV PYTHONUSERBASE=/app/.python_user
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

# repo_git_* tools shell out to git inside the runtime container.
RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        apt-get install -y --no-install-recommends git ca-certificates; \
        rm -rf /var/lib/apt/lists/*; \
    elif command -v dnf >/dev/null 2>&1; then \
        dnf install -y git ca-certificates; \
        dnf clean all; \
    elif command -v microdnf >/dev/null 2>&1; then \
        microdnf install -y git ca-certificates; \
        microdnf clean all; \
    elif command -v yum >/dev/null 2>&1; then \
        yum install -y git ca-certificates; \
        yum clean all; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache git ca-certificates; \
    else \
        echo "No supported package manager found to install git" >&2; \
        exit 1; \
    fi

WORKDIR /app
COPY . /app

RUN python -m pip -q install --user -r /app/requirements.txt

ENV PYTHONPATH=/app:/app/.python_user/lib/python${PYTHON_VERSION}/site-packages
ENV ATSUITE_NODE_MODULE=${ATSUITE_NODE_MODULE}
ENV ATSUITE_MCP_NAME=${ATSUITE_MCP_NAME}

EXPOSE 8080
ENTRYPOINT []
CMD ["python", "-m", "atsuite_sdk.function"]
