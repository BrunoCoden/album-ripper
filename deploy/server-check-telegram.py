#!/usr/bin/python3
"""Comandos de Telegram para el server-check existente. Solo biblioteca estándar."""
import fcntl
import json
import logging
import os
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SERVICE = 'server-check.service'
STATE = Path('/var/lib/server-check-telegram')
LOGDIR = Path('/var/log/server-check')
MAX_REPORT_BYTES = 5 * 1024 * 1024
COMMAND_MAX_AGE = 300
OFFSET_MAX_AGE = 6 * 86400
HELP = '/musica ENLACE — descargar una playlist; también podés enviar el enlace solo.\n/salud — ejecutar la prueba y recibir el informe completo.\n/ayuda — ver estos comandos.'


class APIError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__('Telegram devolvió el código %s' % code)


class Telegram:
    def __init__(self, token, chat_id):
        self.base = 'https://api.telegram.org/bot' + token + '/'
        self.chat_id = chat_id

    def call(self, method, payload=None, body=None, content_type=None):
        if body is None:
            body = json.dumps(payload or {}).encode('utf-8')
            content_type = 'application/json'
        request = urllib.request.Request(self.base + method, data=body,
                                         headers={'Content-Type': content_type})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            # No registrar la URL: contiene el token.
            raise APIError(error.code) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise APIError(0) from None
        if not result.get('ok'):
            raise APIError(result.get('error_code', 0))
        return result['result']

    def send(self, text):
        self.call('sendMessage', {'chat_id': self.chat_id, 'text': text[:3500]})

    def document(self, name, text):
        boundary = 'servercheck' + uuid.uuid4().hex
        name = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        prefix = (
            '--%s\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n%s\r\n'
            '--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
            'Content-Type: text/plain; charset=utf-8\r\n\r\n'
        ) % (boundary, self.chat_id, boundary, name)
        body = prefix.encode() + text.encode('utf-8') + ('\r\n--%s--\r\n' % boundary).encode()
        self.call('sendDocument', body=body,
                  content_type='multipart/form-data; boundary=' + boundary)


def redact(text, secret=''):
    if secret:
        text = text.replace(secret, '[TOKEN OCULTO]')
    return re.sub(r'\b\d{6,12}:[A-Za-z0-9_-]{20,}\b', '[TOKEN OCULTO]', text)


def snapshot(directory):
    files = {}
    for path in directory.glob('check-*.log'):
        try:
            stat = path.stat()
            if path.is_file() and not path.is_symlink():
                files[path] = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            pass
    return files


class HealthJob:
    def __init__(self, api, logdir=LOGDIR, execute=subprocess.run, secret=''):
        self.api, self.logdir, self.execute, self.secret = api, logdir, execute, secret

    def run_command(self, args, timeout=20):
        return self.execute(args, capture_output=True, text=True, timeout=timeout,
                            check=False, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
                                              'LANG': 'C.UTF-8'})

    def __call__(self):
        state = self.run_command(['/usr/bin/systemctl', 'show', SERVICE,
                                  '--property=ActiveState', '--value'])
        if state.returncode != 0:
            self.api.send('No pude consultar server-check.service. Revisá el servicio en el servidor.')
            return
        if state.stdout.strip() in ('activating', 'active', 'deactivating', 'reloading'):
            self.api.send('Ya hay una prueba de salud en curso. Esperá a que termine y enviá /salud de nuevo.')
            return
        before = snapshot(self.logdir)
        started = time.monotonic()
        try:
            completed = self.run_command(['/usr/bin/systemctl', 'start', SERVICE], timeout=960)
        except subprocess.TimeoutExpired:
            self.api.send('Se agotó el tiempo de espera de la prueba. Revisá server-check.service en el servidor.')
            return
        after = snapshot(self.logdir)
        fresh = [path for path, stat in after.items() if before.get(path) != stat]
        if not fresh:
            self.api.send('No encontré un informe nuevo de esta ejecución. '
                          'Revisá: journalctl -u server-check.service -n 50 --no-pager')
            return
        path = max(fresh, key=lambda candidate: after[candidate][1])
        with path.open('rb') as report_file:
            data = report_file.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            self.api.send('La prueba terminó, pero el informe supera 5 MiB. Consultalo en ' + str(path))
            return
        report = redact(data.decode('utf-8', errors='replace'), self.secret)
        critical = [line for line in report.splitlines() if re.match(r'^\s*\[CRITICAL\]', line)]
        warning = [line for line in report.splitlines() if re.match(r'^\s*\[WARN\]', line)]
        status = ('El servicio terminó con error (código %s).' % completed.returncode
                  if completed.returncode else 'La ejecución del servicio terminó correctamente.')
        summary = ('Prueba de salud — %s\n%s\nDuración: %s s\nCríticos: %s | Avisos: %s' %
                   (socket.gethostname(), status, int(time.monotonic() - started),
                    len(critical), len(warning)))
        if critical or warning:
            summary += '\n\n' + '\n'.join((critical + warning)[:8])[:2000]
        summary += '\n\nTe envío el informe completo a continuación.'
        self.api.send(summary)
        self.api.document(path.stem + '.txt', report)


