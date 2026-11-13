#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SANITIZER_SCRIPT="${SCRIPT_DIR}/tag_audio_from_filenames.py"

usage() {
  cat <<'USAGE'
Uso:
  ytmusic-rip.sh [--playlist-metadata-only] URL [CARPETA_DESTINO]
  ytmusic-rip.sh CARPETA_LOCAL

Ejemplos:
  ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...'
  ytmusic-rip.sh 'https://music.youtube.com/watch?v=...'
  ytmusic-rip.sh '$HOME/Downloads/YouTube Music/Mi Carpeta'
  ytmusic-rip.sh --playlist-metadata-only 'https://music.youtube.com/playlist?list=...'
  YTMUSIC_MAX_ITEMS=3 ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...'

Variables opcionales:
  YTMUSIC_COOKIES_BROWSER=firefox
  YTMUSIC_COOKIES_FILE="$HOME/Downloads/youtube-cookies.txt"
  YTMUSIC_EXTRA_ARGS='--write-info-json'
  YTMUSIC_MAX_ITEMS=10
  YTMUSIC_OUTPUT_DIR="$HOME/Downloads/YouTube Music"
  YTMUSIC_YT_DLP="$HOME/albumripper-venv/bin/yt-dlp"
  YTMUSIC_RUN_SANITIZER=1
  YTMUSIC_SANITIZER_PYTHON="$HOME/albumripper-venv/bin/python"
  YTMUSIC_SANITIZER_ARGS='--youtube-assist --rename'
  YTMUSIC_EXPORT_M3U=1
  YTMUSIC_RETRY_COUNT=3
  YTMUSIC_RETRY_SLEEP=8
  YTMUSIC_ITEM_DELAY=3
  YTMUSIC_PLAYLIST_METADATA_ONLY=1
USAGE
}

sanitize() {
  printf '%s' "$1" | sed "s/['’]\+//g" | tr '/:\\*?"<>|' '_' | tr -s ' ' | sed 's/^ *//; s/ *$//'
}

resolve_yt_dlp() {
  if [[ -n "${YTMUSIC_YT_DLP:-}" ]]; then
    printf '%s\n' "${YTMUSIC_YT_DLP}"
    return 0
  fi

  if command -v yt-dlp >/dev/null 2>&1; then
    command -v yt-dlp
    return 0
  fi

  if [[ -x "${HOME}/albumripper-venv/bin/yt-dlp" ]]; then
    printf '%s\n' "${HOME}/albumripper-venv/bin/yt-dlp"
    return 0
  fi

  return 1
}

resolve_sanitizer_python() {
  if [[ -n "${YTMUSIC_SANITIZER_PYTHON:-}" ]]; then
    printf '%s\n' "${YTMUSIC_SANITIZER_PYTHON}"
    return 0
  fi

  if [[ -x "${HOME}/albumripper-venv/bin/python" ]]; then
    printf '%s\n' "${HOME}/albumripper-venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  return 1
}

detect_cookie_browser() {
  if command -v firefox >/dev/null 2>&1; then
    echo firefox
    return 0
  fi

  if command -v google-chrome >/dev/null 2>&1; then
    echo chrome
    return 0
  fi

  if command -v chromium-browser >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
    echo chromium
    return 0
  fi

  return 1
}

resolve_cookies_file() {
  if [[ -n "${YTMUSIC_COOKIES_FILE:-}" && -f "${YTMUSIC_COOKIES_FILE}" ]]; then
    printf '%s\n' "${YTMUSIC_COOKIES_FILE}"
    return 0
  fi

  return 1
}

append_cookie_args() {
  local browser_name="$1"
  local cookies_file="$2"
  shift 2

  if [[ -n "${cookies_file}" ]]; then
    printf '%s\0' --cookies "${cookies_file}"
    return 0
  fi

  if [[ -n "${browser_name}" ]]; then
    printf '%s\0' --cookies-from-browser "${browser_name}"
    return 0
  fi

  return 0
}

