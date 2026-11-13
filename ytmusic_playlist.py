#!/usr/bin/env python3
"""Ordered playlists, exact-ID reuse and a library-wide writer lock."""
import contextlib
import csv
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
TRAILING_ID = re.compile(r'(?:__|-)([A-Za-z0-9_-]{11})$')
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.mp4', '.flac', '.ogg', '.opus', '.wav'}

class PlaylistError(Exception):
    pass


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'\s', value):
        raise PlaylistError('Enviá un único enlace de playlist HTTPS.')
    try:
        u = urlsplit(value)
        values = parse_qs(u.query).get('list', [])
        if (u.scheme != 'https' or u.hostname not in {'music.youtube.com', 'www.youtube.com', 'youtube.com'}
                or u.username or u.password or u.port not in (None, 443)
                or u.path not in ('/playlist', '/watch') or len(values) != 1
                or not re.fullmatch(r'[A-Za-z0-9_-]{10,200}', values[0])):
            raise ValueError()
    except ValueError:
        raise PlaylistError('Enlace inválido: usá una playlist HTTPS de YouTube Music o YouTube.') from None
    return 'https://www.youtube.com/playlist?list=' + values[0]


@contextlib.contextmanager
def library_lock(root):
    lock_path = Path(root) / '.ytmusic-rip.lock'
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o660)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PlaylistError('La biblioteca está ocupada por otra descarga.') from None
        yield


def filename_id(path):
    match = TRAILING_ID.search(path.stem)
    return match[1] if match else None


def metadata_id(path):
    try:
        from mutagen import File
        audio = File(path)
        if not audio or not audio.tags:
            return None
        # Only provenance fields, never an arbitrary title/comment substring.
        for key, value in audio.tags.items():
            if str(key).lower() not in {'purl', 'webpage_url', 'woas', 'woaf', 'txxx:purl',
                                       'txxx:webpage_url', '----:com.apple.itunes:purl'}:
                continue
            values = value if isinstance(value, list) else getattr(value, 'text', [getattr(value, 'url', value)])
            for item in values:
                text = item.decode() if isinstance(item, bytes) else str(item)
                parsed = urlsplit(text)
                if parsed.hostname in {'www.youtube.com', 'youtube.com', 'music.youtube.com'}:
                    video = parse_qs(parsed.query).get('v', [''])[0]
                elif parsed.hostname == 'youtu.be':
                    video = parsed.path.lstrip('/')
                else:
                    continue
                if VIDEO_ID.fullmatch(video):
                    return video
    except Exception:
        # Broken tags must not prevent processing the rest of the library.
        return None
    return None


def usable_audio(path):
    try:
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS or path.stat().st_size == 0:
            return False
        with path.open('rb'):
            pass
        checked = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
                                  '-map', '0:a:0', '-f', 'null', '-'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
        return checked.returncode == 0 and not checked.stderr.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False


def index_library(root, wanted):
    found = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() not in AUDIO_EXTENSIONS or path.is_symlink():
                continue
            video = filename_id(path) or metadata_id(path)
            if video in wanted and video not in found and usable_audio(path):
                found[video] = path
    return found


def atomic_text(path, text, mode=0o644):
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def downloader():
    configured = os.environ.get('YTMUSIC_YT_DLP')
    found = configured or shutil.which('yt-dlp') or str(Path.home() / 'albumripper-venv/bin/yt-dlp')
    if not os.access(found, os.X_OK):
        raise PlaylistError('No encuentro yt-dlp; configurá YTMUSIC_YT_DLP.')
    return found


def auth_args():
    cookies = os.environ.get('YTMUSIC_COOKIES_FILE')
    browser = os.environ.get('YTMUSIC_COOKIES_BROWSER')
    if cookies:
        if not Path(cookies).is_file():
            raise PlaylistError('No se encuentra el archivo de cookies configurado.')
        return ['--cookies', cookies]
    if browser is None:
        browser = next((name for name, binary in [('firefox', 'firefox'), ('chrome', 'google-chrome'),
                                                ('chromium', 'chromium')] if shutil.which(binary)), None)
    return ['--cookies-from-browser', browser] if browser and browser != 'none' else []


def safe_name(title, byte_limit=120):
    name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', '_', title).strip(' .')
    name = name.encode('utf-8')[:byte_limit].decode('utf-8', errors='ignore').strip(' .')
    return name or 'playlist'


