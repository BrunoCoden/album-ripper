# ytmusic-rip Context

## Estado actual

Estado: estable para descarga de YouTube Music y saneo de carpetas locales.
Fecha de estabilizacion: 2026-07-19.

El proyecto usa un solo formato final de biblioteca:

- `Artist - Title-VIDEO_ID.ext` cuando existe ID de YouTube
- `Artist - Title.ext` cuando no hay ID recuperable

## Entradas soportadas

### 1. URL de YouTube Music o YouTube

- track individual
- playlist

### 2. Carpeta local

Si el input es una carpeta local, `ytmusic-rip.sh` no descarga nada y ejecuta solo saneo + rename.

## Flujo estable

### Track individual

1. descarga con `yt-dlp`
2. saneo de tags
3. rename al formato estable

### Playlist

1. expansion con `--flat-playlist`
2. descarga item por item
3. manifest `.entries.tsv`
4. saneo de tags
5. rename al formato estable
6. generacion de `.m3u`

### Carpeta local

1. sin descarga
2. saneo de tags
3. rename al formato estable

## Decisiones de implementacion relevantes

- El wrapper acepta carpeta local como primer argumento.
- El saneador integrado usa `--youtube-assist --rename` como modo recomendado.
- El generador de `.m3u` reconoce nombres renombrados con sufijo `-VIDEO_ID`.
- Si hubo fallos parciales en una playlist, el manifest se conserva y el `.m3u` puede salir parcial.

## Variables recomendadas

```bash
export YTMUSIC_YT_DLP="$HOME/albumripper-venv/bin/yt-dlp"
export YTMUSIC_SANITIZER_PYTHON="$HOME/albumripper-venv/bin/python"
export YTMUSIC_SANITIZER_ARGS='--youtube-assist --rename'
```

## Uso recomendado

### Descargar playlist

```bash
./ytmusic-rip.sh 'https://music.youtube.com/playlist?list=...'
```

### Procesar carpeta local

```bash
./ytmusic-rip.sh '/ruta/a/la/carpeta'
```

## Limitaciones conocidas

- Si YouTube bloquea por red, cookies o anti-bot, la descarga puede seguir fallando aun con reintentos.
- Si un archivo local ya perdio el `VIDEO_ID`, el rename no puede restaurarlo desde el nombre solo.
- Algunos casos extremos de titulos de YouTube todavia pueden requerir criterio manual.

## Release estable

Esta version corresponde a la primera release estable del flujo unificado:

- descarga opcional
- saneo de tags
- rename consistente
- `.m3u` para playlists
