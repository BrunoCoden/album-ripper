#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Uso:
  ytmusic-rip.sh URL [CARPETA_DESTINO]

Ejemplos:
  ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...'
  ytmusic-rip.sh 'https://music.youtube.com/watch?v=...'
  YTMUSIC_MAX_ITEMS=3 ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...'

Variables opcionales:
  YTMUSIC_COOKIES_BROWSER=firefox
  YTMUSIC_EXTRA_ARGS='--write-info-json'
  YTMUSIC_MAX_ITEMS=10
  YTMUSIC_OUTPUT_DIR="$HOME/Downloads/YouTube Music"
  YTMUSIC_YT_DLP="$HOME/albumripper-venv/bin/yt-dlp"
USAGE
}

sanitize() {
  printf '%s' "$1" | tr '/:\\*?"<>|' '_' | tr -s ' '
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
COMMON_ARGS=()

build_common_args() {
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

  if [[ -n "${YTMUSIC_COOKIES_BROWSER:-}" ]]; then
    COMMON_ARGS+=(--cookies-from-browser "${YTMUSIC_COOKIES_BROWSER}")
  fi

  if [[ -n "${YTMUSIC_EXTRA_ARGS:-}" ]]; then
    # shellcheck disable=SC2206
    EXTRA_ARGS=( ${YTMUSIC_EXTRA_ARGS} )
    COMMON_ARGS+=("${EXTRA_ARGS[@]}")
  fi
}

download_single() {
  local url="$1"
  local output_template="$2"
  local auto_browser

  if [[ -n "${YTMUSIC_COOKIES_BROWSER:-}" ]]; then
    "${YT_DLP}" "${COMMON_ARGS[@]}" --output "${output_template}" "${url}"
    return 0
  fi

  if [[ -n "${AUTO_COOKIE_BROWSER}" ]]; then
    "${YT_DLP}" "${COMMON_ARGS[@]}" --cookies-from-browser "${AUTO_COOKIE_BROWSER}" --output "${output_template}" "${url}"
    return 0
  fi

  if "${YT_DLP}" "${COMMON_ARGS[@]}" --output "${output_template}" "${url}"; then
    return 0
  fi

  auto_browser="$(detect_cookie_browser || true)"
  if [[ -z "${auto_browser}" ]]; then
    return 1
  fi

  echo "Reintentando con cookies de ${auto_browser}..." >&2
  if "${YT_DLP}" "${COMMON_ARGS[@]}" --cookies-from-browser "${auto_browser}" --output "${output_template}" "${url}"; then
    AUTO_COOKIE_BROWSER="${auto_browser}"
    return 0
  fi

  return 1
}

download_playlist() {
  local url="$1"
  local dest="$2"
  local list_id
  local playlist_dir
  local max_items="${YTMUSIC_MAX_ITEMS:-}"
  local -a entry_urls=()
  local idx=0

  list_id="$(printf '%s' "${url}" | sed -n 's/.*[?&]list=\([^&]*\).*/\1/p')"
  if [[ -z "${list_id}" ]]; then
    list_id="playlist"
  fi

  playlist_dir="${dest}/$(sanitize "${list_id}")"
  mkdir -p "${playlist_dir}"

  while IFS= read -r entry_url; do
    [[ -n "${entry_url}" ]] || continue
    entry_urls+=("${entry_url}")
    if [[ -n "${max_items}" && ${#entry_urls[@]} -ge ${max_items} ]]; then
      break
    fi
  done < <("${YT_DLP}" --flat-playlist --print '%(url)s' "${url}")

  if [[ ${#entry_urls[@]} -eq 0 ]]; then
    echo "No pude extraer items de la playlist" >&2
    exit 1
  fi

  for entry_url in "${entry_urls[@]}"; do
    idx=$((idx + 1))
    printf 'Descargando %d/%d: %s\n' "${idx}" "${#entry_urls[@]}" "${entry_url}"
    download_single "${entry_url}" "${playlist_dir}/$(printf '%02d' "${idx}")_%(title)s.%(ext)s"
  done
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 ]]; then
  usage
  exit 0
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

URL="$1"
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

build_common_args

if [[ "${URL}" == *"playlist?list="* ]]; then
  download_playlist "${URL}" "${DEST}"
else
  download_single "${URL}" "${DEST}/%(uploader|channel|artist|Unknown Artist)s/%(title)s.%(ext)s"
fi
