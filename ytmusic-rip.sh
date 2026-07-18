#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SANITIZER_SCRIPT="${SCRIPT_DIR}/tag_audio_from_filenames.py"

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
  YTMUSIC_RUN_SANITIZER=1
  YTMUSIC_SANITIZER_PYTHON="$HOME/albumripper-venv/bin/python"
  YTMUSIC_SANITIZER_ARGS='--youtube-assist --rename'
  YTMUSIC_EXPORT_M3U=1
  YTMUSIC_RETRY_COUNT=3
  YTMUSIC_RETRY_SLEEP=8
  YTMUSIC_ITEM_DELAY=3
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
RETRY_COUNT="${YTMUSIC_RETRY_COUNT:-3}"
RETRY_SLEEP="${YTMUSIC_RETRY_SLEEP:-8}"
ITEM_DELAY="${YTMUSIC_ITEM_DELAY:-3}"

build_common_args() {
  if [[ -z "${YTMUSIC_COOKIES_BROWSER:-}" && -z "${AUTO_COOKIE_BROWSER}" ]]; then
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

  if [[ -n "${YTMUSIC_COOKIES_BROWSER:-}" ]]; then
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

export_playlist_m3u() {
  local playlist_dir="$1"
  local playlist_name="$2"
  local playlist_file="${playlist_dir}/${playlist_name}.m3u"
  local wrote=0

  if [[ "${YTMUSIC_EXPORT_M3U:-1}" == "0" ]]; then
    return 0
  fi

  printf '[playlist] Generando M3U: %s\n' "${playlist_file}"
  : > "${playlist_file}"

  while IFS= read -r relative_path; do
    [[ -n "${relative_path}" ]] || continue
    printf '%s\n' "${relative_path}" >> "${playlist_file}"
    wrote=1
  done < <(
    find "${playlist_dir}" -maxdepth 1 -type f \
      \( -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.mp4' -o -iname '*.flac' -o -iname '*.ogg' -o -iname '*.opus' \) \
      -printf '%f\n' | sort
  )

  if [[ ${wrote} -eq 0 ]]; then
    rm -f "${playlist_file}"
    echo '[playlist-warning] No encontré archivos de audio para generar el M3U' >&2
    return 1
  fi

  printf '[playlist] M3U generado: %s\n' "${playlist_file}"
}

download_single() {
  local url="$1"
  local output_template="$2"
  local attempt=1
  local active_browser="${YTMUSIC_COOKIES_BROWSER:-${AUTO_COOKIE_BROWSER}}"
  local exit_code=1

  while (( attempt <= RETRY_COUNT )); do
    if (( attempt > 1 )); then
      printf '[retry] Intento %d/%d para %s\n' "${attempt}" "${RETRY_COUNT}" "${url}" >&2
      sleep "${RETRY_SLEEP}"
    fi

    if [[ -n "${active_browser}" ]]; then
      if "${YT_DLP}" "${COMMON_ARGS[@]}" --cookies-from-browser "${active_browser}" --sleep-requests 2 --sleep-interval 2 --max-sleep-interval 6 --output "${output_template}" "${url}"; then
        AUTO_COOKIE_BROWSER="${active_browser}"
        return 0
      fi
      exit_code=$?
    else
      if "${YT_DLP}" "${COMMON_ARGS[@]}" --sleep-requests 2 --sleep-interval 2 --max-sleep-interval 6 --output "${output_template}" "${url}"; then
        return 0
      fi
      exit_code=$?
      active_browser="$(detect_cookie_browser || true)"
      if [[ -n "${active_browser}" ]]; then
        echo "Reintentando con cookies de ${active_browser}..." >&2
      fi
    fi

    attempt=$((attempt + 1))
  done

  return "${exit_code}"
}

download_playlist() {
  local url="$1"
  local dest="$2"
  local list_id
  local playlist_dir
  local max_items="${YTMUSIC_MAX_ITEMS:-}"
  local -a entry_urls=()
  local idx=0
  local download_errors=0

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
    if ! download_single "${entry_url}" "${playlist_dir}/$(printf '%02d' "${idx}")_%(title)s__%(id)s.%(ext)s"; then
      printf '[download-error] Falló la descarga de: %s\n' "${entry_url}" >&2
      download_errors=$((download_errors + 1))
    fi
    if [[ -n "${ITEM_DELAY}" && "${ITEM_DELAY}" != "0" && ${idx} -lt ${#entry_urls[@]} ]]; then
      printf '[throttle] Esperando %ss antes del próximo tema\n' "${ITEM_DELAY}"
      sleep "${ITEM_DELAY}"
    fi
  done

  if [[ ${download_errors} -gt 0 ]]; then
    printf '[playlist-warning] Hubo %d descarga(s) fallidas; omito saneador y M3U\n' "${download_errors}" >&2
    return 1
  fi

  run_sanitizer "${playlist_dir}"
  export_playlist_m3u "${playlist_dir}" "$(basename "${playlist_dir}")"
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
  download_single "${URL}" "${DEST}/%(uploader|channel|artist|Unknown Artist)s/%(title)s__%(id)s.%(ext)s"
fi
