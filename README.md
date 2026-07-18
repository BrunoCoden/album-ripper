# ytmusic-rip

Wrapper de `yt-dlp` para descargar audio desde YouTube Music cuando una app más pesada falla o resulta innecesaria.

Incluye:

- un script CLI para bajar playlists o tracks;
- una ventana gráfica mínima para pegar la URL;
- un saneador integrado para postprocesar playlists descargadas;
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

## Uso

### Abrir la ventana gráfica

```bash
./ytmusic-rip-ui.sh
```

### Descargar una playlist

```bash
./ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...'
```

Al terminar la descarga de una playlist, el script corre automáticamente el saneador integrado sobre esa carpeta.

### Descargar un track

```bash
./ytmusic-rip.sh 'https://music.youtube.com/watch?v=...'
```

### Elegir carpeta destino

```bash
./ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...' "$HOME/Music/Pruebas"
```

## Variables útiles

```bash
YTMUSIC_MAX_ITEMS=3
YTMUSIC_COOKIES_BROWSER=firefox
YTMUSIC_EXTRA_ARGS='--write-info-json'
YTMUSIC_OUTPUT_DIR="$HOME/Downloads/YouTube Music"
YTMUSIC_YT_DLP="$HOME/albumripper-venv/bin/yt-dlp"
YTMUSIC_RUN_SANITIZER=1
YTMUSIC_SANITIZER_PYTHON="$HOME/albumripper-venv/bin/python"
YTMUSIC_SANITIZER_ARGS='--youtube-assist'
```

## Cómo funciona

Si recibe un track, lo descarga directo.

Si recibe una playlist, primero expande los items con `--flat-playlist` y luego descarga cada URL por separado. Ese flujo evita varios fallos que suelen aparecer al pedirle a `yt-dlp` que procese la playlist completa de una sola vez.

Después de bajar la playlist, ejecuta `tag_audio_from_filenames.py` sobre la carpeta descargada. Por defecto usa `--youtube-assist`.

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

- Puede aparecer ruido `Broken pipe` al limitar playlists con `YTMUSIC_MAX_ITEMS`.
- Algunas descargas futuras podrían requerir cookies del navegador.
- Si YouTube cambia sus restricciones, puede ser necesario actualizar `yt-dlp`.
- Si falta `mutagen` o falla el saneador, la ejecución termina con error después de descargar la playlist.