resolve_default_dest() {
  if [[ -n "${YTMUSIC_OUTPUT_DIR:-}" ]]; then
    printf '%s\n' "${YTMUSIC_OUTPUT_DIR}"
    return 0
  fi

  if [[ -d "${HOME}/Music" ]]; then
    printf '%s\n' "${HOME}/Music/YouTube Music"
  else
    printf '%s\n' "${HOME}/Downloads/YouTube Music"
  fi
}

AUTO_COOKIE_BROWSER=""
AUTO_COOKIES_FILE=""
COMMON_ARGS=()
RETRY_COUNT="${YTMUSIC_RETRY_COUNT:-3}"
RETRY_SLEEP="${YTMUSIC_RETRY_SLEEP:-8}"
ITEM_DELAY="${YTMUSIC_ITEM_DELAY:-3}"

build_common_args() {
  AUTO_COOKIES_FILE="$(resolve_cookies_file || true)"
  if [[ -n "${AUTO_COOKIES_FILE}" ]]; then
    printf '[auth] Usando archivo de cookies desde el arranque: %s\n' "${AUTO_COOKIES_FILE}"
  elif [[ -z "${YTMUSIC_COOKIES_BROWSER:-}" && -z "${AUTO_COOKIE_BROWSER}" ]]; then
    AUTO_COOKIE_BROWSER="$(detect_cookie_browser || true)"
    if [[ -n "${AUTO_COOKIE_BROWSER}" ]]; then
      printf '[auth] Usando cookies de %s desde el arranque\n' "${AUTO_COOKIE_BROWSER}"

    fi
  fi

  COMMON_ARGS=(
    --extract-audio
    --audio-format mp3
    --audio-quality 0
    --no-keep-video
    --embed-thumbnail
    --add-metadata
    --convert-thumbnails jpg
    --newline
    --restrict-filenames
  )

  if [[ -n "${YTMUSIC_COOKIES_FILE:-}" && -f "${YTMUSIC_COOKIES_FILE}" ]]; then
    COMMON_ARGS+=(--cookies "${YTMUSIC_COOKIES_FILE}")
  elif [[ -n "${YTMUSIC_COOKIES_BROWSER:-}" ]]; then
    COMMON_ARGS+=(--cookies-from-browser "${YTMUSIC_COOKIES_BROWSER}")
  fi

  if [[ -n "${YTMUSIC_EXTRA_ARGS:-}" ]]; then
    # shellcheck disable=SC2206
    EXTRA_ARGS=( ${YTMUSIC_EXTRA_ARGS} )
    COMMON_ARGS+=("${EXTRA_ARGS[@]}")
  fi
}

run_sanitizer() {
  local target_dir="$1"
  local sanitizer_python
  local -a sanitizer_args=()

  if [[ "${YTMUSIC_RUN_SANITIZER:-1}" == "0" ]]; then
    return 0
  fi

  if [[ ! -f "${SANITIZER_SCRIPT}" ]]; then
    echo "[sanitize-warning] No encuentro ${SANITIZER_SCRIPT}" >&2
    return 1
  fi

  sanitizer_python="$(resolve_sanitizer_python || true)"
  if [[ -z "${sanitizer_python}" || ! -x "${sanitizer_python}" ]]; then
    echo "[sanitize-warning] No encuentro un intérprete Python para ejecutar el saneador" >&2
    return 1
  fi

  if [[ -n "${YTMUSIC_SANITIZER_ARGS:-}" ]]; then
    # shellcheck disable=SC2206
    sanitizer_args=( ${YTMUSIC_SANITIZER_ARGS} )
  else
    sanitizer_args=(--youtube-assist --rename)
  fi

  printf '[sanitize] Ejecutando saneador en: %s\n' "${target_dir}"
  "${sanitizer_python}" "${SANITIZER_SCRIPT}" "${sanitizer_args[@]}" "${target_dir}"
  printf '[sanitize] Saneador terminado: %s\n' "${target_dir}"
}

