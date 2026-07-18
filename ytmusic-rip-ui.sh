#!/usr/bin/env bash

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RIP_SCRIPT="${APP_DIR}/ytmusic-rip.sh"
DEFAULT_OUTPUT_DIR="${YTMUSIC_OUTPUT_DIR:-$HOME/Downloads/YouTube Music}"

if ! command -v zenity >/dev/null 2>&1; then
  echo "zenity no está instalado" >&2
  exit 1
fi

if [[ ! -x "${RIP_SCRIPT}" ]]; then
  zenity --error \
    --title="ytmusic-rip" \
    --text="No encuentro el script principal:\n${RIP_SCRIPT}"
  exit 1
fi

url="$(zenity --entry \
  --title='ytmusic-rip' \
  --width=560 \
  --text='Pegá el link de YouTube Music y hacé clic en Ripear.' \
  --entry-text='https://music.youtube.com/playlist?list=' \
  --ok-label='Ripear' \
  --cancel-label='Cancelar')" || exit 0

url="${url#${url%%[![:space:]]*}}"
url="${url%${url##*[![:space:]]}}"

if [[ -z "${url}" ]]; then
  zenity --error --title='ytmusic-rip' --text='No ingresaste ninguna URL.'
  exit 1
fi

if [[ "${url}" != http://* && "${url}" != https://* ]]; then
  zenity --error --title='ytmusic-rip' --text='La URL debe empezar con http:// o https://'
  exit 1
fi

log_file="$(mktemp /tmp/ytmusic-rip-ui.XXXXXX.log)"

cleanup() {
  rm -f "${log_file}"
}
trap cleanup EXIT

"${RIP_SCRIPT}" "${url}" >"${log_file}" 2>&1 &
rip_pid=$!

monitor_progress() {
  local log="$1"
  local pid="$2"
  local current=1
  local total=1
  local item_percent=0
  local combined=0
  local status_text='Preparando ripeo...'
  local last_line=''

  while kill -0 "${pid}" 2>/dev/null; do
    progress_line="$(grep -E 'Descargando [0-9]+/[0-9]+:' "${log}" | tail -n 1 || true)"
    if [[ -n "${progress_line}" && ${progress_line} =~ Descargando[[:space:]]+([0-9]+)/([0-9]+): ]]; then
      current="${BASH_REMATCH[1]}"
      total="${BASH_REMATCH[2]}"
      status_text="${progress_line}"
    fi

    download_line="$(grep -E '^\[download\][[:space:]]+[0-9]+(\.[0-9]+)?%' "${log}" | tail -n 1 || true)"
    if [[ -n "${download_line}" && ${download_line} =~ \[download\][[:space:]]+([0-9]+)(\.[0-9]+)?% ]]; then
      item_percent="${BASH_REMATCH[1]}"
    fi

    last_line="$(tail -n 1 "${log}" 2>/dev/null || true)"
    case "${last_line}" in
      *'Extracting URL:'*)
        status_text='Analizando URL...'
        item_percent=2
        ;;
      *'Downloading webpage'*)
        status_text='Consultando YouTube Music...'
        item_percent=5
        ;;
      *'Downloading android vr player API JSON'*)
        status_text='Preparando descarga...'
        item_percent=8
        ;;
      *'[info]'*'Downloading 1 format(s):'*)
        status_text='Resolviendo formato de audio...'
        item_percent=12
        ;;
      *'[info] Downloading video thumbnail'*)
        status_text='Bajando portada...'
        item_percent=18
        ;;
      *'[download] Destination:'*)
        status_text='Descargando audio...'
        item_percent=20
        ;;
      *'[ExtractAudio] Destination:'*)
        status_text='Convirtiendo a mp3...'
        item_percent=85
        ;;
      *'[Metadata] Adding metadata'*)
        status_text='Escribiendo metadata...'
        item_percent=92
        ;;
      *'[EmbedThumbnail]'*)
        status_text='Incrustando portada...'
        item_percent=97
        ;;
      *'Reintentando con cookies de '*)
        status_text='Reintentando con cookies del navegador...'
        item_percent=15
        ;;
      *)
        ;;
    esac

    if [[ "${total}" -gt 1 ]]; then
      combined=$(( (((current - 1) * 100) + item_percent) / total ))
      if [[ ${combined} -lt 1 ]]; then
        combined=1
      fi
      printf '# %s\n' "${status_text}"
      printf '%s\n' "${combined}"
    else
      if [[ ${item_percent} -lt 1 ]]; then
        item_percent=1
      fi
      printf '# %s\n' "${status_text}"
      printf '%s\n' "${item_percent}"
    fi

    sleep 1
  done

  wait "${pid}"
  final_status=$?
  if [[ ${final_status} -eq 0 ]]; then
    printf '# Ripeo terminado.\n'
    printf '100\n'
  else
    printf '# El ripeo terminó con error.\n'
    printf '100\n'
  fi

  return 0
}

monitor_progress "${log_file}" "${rip_pid}" | zenity --progress \
  --title='ytmusic-rip' \
  --width=560 \
  --text='Preparando ripeo...' \
  --percentage=0 \
  --auto-close \
  --no-cancel

wait "${rip_pid}"
status=$?

if [[ ${status} -eq 0 ]]; then
  zenity --question \
    --title='ytmusic-rip' \
    --width=520 \
    --ok-label='Ver log' \
    --cancel-label='Cerrar' \
    --text='Ripeo terminado correctamente.' \
    --extra-button='Abrir carpeta destino'
  response=$?

  case ${response} in
    0)
      zenity --text-info --title='Log de ytmusic-rip' --filename="${log_file}" --width=900 --height=600
      ;;
    1)
      ;;
    *)
      xdg-open "${DEFAULT_OUTPUT_DIR}" >/dev/null 2>&1 || true
      ;;
  esac
else
  zenity --error \
    --title='ytmusic-rip' \
    --width=520 \
    --text='El ripeo falló. Se mostrará el log para revisar el error.'
  zenity --text-info --title='Error de ytmusic-rip' --filename="${log_file}" --width=900 --height=600
  exit "${status}"
fi
