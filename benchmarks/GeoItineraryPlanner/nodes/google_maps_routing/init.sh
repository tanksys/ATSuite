#! /bin/bash

OUTPUT_DIR="${1:-.}"
ENV_PATH="${OUTPUT_DIR}/.env"
GOOGLE_MAPS_API_URL="https://console.cloud.google.com/google/maps-apis"

if [ ! -f "${ENV_PATH}" ]; then
  echo "Creating .env file for Google Maps API..."
  echo "Please get your Google Maps API key from: ${GOOGLE_MAPS_API_URL}"
  read -p "Enter your GOOGLE_MAPS_API_KEY: " GOOGLE_MAPS_API_KEY

  if [ -z "${GOOGLE_MAPS_API_KEY}" ]; then
    echo "Error: GOOGLE_MAPS_API_KEY cannot be empty"
    exit 1
  fi

  echo "GOOGLE_MAPS_API_KEY=${GOOGLE_MAPS_API_KEY}" > "${ENV_PATH}"
  echo "Success: .env file created at ${ENV_PATH}"
else
  echo "Info: .env file already exists at ${ENV_PATH}, skipping creation"
fi