class CommandBot:
    def __init__(self, api, chat_id, username, offset_file, runner, music=None):
        self.music = music
        self.api, self.chat_id, self.username = api, chat_id, username.lower()
        self.offset_file, self.runner = offset_file, runner
        self.lock = threading.Lock()
        self.offset = 0
        if offset_file.exists():
            self.offset = int(offset_file.read_text().strip())
            if self.offset < 0:
                raise ValueError('Estado de Telegram inválido')

    def save_offset(self, offset):
        temporary = self.offset_file.with_suffix('.new')
        with temporary.open('w') as stream:
            os.chmod(temporary, 0o600)
            stream.write(str(offset) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.offset_file)
        self.offset = offset

    def poll_offset(self):
        # Telegram puede elegir un ID menor después de una semana sin novedades.
        # Reiniciar antes de ese plazo evita confirmar y perder el próximo pedido.
        if self.offset and time.time() - self.offset_file.stat().st_mtime >= OFFSET_MAX_AGE:
            self.save_offset(0)
        return self.offset

    def consume(self, update):
        update_id = update['update_id']
        if update_id < self.offset:
            return
        # Persistir antes de ejecutar: un reinicio no repite un pedido ya aceptado.
        self.save_offset(update_id + 1)
        message = update.get('message', {})
        chat, sender = message.get('chat', {}), message.get('from', {})
        if (chat.get('type') != 'private' or chat.get('id') != self.chat_id
                or sender.get('id') != self.chat_id or sender.get('is_bot', False)):
            return
        age = time.time() - message.get('date', 0)
        if age < -60 or age > COMMAND_MAX_AGE:
            return
        text = message.get('text', '').strip()
        if self.music and self.music.consume(text, update_id):
            return
        match = re.fullmatch(r'/(salud|ayuda|start)(?:@([A-Za-z0-9_]+))?', text, re.I)
        if not match or (match[2] and match[2].lower() != self.username):
            if text.startswith('/'):
                self.api.send('Usá /salud, /ayuda o /musica ENLACE.')
            return
        if match[1].lower() in ('ayuda', 'start'):
            self.api.send(HELP)
            return
        if not self.lock.acquire(blocking=False):
            self.api.send('Ya hay una prueba de salud en curso. Esperá a que termine.')
            return
        worker = threading.Thread(target=self.run_health, name='salud', daemon=True)
        worker.start()

    def run_health(self):
        try:
            self.api.send('Iniciando la prueba de salud. Te aviso cuando termine.')
            self.runner()
        except Exception as error:
            # Nunca imprimir la excepción completa: podría contener credenciales.
            logging.error('No se pudo completar /salud (%s)', type(error).__name__)
            try:
                self.api.send('No pude completar la prueba o entregar el informe. '
                              'Revisá el registro de server-check-telegram.service.')
            except Exception:
                logging.error('No se pudo entregar el mensaje de error')
        finally:
            self.lock.release()


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    token = os.environ.get('BOT_TOKEN', '').strip()
    chat_id = os.environ.get('CHAT_ID', '').strip()
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token) or not chat_id.isdigit() or int(chat_id) <= 0:
        logging.error('Falta BOT_TOKEN o un CHAT_ID privado válido en telegram.conf')
        return 1
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    instance = (STATE / 'listener.lock').open('a')
    try:
        fcntl.flock(instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.error('Ya existe un receptor de Telegram en este servidor')
        return 1
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    api = Telegram(token, int(chat_id))
    music = None
    if os.environ.get('YTMUSIC_SPOOL'):
        from ytmusic_queue import MusicBridge
        music = MusicBridge(api, Path(os.environ['YTMUSIC_SPOOL']))
        music.start(stop)
    bot = None
    delay = 3
    while not stop.is_set():
        try:
            if bot is None:
                if api.call('getWebhookInfo').get('url'):
                    logging.error('El bot tiene un webhook. No se alteró su configuración.')
                    return 1
                username = api.call('getMe')['username']
                bot = CommandBot(api, int(chat_id), username, STATE / 'offset',
                                 HealthJob(api, secret=token), music=music)
                api.call('setMyCommands', {'scope': {'type': 'chat', 'chat_id': int(chat_id)},
                    'commands': [{'command': 'musica', 'description': 'Descargar playlist de YouTube Music'},
                                 {'command': 'salud', 'description': 'Ejecutar prueba de salud'},
                                 {'command': 'ayuda', 'description': 'Ver comandos disponibles'}]})
                logging.info('Receptor listo: /salud y /ayuda')
            updates = api.call('getUpdates', {'offset': bot.poll_offset(), 'timeout': 25,
                                              'allowed_updates': ['message']})
            for update in updates:
                if stop.is_set():
                    break
                bot.consume(update)
            delay = 3
        except APIError as error:
            if error.code in (401, 409):
                logging.error('Token inválido (401) o receptor/webhook en conflicto (409). Código: %s', error.code)
                return 1
            logging.warning('Telegram no disponible (código %s); reintentando', error.code)
            stop.wait(delay)
            delay = min(delay * 2, 30)
        except (OSError, ValueError):
            logging.error('No se pudo leer o guardar el estado local del receptor')
            return 1
    instance.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
