#!/usr/bin/env python3
"""Unprivileged, single-consumer queue worker; no Telegram credentials."""
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading

from ytmusic_playlist import PlaylistError, atomic_text, normalize_url
from ytmusic_queue import JOB_NAME, read_json


def mount_info(root):
    result = subprocess.run(['findmnt', '--json', '--target', str(root), '--output', 'TARGET,UUID'],
                            capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


def check_library(root, mount, uuid):
    root, mount = Path(root), Path(mount)
    if not root.is_dir():
        raise PlaylistError('La biblioteca no está disponible; no se creó ninguna carpeta.')
    if root.resolve() != root or mount.resolve() != mount or not root.is_relative_to(mount):
        raise PlaylistError('La ruta de biblioteca no corresponde al montaje configurado.')
    try:
        info = mount_info(mount)['filesystems']
        library_info = mount_info(root)['filesystems']
        # ProtectSystem/ReadWritePaths may bind-mount the library inside the unit.
        valid = (len(info) == 1 and info[0]['target'] == str(mount) and info[0]['uuid'] == uuid
                 and len(library_info) == 1 and library_info[0]['uuid'] == uuid
                 and Path(library_info[0]['target']).is_relative_to(mount))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        valid = False
    if not valid:
        raise PlaylistError('El montaje de música está ausente o no tiene el UUID esperado.')
    if not os.access(root, os.W_OK | os.X_OK, effective_ids=True):
        raise PlaylistError('El usuario del servicio no puede escribir en la biblioteca.')
    try:
        with tempfile.TemporaryFile(dir=root):
            pass
    except OSError:
        raise PlaylistError('No se puede escribir en la biblioteca; revisá permisos y espacio.') from None


def process_one(config):
    spool = Path(config['spool'])
    jobs = sorted((spool / 'running').glob('*.json')) or sorted((spool / 'pending').glob('*.json'))
    jobs = [p for p in jobs if JOB_NAME.fullmatch(p.name)]
    if not jobs:
        return False
    request = jobs[0]
    result_path = spool / 'results' / request.name
    if result_path.exists():
        request.unlink()
        return True
    running = spool / 'running' / request.name
    if request != running:
        os.replace(request, running)
    result = dict(new=0, reused=0, failed=0, failed_ids=[], complete=False, m3u=None, exit_code=1, errors=[])
    try:
        job = read_json(running)
        url = normalize_url(job['url'])
        check_library(config['library'], config['mount'], config['uuid'])
        with tempfile.TemporaryDirectory(prefix='ytmusic-result-') as temporary:
            output = Path(temporary) / 'result.json'
            # Do not inherit BOT_TOKEN, shell hooks or unrelated process credentials.
            env = {'PATH':'/opt/ytmusic-rip/bin:/usr/local/bin:/usr/bin:/bin', 'HOME':os.environ.get('HOME', '/var/lib/ytmusic-rip'),
                   'LANG':'C.UTF-8', 'PYTHONUNBUFFERED':'1', 'YTMUSIC_COOKIES_BROWSER':'none',
                   'YTMUSIC_RESULT_FILE':str(output)}
            for key in ('YTMUSIC_YT_DLP', 'YTMUSIC_SANITIZER_PYTHON', 'YTMUSIC_COOKIES_FILE',
                        'YTMUSIC_ITEM_DELAY', 'YTMUSIC_RETRY_COUNT', 'YTMUSIC_RETRY_SLEEP'):
                if key in config.get('environment', {}):
                    env[key] = str(config['environment'][key])
            completed = subprocess.run([config['script'], url, config['library']], env=env, check=False)
            if output.is_file():
                result = read_json(output)
            else:
                result['errors'] = ['El descargador no produjo un resultado. Revisá el journal.']
            if completed.returncode:
                result['exit_code'] = completed.returncode
                if not result.get('errors') and not result.get('failed'):
                    result['errors'] = ['El descargador terminó con error (código %d).' % completed.returncode]
    except PlaylistError as error:
        result['errors'] = [str(error)]
    except Exception as error:
        logging.error('Trabajo %s falló (%s)', running.stem, type(error).__name__)
        result['errors'] = ['No se pudo completar el trabajo (%s).' % type(error).__name__]
    atomic_text(result_path, json.dumps(result, ensure_ascii=False), 0o644)
    running.unlink()
    logging.info('Trabajo %s: nuevos=%s reutilizados=%s fallidos=%s código=%s', running.stem,
                 result['new'], result['reused'], result['failed'], result['exit_code'])
    return True


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    if os.geteuid() == 0:
        raise SystemExit('El worker de música debe ejecutarse sin root.')
    config = json.loads(Path(sys.argv[1]).read_text())
    if '--check' in sys.argv[2:]:
        check_library(config['library'], config['mount'], config['uuid'])
        print('Biblioteca, montaje y escritura verificados.')
        return
    with (Path(config['spool']) / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        while not stop.is_set():
            if not process_one(config):
                stop.wait(2)

if __name__ == '__main__': main()
