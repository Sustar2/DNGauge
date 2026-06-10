#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${PYTHON_BIN:-}" ]]; then
    PYTHON_CMD="${PYTHON_BIN}"
elif [[ -x "/home/wenjingxun/app/miniconda3/envs/dng_compare/bin/python" ]]; then
    PYTHON_CMD="/home/wenjingxun/app/miniconda3/envs/dng_compare/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="$(command -v python3)"
else
    PYTHON_CMD="$(command -v python)"
fi

cd "${PROJECT_ROOT}"

rm -rf "${PROJECT_ROOT}/build" "${PROJECT_ROOT}/dist"

"${PYTHON_CMD}" -m PyInstaller \
    --noconfirm \
    --distpath "${PROJECT_ROOT}/dist" \
    --workpath "${PROJECT_ROOT}/build" \
    "${SCRIPT_DIR}/DNGauge.spec"

echo
echo "Linux executable created:"
echo "  ${PROJECT_ROOT}/dist/DNGauge"
