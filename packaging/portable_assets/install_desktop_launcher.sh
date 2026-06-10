#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_FILE="${SCRIPT_DIR}/DNGauge.desktop.template"
TARGET_DIR="${HOME}/.local/share/applications"
TARGET_FILE="${TARGET_DIR}/DNGauge.desktop"

mkdir -p "${TARGET_DIR}"

sed "s|__APPDIR__|${SCRIPT_DIR}|g" "${DESKTOP_FILE}" > "${TARGET_FILE}"
chmod +x "${TARGET_FILE}"

if [[ -d "${HOME}/Desktop" ]]; then
    cp "${TARGET_FILE}" "${HOME}/Desktop/DNGauge.desktop"
    chmod +x "${HOME}/Desktop/DNGauge.desktop"
fi

echo "Desktop launcher installed:"
echo "  ${TARGET_FILE}"
if [[ -d "${HOME}/Desktop" ]]; then
    echo "  ${HOME}/Desktop/DNGauge.desktop"
fi
