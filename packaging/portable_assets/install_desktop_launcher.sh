#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_FILE="${SCRIPT_DIR}/DNGauge.desktop.template"
TARGET_DIR="${HOME}/.local/share/applications"
TARGET_FILE="${TARGET_DIR}/DNGauge.desktop"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"

if [[ -z "${DESKTOP_DIR}" || ! -d "${DESKTOP_DIR}" ]]; then
    DESKTOP_DIR="${HOME}/Desktop"
fi

mkdir -p "${TARGET_DIR}"

sed "s|__APPDIR__|${SCRIPT_DIR}|g" "${DESKTOP_FILE}" > "${TARGET_FILE}"
chmod +x "${TARGET_FILE}"

if [[ -d "${DESKTOP_DIR}" ]]; then
    cp "${TARGET_FILE}" "${DESKTOP_DIR}/DNGauge.desktop"
    chmod +x "${DESKTOP_DIR}/DNGauge.desktop"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${TARGET_DIR}"
fi

echo "Desktop launcher installed:"
echo "  ${TARGET_FILE}"
if [[ -d "${DESKTOP_DIR}" ]]; then
    echo "  ${DESKTOP_DIR}/DNGauge.desktop"
fi
