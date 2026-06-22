#!/bin/bash

OUTPUT_DIR="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Try ATSUITE_DATA_PATH first (set by build script), then relative to OUTPUT_DIR, then fallback to benchmark root
if [ -n "${ATSUITE_DATA_PATH}" ] && [ -f "${ATSUITE_DATA_PATH}/accommodations/clean_accommodations_2022.csv" ]; then
    DATA_DIR="${ATSUITE_DATA_PATH}"
elif [ -d "${OUTPUT_DIR}/../data" ]; then
    DATA_DIR="$(cd "${OUTPUT_DIR}/../data" && pwd)"
else
    BENCHMARK_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
    DATA_DIR="${BENCHMARK_ROOT}/data"
fi

SRC_PATH="${DATA_DIR}/accommodations/clean_accommodations_2022.csv"
DST_PATH="${OUTPUT_DIR}/accommodations.csv"

if [ ! -f "${SRC_PATH}" ]; then
    echo "Dataset not found at ${SRC_PATH}"
    exit 1
fi

cp "${SRC_PATH}" "${DST_PATH}"
