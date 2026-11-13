#!/usr/bin/env bash
# Sourced by install.sh; arguments also allow isolated rollback tests.
activate_services() {
  local original="$1" dropin="$2" backup="$3"
  if systemctl daemon-reload &&
     systemctl enable --now ytmusic-rip-worker.service &&
     systemctl restart server-check-telegram.service; then
    sleep 3
    if systemctl is-active --quiet server-check-telegram.service &&
       systemctl is-active --quiet ytmusic-rip-worker.service; then
      return 0
    fi
  fi
  echo 'Falló la activación; restaurando el receptor anterior.' >&2
  systemctl disable --now ytmusic-rip-worker.service || true
  cp -a "$backup/server-check-telegram.py" "$original.restore" || return 1
  mv -f "$original.restore" "$original" || return 1
  if [[ -f "$backup/music.conf" ]]; then
    cp -a "$backup/music.conf" "$dropin" || return 1
  else
    rm -f "$dropin" || return 1
  fi
  if ! { systemctl daemon-reload && systemctl restart server-check-telegram.service; }; then
    echo 'No se pudo reiniciar el receptor restaurado; revisá systemctl status server-check-telegram.' >&2
  fi
  printf 'Respaldo: %s\n' "$backup" >&2
  return 1
}
