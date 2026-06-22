#! /bin/bash

OUTPUT_DIR="${1:-.}"
ENV_PATH="${OUTPUT_DIR}/.env"
NPS_API_URL="https://www.nps.gov/subjects/developer/get-started.htm"

# 检查并创建 .env 文件（核心逻辑）
if [ ! -f "${ENV_PATH}" ]; then
  echo "Creating .env file for National Parks API..."
  echo "Please get your NPS API key from: ${NPS_API_URL}"
  read -p "Enter your NPS API key: " NPS_API_KEY
  
  if [ -z "${NPS_API_KEY}" ]; then
    echo "Error: NPS API key cannot be empty"
    exit 1
  fi

  # 写入 API Key 到 .env 文件
  echo "NPS_API_KEY=${NPS_API_KEY}" > "${ENV_PATH}"
  echo "Success: .env file created at ${ENV_PATH}"
else
  echo "Info: .env file already exists at ${ENV_PATH}, skipping creation"
fi