#!/bin/bash

# 对齐 google_maps/init.sh 风格，仅配置 WeatherAPI 核心环境变量
OUTPUT_DIR="${1:-.}"
ENV_PATH="${OUTPUT_DIR}/.env"
WEATHER_API_URL="https://www.weatherapi.com/"

if [ ! -f "${ENV_PATH}" ]; then
  echo "Creating .env file for WeatherAPI..."
  echo "Please get your WeatherAPI key from: ${WEATHER_API_URL}"
  read -p "Enter your WEATHER_API_KEY: " WEATHER_API_KEY
  
  if [ -z "${WEATHER_API_KEY}" ]; then
    echo "Error: WEATHER_API_KEY cannot be empty"
    exit 1
  fi

  # 写入核心环境变量（对齐 .env.example 规范）
  echo "WEATHER_API_KEY=${WEATHER_API_KEY}" > "${ENV_PATH}"
  echo "API_TIMEOUT=10" >> "${ENV_PATH}"
  echo "API_LANGUAGE=tr" >> "${ENV_PATH}"
  echo "Success: .env file created at ${ENV_PATH}"
else
  echo "Info: .env file already exists at ${ENV_PATH}, skipping creation"
fi