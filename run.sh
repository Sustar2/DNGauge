#!/usr/bin/env bash
set -euo pipefail

# DNG Compare 启动脚本（通用版）
# 用法:
#   ./run.sh
#   ./run.sh left.dng right.dng

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

# 优先使用当前环境中的 python，其次 python3
if command -v python >/dev/null 2>&1; then
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "[ERROR] 未找到 Python 解释器（python/python3）"
  exit 1
fi

exec "${PY}" shotwell_compare.py "$@"
