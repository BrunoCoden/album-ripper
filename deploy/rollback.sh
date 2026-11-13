#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 && $# == 1 ]] || { echo 'Como root: bash deploy/rollback.sh /var/backups/ytmusic-rip/FECHA'; exit 1; }
BACKUP=$(realpath -- "$1")
[[ "$BACKUP" == /var/backups/ytmusic-rip/* && -f "$BACKUP/server-check-telegram.py" ]] || exit 1
systemctl disable --now ytmusic-rip-worker.service
install -o root -g root -m 0755 "$BACKUP/server-check-telegram.py" /usr/local/sbin/server-check-telegram.py
if [[ -f "$BACKUP/music.conf" ]]; then
  cp -a "$BACKUP/music.conf" /etc/systemd/system/server-check-telegram.service.d/music.conf
else
  rm -f /etc/systemd/system/server-check-telegram.service.d/music.conf
fi
systemctl daemon-reload
systemctl restart server-check-telegram.service
systemctl is-active server-check-telegram.service
