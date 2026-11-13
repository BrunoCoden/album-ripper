# ytmusic-rip

Wrapper de `yt-dlp` para descargar audio desde YouTube Music cuando una app más pesada falla o resulta innecesaria.

Incluye:

- un script CLI para bajar playlists o tracks, o sanear una carpeta local;
- una ventana gráfica mínima para pegar la URL;
- un saneador integrado para postprocesar playlists descargadas;
- exportación automática de playlists `.m3u` para Navidrome;
- un instalador opcional para crear un acceso directo del escritorio.

## Requisitos

- `bash`
- `ffmpeg`
- `yt-dlp`
- `zenity` para la UI gráfica
- `python3`
- `mutagen`

## Instalación rápida

### Opción 1: `yt-dlp` global

Si `yt-dlp` ya está en tu `PATH`, no hace falta configurar nada más.

### Opción 2: `yt-dlp` en un venv

Podés indicar una ruta explícita:

```bash
export YTMUSIC_YT_DLP="$HOME/albumripper-venv/bin/yt-dlp"
```

Si no definís esa variable, el script intenta usar:

1. `yt-dlp` en `PATH`
2. `$HOME/albumripper-venv/bin/yt-dlp`

Para el saneador podés hacer lo mismo con el intérprete Python:

```bash
export YTMUSIC_SANITIZER_PYTHON="$HOME/albumripper-venv/bin/python"
```

### Opción 3: archivo de cookies exportado

Si YouTube sigue bloqueando incluso con `--cookies-from-browser`, podés usar un archivo exportado en formato Netscape:

```bash
export YTMUSIC_COOKIES_FILE="$HOME/Downloads/youtube-cookies.txt"
```

Ese archivo tiene prioridad sobre `YTMUSIC_COOKIES_BROWSER`.

## Uso

### Abrir la ventana gráfica

```bash
./ytmusic-rip-ui.sh
```

### Descargar una playlist

```bash
./ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...'
```

Para cada tema nuevo, el script sanea el audio antes de publicarlo en la biblioteca. Los archivos reutilizados no se modifican.

### Extraer solo metadata de una playlist

```bash
./ytmusic-rip.sh --playlist-metadata-only 'https://music.youtube.com/playlist?list=...'
```

Ese modo no descarga audio. Solo crea la carpeta de la playlist y un manifest `.entries.tsv` con `index`, `video_id`, `title` y `url`. Ese manifest también sirve para reconstruir después un `.m3u` en el orden de la playlist si la descarga quedó parcial.

### Descargar un track

```bash
./ytmusic-rip.sh 'https://music.youtube.com/watch?v=...'
```

### Sanear una carpeta local

```bash
./ytmusic-rip.sh '$HOME/Downloads/YouTube Music/Mi Carpeta'
```

Eso no descarga nada. Solo ejecuta saneo de tags y rename sobre esa carpeta.

### Elegir carpeta destino

```bash
./ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...' "$HOME/Music/Pruebas"
```

## Variables útiles

```bash
YTMUSIC_MAX_ITEMS=3
YTMUSIC_COOKIES_BROWSER=firefox
YTMUSIC_COOKIES_FILE="$HOME/Downloads/youtube-cookies.txt"
YTMUSIC_EXTRA_ARGS='--write-info-json'
YTMUSIC_OUTPUT_DIR="$HOME/Downloads/YouTube Music"
YTMUSIC_YT_DLP="$HOME/albumripper-venv/bin/yt-dlp"
YTMUSIC_RUN_SANITIZER=1
YTMUSIC_SANITIZER_PYTHON="$HOME/albumripper-venv/bin/python"
YTMUSIC_SANITIZER_ARGS='--youtube-assist --rename'
YTMUSIC_EXPORT_M3U=1
YTMUSIC_RETRY_COUNT=3
YTMUSIC_RETRY_SLEEP=8
YTMUSIC_ITEM_DELAY=3
```

## Cómo funciona