download_single() {
  local url="$1"
  local output_template="$2"
  local attempt=1
  local active_browser="${YTMUSIC_COOKIES_BROWSER:-${AUTO_COOKIE_BROWSER}}"
  local active_cookies_file="${YTMUSIC_COOKIES_FILE:-${AUTO_COOKIES_FILE}}"
  local exit_code=1

  while (( attempt <= RETRY_COUNT )); do
    if (( attempt > 1 )); then
      printf '[retry] Intento %d/%d para %s\n' "${attempt}" "${RETRY_COUNT}" "${url}" >&2
      sleep "${RETRY_SLEEP}"
    fi

    if [[ -n "${active_cookies_file}" ]]; then
      if "${YT_DLP}" "${COMMON_ARGS[@]}" --cookies "${active_cookies_file}" --sleep-requests 2 --sleep-interval 2 --max-sleep-interval 6 --output "${output_template}" "${url}"; then
        AUTO_COOKIES_FILE="${active_cookies_file}"
        return 0
      else
        exit_code=$?
      fi
    elif [[ -n "${active_browser}" ]]; then
      if "${YT_DLP}" "${COMMON_ARGS[@]}" --cookies-from-browser "${active_browser}" --sleep-requests 2 --sleep-interval 2 --max-sleep-interval 6 --output "${output_template}" "${url}"; then
        AUTO_COOKIE_BROWSER="${active_browser}"
        return 0
      else
        exit_code=$?
      fi
    else
      if "${YT_DLP}" "${COMMON_ARGS[@]}" --sleep-requests 2 --sleep-interval 2 --max-sleep-interval 6 --output "${output_template}" "${url}"; then
        return 0
      else
        exit_code=$?
      fi
      active_cookies_file="$(resolve_cookies_file || true)"
      if [[ -n "${active_cookies_file}" ]]; then
        echo "Reintentando con archivo de cookies ${active_cookies_file}..." >&2
      else
        active_browser="$(detect_cookie_browser || true)"
        if [[ -n "${active_browser}" ]]; then
          echo "Reintentando con cookies de ${active_browser}..." >&2
        fi
      fi
    fi

    attempt=$((attempt + 1))
  done

  return "${exit_code}"
}

PLAYLIST_METADATA_ONLY="${YTMUSIC_PLAYLIST_METADATA_ONLY:-0}"
if [[ "${1:-}" == "--playlist-metadata-only" ]]; then
  PLAYLIST_METADATA_ONLY=1
  shift
fi

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 ]]; then
  usage
  exit 0
fi

INPUT="$1"
if [[ -d "${INPUT}" ]]; then
  run_sanitizer "${INPUT}"
  exit $?
fi

YT_DLP="$(resolve_yt_dlp || true)"
if [[ -z "${YT_DLP}" || ! -x "${YT_DLP}" ]]; then
  echo "No encuentro yt-dlp. Definí YTMUSIC_YT_DLP o instalalo en PATH." >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg no está instalado o no está en PATH" >&2
  exit 1
fi

URL="${INPUT}"
if [[ $# -ge 2 ]]; then
  DEST="$2"
else
  DEST="$(resolve_default_dest)"
fi

mkdir -p "${DEST}"

if [[ ! -w "${DEST}" ]]; then
  echo "La carpeta destino no es escribible: ${DEST}" >&2
  exit 1
fi

if [[ "${URL}" == *"list="* ]]; then
  playlist_args=()
  [[ "${PLAYLIST_METADATA_ONLY}" == "1" ]] && playlist_args+=(--metadata-only)
  exec "$(resolve_sanitizer_python)" "${SCRIPT_DIR}/ytmusic_playlist.py" "${URL}" "${DEST}" "${playlist_args[@]}"
else
  # Share the playlist writer lock for direct track downloads, too.
  exec {library_lock_fd}>"${DEST}/.ytmusic-rip.lock"
  flock -n "${library_lock_fd}" || { echo 'La biblioteca está ocupada.' >&2; exit 1; }
  build_common_args
  download_single "${URL}" "${DEST}/%(uploader|channel|artist|Unknown Artist)s/%(title)s__%(id)s.%(ext)s"
fi