def download_failure_reason(stderr, returncode):
    """Translate known diagnostics; never copy potentially secret stderr to logs/Telegram."""
    text = (stderr or '').lower()
    if 'private video' in text:
        return 'Video privado; requiere una cuenta con acceso.'
    if any(value in text for value in ('not available in your country', 'not available in your region', 'geo-restricted')):
        return 'Video restringido en el país o región del servidor.'
    if any(value in text for value in ('sign in', 'login required', 'authentication required', 'confirm your age')):
        return 'YouTube requiere autenticación; revisá las cookies configuradas.'
    if any(value in text for value in ('video unavailable', 'this video is not available', 'video has been removed')):
        return 'Video no disponible según YouTube; no especifica si fue retirado o restringido.'
    if '429' in text or 'too many requests' in text:
        return 'YouTube limitó las solicitudes (HTTP 429); esperá antes de reintentar.'
    if '403' in text or 'forbidden' in text:
        return 'YouTube rechazó el acceso al recurso (HTTP 403).'
    if 'no space left' in text:
        return 'No queda espacio en el disco.'
    if 'permission denied' in text:
        return 'Faltan permisos para leer o escribir un archivo.'
    if returncode == 124 or 'timed out' in text or 'timeout' in text:
        return 'Se agotó el tiempo de espera de la descarga.'
    if any(value in text for value in ('name resolution', 'network is unreachable', 'connection refused')):
        return 'Falló la conexión de red con el servidor de descarga.'
    if 'requested format is not available' in text:
        return 'YouTube no ofrece el formato solicitado para este video.'
    return 'yt-dlp falló (código %d); no se reconoció una causa específica.' % returncode


def run_download(command, timeout=1800):
    # Keep output off the journal until classified. Bound the diagnostic read, not RAM.
    with tempfile.TemporaryFile() as diagnostic:
        try:
            result = subprocess.run(command, timeout=timeout, stdout=subprocess.DEVNULL, stderr=diagnostic)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(command, 124)
        end = diagnostic.tell()
        diagnostic.seek(max(0, end - 65536))
        result.stderr = diagnostic.read().decode('utf-8', errors='replace')
    return result


def run_playlist(url, root, metadata_only=False):
    url = normalize_url(url)
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with library_lock(root):
        return _run_playlist(url, root, metadata_only)