Si recibe una carpeta local, no descarga nada: ejecuta saneo de tags y rename directo sobre esa carpeta.

Si recibe un track, lo descarga directo.

Si recibe una playlist, `ytmusic_playlist.py` obtiene un manifest JSON mediante `yt-dlp`, escribe un TSV real y busca IDs exactos en toda la biblioteca. Reconoce nombres `__VIDEO_ID` y `-VIDEO_ID` y campos de procedencia de los tags. Solo reutiliza audio no vacío que FFmpeg pueda decodificar. No compara por título.

Un bloqueo por biblioteca evita escritores simultáneos. Cada ID faltante se descarga una vez (con reintentos ante fallos). Los nuevos audios se sanean en una carpeta temporal y se publican al finalizar. Un audio válido se conserva incluso si falla un postprocesador, y ese error se reporta.

El M3U conserva el orden original y las repeticiones, con rutas relativas incluso a otras carpetas. Si faltan temas, queda parcial y el comando devuelve error. Reenviar la playlist solo descarga los faltantes. Los contadores son por ID único; las entradas sin ID disponible se cuentan como fallidas.

Las carpetas nuevas se llaman `Título-ID_PLAYLIST`, para evitar mezclar listas con el mismo título. Las carpetas antiguas siguen participando de la deduplicación.

## Telegram: bot de salud existente

La integración amplía el receptor existente de `server-check-telegram.service`. Enviá un enlace HTTPS de playlist, o `/musica ENLACE`. `/salud` y `/ayuda` siguen disponibles durante las descargas. El receptor conserva sus credenciales y permisos; `ytmusic-rip-worker.service` procesa una cola persistente con un usuario sin privilegios, sin token de Telegram.

Ver [instalación, recuperación y pruebas](docs/TELEGRAM.md). El repositorio incluye ejemplos de configuración; las rutas, el UUID del montaje y el usuario del servicio se completan localmente antes de instalar.

## Destino por defecto

Usa esta prioridad:

1. `YTMUSIC_OUTPUT_DIR`, si está definida
2. `~/Music/YouTube Music`
3. `~/Downloads/YouTube Music`

## Acceso directo del escritorio

Para instalar un lanzador en aplicaciones:

```bash
./install-desktop.sh
```

Eso genera un `.desktop` en `~/.local/share/applications`.

## Limitaciones conocidas

- Algunas descargas futuras podrían requerir cookies del navegador o un archivo de cookies exportado manualmente.
- Si YouTube cambia sus restricciones, puede ser necesario actualizar `yt-dlp`.
- Si falla el saneador, conserva el audio válido y reporta el error; reintentar no vuelve a sanear archivos ya reutilizados.
- El `.m3u` se genera para playlists, no para tracks individuales.
- YouTube puede seguir bloquear descargas con `429` o desafíos anti-bot incluso usando cookies; ahora el script reintenta y baja la agresividad, pero no puede garantizar evitar esos bloqueos.

## Pruebas

```bash
~/albumripper-venv/bin/python -m unittest discover -s tests -v
bash -n ytmusic-rip.sh ytmusic-rip-ui.sh deploy/activate.sh deploy/rollback.sh
```

Las pruebas usan audio sintético y un descargador simulado; no requieren Telegram ni descargan música real. La prueba de permisos se ejecuta con un usuario sin root.

## Datos privados y publicación

Los tokens y el chat autorizado se configuran fuera del repositorio, en el entorno del receptor. `deploy/config.example.json` y `deploy/ytmusic-rip-worker.service.example` contienen valores genéricos: copiá los ejemplos a archivos `*.local.*` y completalos en tu equipo.

Git ignora `.private/`, archivos `*.local.*`, credenciales, cookies exportadas, claves privadas, logs y resultados de descargas. Los informes de servidores y los instaladores específicos de una máquina se conservan localmente; no forman parte de la distribución pública. No uses `git add -f` para incluirlos. Las exclusiones no eliminan archivos ya versionados: revisá `git diff --cached` antes de publicar.
