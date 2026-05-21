#!/usr/bin/env bash
set -euo pipefail

# DNG_COMPARE 启动脚本（固定使用 conda 环境 dng_compare）
# 用法:
#   ./run.sh
#   ./run.sh left.dng right.dng

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONDA_BASE="/home/wenjingxun/app/miniconda3"
CONDA_ENV="dng_compare"
ENV_LIB="${CONDA_BASE}/envs/${CONDA_ENV}/lib"

source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"

# 解决 Qt xcb 插件依赖问题
export LD_LIBRARY_PATH="${ENV_LIB}:${LD_LIBRARY_PATH:-}"

cd "${SCRIPT_DIR}"
exec python shotwell_compare.py "$@"
