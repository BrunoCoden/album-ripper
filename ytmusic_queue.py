"""Telegram-side persistent queue. This module never downloads or polls Telegram."""
import json
import logging
from pathlib import Path
import re
import threading

from ytmusic_playlist import PlaylistError, atomic_text, normalize_url

JOB_NAME = re.compile(r'^[0-9]{1,20}\.json$')
MAX_JOBS = 20


def read_json(path):
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('Invalid queue file')
    return json.loads(path.read_text())


class MusicBridge:
    def __init__(self, api, spool):
        self.api, self.spool = api, Path(spool)

    def consume(self, text, update_id):
        command = text.split(maxsplit=1)
        music_command = bool(command and command[0].lower() == '/musica')
        if not music_command and not text.lower().startswith(('http:', 'https:')):
            return False
        if music_command and len(command) == 1:
            self.api.send('Enviá un enlace de playlist de YouTube Music, solo o después de /musica.')
            return True
        try:
            url = normalize_url(command[1] if music_command else text)
            if not isinstance(update_id, int) or update_id < 0 or len(str(update_id)) > 20:
                raise PlaylistError('Identificador de mensaje inválido.')
            name = str(update_id) + '.json'
            if any((self.spool / d / name).exists() for d in ('pending', 'running', 'results')):
                return True
            count = sum(len(list((self.spool / d).glob('*.json'))) for d in ('pending', 'running'))
            if count >= MAX_JOBS:
                raise PlaylistError('La cola está llena. Reintentá cuando terminen las descargas pendientes.')
            atomic_text(self.spool / 'pending' / name, json.dumps({'url':url}), 0o640)
            self.api.send('Playlist recibida. Quedó en cola; te aviso al terminar. /salud sigue disponible.')
        except PlaylistError as error:
            self.api.send(str(error))
        except OSError:
            logging.exception('No se pudo guardar el pedido de música')
            self.api.send('No pude guardar el pedido. Revisá el servicio de música y reenviá el enlace.')
        return True

    def deliver_results(self):
        for path in sorted((self.spool / 'results').glob('*.json')):
            if not JOB_NAME.fullmatch(path.name):
                continue
            try:
                result = read_json(path)
                counts = [max(0, int(result.get(key, 0))) for key in ('new', 'reused', 'failed')]
                state = 'completo' if result.get('complete') else 'parcial'
                if not result.get('m3u') and 'm3u' in result:
                    state = 'no generado'
                text = 'Playlist procesada.\nNuevos: %d | Reutilizados: %d | Fallidos: %d\nM3U: %s.' % (*counts, state)
                if result.get('failed_ids'):
                    text += '\nPendientes: ' + ', '.join(str(v) for v in result['failed_ids'])[:1200]
                if result.get('errors'):
                    text += '\n' + '\n'.join(str(v) for v in result['errors'])[:1000]
                if result.get('exit_code'):
                    text += '\nEl trabajo terminó con errores. Podés reenviar el enlace para reintentar.'
                self.api.send(text)
                path.unlink()
            except (OSError, ValueError, TypeError, KeyError):
                logging.error('No se pudo leer un resultado de música: %s', path.name)
            # API failures propagate; keep result on disk for the next attempt.

    def watch(self, stop):
        while not stop.is_set():
            try:
                self.deliver_results()
            except Exception as error:
                logging.warning('No se pudo entregar un resultado de música (%s)', type(error).__name__)
            stop.wait(3)

    def start(self, stop):
        threading.Thread(target=self.watch, args=(stop,), name='music-results', daemon=True).start()
