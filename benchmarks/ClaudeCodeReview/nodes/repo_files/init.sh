#!/bin/bash
set -euo pipefail

OUTPUT_DIR="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "${ATSUITE_DATA_PATH:-}" ] && [ -f "${ATSUITE_DATA_PATH}/repo_fixture.json" ]; then
  DATA_DIR="${ATSUITE_DATA_PATH}"
else
  DATA_DIR="$(cd "${SCRIPT_DIR}/../../data" && pwd)"
fi

mkdir -p "${OUTPUT_DIR}/data"
cp "${DATA_DIR}/repo_fixture.json" "${OUTPUT_DIR}/data/repo_fixture.json"
cp "${DATA_DIR}/pr_fixture.json" "${OUTPUT_DIR}/data/pr_fixture.json"
python3 "${DATA_DIR}/materialize_fixture_repo.py" \
  --data-dir "${DATA_DIR}" \
  --output-dir "${OUTPUT_DIR}/data"
