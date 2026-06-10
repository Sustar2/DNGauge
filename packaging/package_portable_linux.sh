#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RELEASE_ROOT="${PROJECT_ROOT}/release"
APP_DIR="${RELEASE_ROOT}/DNGauge-linux-portable"
ARCHIVE_PATH="${RELEASE_ROOT}/DNGauge-linux-portable.tar.gz"

mkdir -p "${RELEASE_ROOT}"
rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}"

cp "${PROJECT_ROOT}/dist/DNGauge" "${APP_DIR}/DNGauge"
cp "${SCRIPT_DIR}/DNGauge.png" "${APP_DIR}/DNGauge.png"
cp "${SCRIPT_DIR}/portable_assets/install_desktop_launcher.sh" "${APP_DIR}/install_desktop_launcher.sh"
cp "${SCRIPT_DIR}/portable_assets/DNGauge.desktop.template" "${APP_DIR}/DNGauge.desktop.template"
cp "${SCRIPT_DIR}/portable_assets/README_RUN.txt" "${APP_DIR}/README_RUN.txt"
cp "${SCRIPT_DIR}/portable_assets/README_RUN_EN.txt" "${APP_DIR}/README_RUN_EN.txt"
cp "${SCRIPT_DIR}/portable_assets/README_RUN_CN.txt" "${APP_DIR}/README_RUN_CN.txt"

sed "s|__APPDIR__|${APP_DIR}|g" "${APP_DIR}/DNGauge.desktop.template" > "${APP_DIR}/DNGauge.desktop"

chmod +x "${APP_DIR}/DNGauge" "${APP_DIR}/install_desktop_launcher.sh" "${APP_DIR}/DNGauge.desktop"

rm -f "${ARCHIVE_PATH}"
tar -czf "${ARCHIVE_PATH}" -C "${RELEASE_ROOT}" "DNGauge-linux-portable"

echo
echo "Portable folder created:"
echo "  ${APP_DIR}"
echo
echo "Portable archive created:"
echo "  ${ARCHIVE_PATH}"
