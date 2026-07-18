#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${HOME}/.local/share/applications"
TARGET_FILE="${TARGET_DIR}/ytmusic-rip-ui.desktop"

mkdir -p "${TARGET_DIR}"

cat >"${TARGET_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=ytmusic-rip
Comment=Ripear playlists o tracks de YouTube Music
Exec=${SCRIPT_DIR}/ytmusic-rip-ui.sh
Icon=multimedia-audio-player
Terminal=false
Categories=AudioVideo;Audio;
Path=${SCRIPT_DIR}
StartupNotify=true
EOF

chmod +x "${TARGET_FILE}"

printf 'Instalado: %s\n' "${TARGET_FILE}"