def _run_playlist(url, root, metadata_only):
    executable = downloader()
    auth = auth_args()
    args = [executable, '--ignore-config', *auth, '--flat-playlist', '--dump-single-json']
    if os.environ.get('YTMUSIC_MAX_ITEMS'):
        args += ['--playlist-end', str(int(os.environ['YTMUSIC_MAX_ITEMS']))]
    manifest = subprocess.run([*args, url], capture_output=True, text=True, timeout=300)
    if manifest.returncode:
        # Do not echo arbitrary downloader errors which might contain credentials.
        raise PlaylistError('No pude obtener el manifest: ' + download_failure_reason(manifest.stderr, manifest.returncode))
    try:
        data = json.loads(manifest.stdout)
        entries = data['entries']
        if not isinstance(entries, list) or not entries:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise PlaylistError('La playlist está vacía o su manifest es inválido.') from None
    playlist_id = parse_qs(urlsplit(url).query)['list'][0]
    name = safe_name(str(data.get('title') or playlist_id), min(120, 220 - len(playlist_id) - 1)) + '-' + playlist_id
    folder = root / name
    if folder.is_symlink():
        raise PlaylistError('La carpeta de playlist no puede ser un enlace simbólico.')
    folder.mkdir(mode=0o755, exist_ok=True)
    rows = []
    for i, entry in enumerate(entries, 1):
        entry = entry or {}
        video = str(entry.get('id') or '')
        rows.append((i, video if VIDEO_ID.fullmatch(video) else '', str(entry.get('title') or '[no disponible]')))
    manifest_path = folder / (name + '.entries.tsv')
    import io
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter='\t', lineterminator='\n')
    writer.writerow(['index', 'video_id', 'title', 'url'])
    writer.writerows((i, v, title, 'https://www.youtube.com/watch?v=' + v if v else '') for i, v, title in rows)
    atomic_text(manifest_path, buffer.getvalue())
    result = dict(new=0, reused=0, failed=0, failed_ids=[], errors=[], complete=False,
                  m3u=None, manifest=str(manifest_path), exit_code=0, metadata_only=metadata_only)
    if metadata_only:
        return result
    wanted = {v for _, v, _ in rows if v}
    paths = index_library(root, wanted)
    result['reused'] = len(paths)
    attempted = set(paths)
    retries = max(1, int(os.environ.get('YTMUSIC_RETRY_COUNT', '3')))
    for index, video, title in rows:
        if not video or video in attempted:
            continue
        attempted.add(video)
        print('Descargando %d/%d: https://www.youtube.com/watch?v=%s' % (index, len(rows), video), flush=True)
        with tempfile.TemporaryDirectory(prefix='.download-' + video + '-', dir=folder) as temporary:
            stage = Path(temporary)
            template = str(stage / ('%(title)s__' + video + '.%(ext)s'))
            command = [executable, '--ignore-config', *auth, '--no-playlist', '--extract-audio', '--audio-format', 'mp3',
                       '--audio-quality', '0', '--no-keep-video', '--embed-thumbnail', '--add-metadata',
                       '--convert-thumbnails', 'jpg', '--newline', '--restrict-filenames',
                       '--sleep-requests', '2', '--sleep-interval', '2', '--max-sleep-interval', '6',
                       *shlex.split(os.environ.get('YTMUSIC_EXTRA_ARGS', '')), '--output', template,
                       'https://www.youtube.com/watch?v=' + video]
            downloaded = False
            failure_reason = 'No se obtuvo un archivo de audio completo y legible.'
            for attempt in range(retries):
                if attempt:
                    time.sleep(float(os.environ.get('YTMUSIC_RETRY_SLEEP', '8')))
                completed = run_download(command)
                if completed.returncode == 0:
                    downloaded = True
                    break
                failure_reason = download_failure_reason(completed.stderr, completed.returncode)
                print('[download-error] ID=%s intento=%d/%d código=%d motivo=%s' %
                      (video, attempt + 1, retries, completed.returncode, failure_reason), flush=True)
                if any(filename_id(p) == video and usable_audio(p) for p in stage.iterdir()):
                    result['errors'].append('%s [%s]: %s Se conservó el audio válido.' % (title[:160], video, failure_reason))
                    downloaded = True
                    break
            if downloaded:
                if os.environ.get('YTMUSIC_RUN_SANITIZER', '1') != '0':
                    sanitizer = Path(__file__).with_name('tag_audio_from_filenames.py')
                    python = os.environ.get('YTMUSIC_SANITIZER_PYTHON', sys.executable)
                    options = shlex.split(os.environ.get('YTMUSIC_SANITIZER_ARGS', '--youtube-assist --rename'))
                    try:
                        sanitized = subprocess.run([python, str(sanitizer), *options, str(stage)], timeout=300)
                    except subprocess.TimeoutExpired:
                        sanitized = subprocess.CompletedProcess([], 124)
                    if sanitized.returncode:
                        result['errors'].append('Falló el saneador para ' + video)
                candidates = [p for p in stage.iterdir() if filename_id(p) == video and usable_audio(p)]
                if candidates:
                    source = sorted(candidates)[0]
                    target = folder / source.name
                    if target.exists() or target.is_symlink():
                        target = folder / ('recovered-' + uuid.uuid4().hex[:12] + '__' + video + source.suffix)
                    source.chmod(0o644)
                    # Never overwrite an unrelated/corrupt preexisting file.
                    os.link(source, target)
                    source.unlink()
                    paths[video] = target
                    result['new'] += 1
            if video not in paths:
                result['failed_ids'].append(video)
                if len(result['errors']) < 50:
                    result['errors'].append('%s [%s]: %s' % (title[:160], video, failure_reason))
        if index < len(rows):
            time.sleep(float(os.environ.get('YTMUSIC_ITEM_DELAY', '3')))
    unavailable = sum(not v for _, v, _ in rows)
    result['failed'] = len(result['failed_ids']) + unavailable
    result['complete'] = result['failed'] == 0
    if os.environ.get('YTMUSIC_EXPORT_M3U', '1') != '0':
        m3u = folder / (name + '.m3u')
        lines = ['#EXTM3U'] + [os.path.relpath(paths[v], folder) for _, v, _ in rows if v in paths]
        atomic_text(m3u, '\n'.join(lines) + '\n')
        result['m3u'] = str(m3u)
    result['exit_code'] = int(bool(result['failed'] or result['errors']))
    print('[playlist] ' + json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main():
    try:
        result = run_playlist(sys.argv[1], sys.argv[2], '--metadata-only' in sys.argv[3:])
    except (PlaylistError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        text = str(error) if isinstance(error, PlaylistError) else type(error).__name__
        result = dict(new=0, reused=0, failed=0, failed_ids=[], complete=False, m3u=None,
                      exit_code=1, errors=[text])
        print('[playlist-error] ' + text, file=sys.stderr)
    if os.environ.get('YTMUSIC_RESULT_FILE'):
        atomic_text(Path(os.environ['YTMUSIC_RESULT_FILE']), json.dumps(result, ensure_ascii=False), 0o600)
    return result['exit_code']

if __name__ == '__main__':
    raise SystemExit(main())
