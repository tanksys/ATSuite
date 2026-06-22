#!/bin/bash
set -e

TARGET_DIR="${1:-$(pwd)}"
DATA_ROOT="${ATSUITE_DATA_PATH:-}"
BOOTSTRAP_DIR="${TARGET_DIR}/bootstrap"

mkdir -p "${BOOTSTRAP_DIR}"

for data_file in data_pums_2000.csv adult.data adult.test; do
  if [[ -n "${DATA_ROOT}" && -f "${DATA_ROOT}/${data_file}" ]]; then
    cp "${DATA_ROOT}/${data_file}" "${BOOTSTRAP_DIR}/${data_file}"
  fi
done

exit 0
