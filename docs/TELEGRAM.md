# Música desde un bot de salud existente

## Alcance

El receptor de referencia `deploy/server-check-telegram.py` conserva `/salud`, `/ayuda` y `/start`, y agrega playlists de YouTube Music y YouTube mediante un enlace HTTPS o `/musica ENLACE`. Hay un único receptor de Telegram; solo acepta mensajes privados del ID configurado.

Este receptor está integrado con `server-check.service` y sus informes. Antes de usarlo en otro servidor, comparalo con el bot existente y adaptá esa integración. No sobrescribas un receptor diferente sin revisar sus comandos y configuración.

El descargador corre como un usuario sin root. El receptor escribe pedidos en una cola local, el worker verifica el montaje y los permisos y procesa un trabajo a la vez. Las credenciales de Telegram nunca se pasan al descargador.

## Archivos públicos y configuración local

- `deploy/config.example.json`: ejemplo de configuración del worker. Copialo a `deploy/config.local.json`, que Git ignora, y completá `library`, `mount` y `uuid`.
- `deploy/ytmusic-rip-worker.service.example`: ejemplo de unidad systemd. Copialo a `deploy/ytmusic-rip-worker.local.service`, también ignorado, y adaptá `User`, `Group`, `SupplementaryGroups` y `ReadWritePaths`.
- `deploy/music.conf`: drop-in para conectar el receptor con la cola.
- `deploy/requirements-server.txt`: versiones de dependencias utilizadas en las pruebas.
- `deploy/activate.sh` y `deploy/rollback.sh`: helpers para una instalación revisada y respaldada. No constituyen un instalador genérico.

Los nombres `ytmusic` y `media`, y las rutas `/srv/music/library` y `/srv/music`, son ejemplos. El UUID debe ser el del sistema de archivos real; nunca instales el marcador `REPLACE_WITH_FILESYSTEM_UUID`.

Los informes operativos, los datos de acceso y los instaladores específicos de un host se mantienen en `.private/` o archivos `*.local.*`. No se distribuyen con el repositorio público.

## Preparación del despliegue

Realizá estos pasos con permisos administrativos, revisando los valores para tu servidor:

1. Identificá la carpeta que Navidrome escanea y el montaje correspondiente. Si usa un contenedor, verificá la correspondencia entre las rutas del contenedor y del host. Consultá `findmnt --target RUTA --output TARGET,UUID` y completá la configuración local.
2. Elegí un usuario y grupo sin privilegios para el worker. Ese usuario debe poder escribir en la biblioteca y Navidrome debe poder leer los audios y playlists resultantes. Ajustá permisos del montaje existente; no crees una biblioteca sustituta cuando falte el disco.
3. Instalá Bash, Python con soporte para venv, FFmpeg, findmnt y flock. Creá `/opt/ytmusic-rip`, propiedad de root, e instalá allí `ytmusic-rip.sh`, `tag_audio_from_filenames.py`, `ytmusic_playlist.py`, `ytmusic_queue.py` y `ytmusic_worker.py`. Creá su venv e instalá `deploy/requirements-server.txt`.
4. Instalá un runtime JavaScript compatible con yt-dlp, por ejemplo Deno, en `/opt/ytmusic-rip/bin`. Verificá la descarga contra su checksum oficial. El worker incluye esa carpeta en PATH. `wheelhouse/` y `runtime/` son artefactos locales ignorados por Git.
5. Instalá la configuración local como `/etc/ytmusic-rip/config.json`, propietario root, grupo del worker y modo `0640`. El directorio debe permitir lectura y recorrido a ese grupo.
6. Creá `/var/lib/ytmusic-rip` y sus subdirectorios `pending`, `running` y `results`, propietario root, grupo del worker y modo `2770`. El receptor root y el worker deben poder acceder. Los pedidos usan modo `0640`; los resultados, sin credenciales, `0644`.
7. Conservá `BOT_TOKEN` y `CHAT_ID` en el archivo de entorno del receptor, fuera del repositorio y con permisos restrictivos. No hace falta crear un segundo bot. Respaldá el receptor existente y sus drop-ins antes de instalar la extensión.
8. Instalá la unidad local como `/etc/systemd/system/ytmusic-rip-worker.service` y `deploy/music.conf` como `/etc/systemd/system/server-check-telegram.service.d/music.conf`. El receptor debe poder escribir en la cola aun si usa `ProtectSystem=strict`.
9. Comprobá la biblioteca con el usuario real del worker y verificá las unidades. Después recargá systemd, habilitá el worker y reiniciá el receptor. Si la activación falla, restaurá el receptor y el drop-in respaldados.

Ejemplo de comprobación con el usuario del ejemplo:

```bash
runuser -u ytmusic -- /opt/ytmusic-rip/venv/bin/python /opt/ytmusic-rip/ytmusic_worker.py /etc/ytmusic-rip/config.json --check
systemd-analyze verify /etc/systemd/system/ytmusic-rip-worker.service /etc/systemd/system/server-check-telegram.service
```

El worker requiere visibilidad suficiente para resolver el UUID mediante findmnt. `ReadWritePaths` puede crear un bind mount dentro del namespace del servicio; también se valida que esa biblioteca pertenezca al mismo sistema de archivos. Comprobá el acceso efectivo dentro de las protecciones de systemd antes de dar la instalación por terminada.

## Operación y logs

```bash
systemctl status server-check-telegram ytmusic-rip-worker --no-pager
journalctl -u ytmusic-rip-worker -n 100 --no-pager
journalctl -u server-check-telegram -n 100 --no-pager
```

Hay un máximo de 20 trabajos pendientes/activos. `/salud` sigue disponible durante las descargas. Los errores conocidos de yt-dlp se traducen a mensajes con título, ID y motivo; el journal registra código e intento. No se publica stderr crudo, que podría contener credenciales. Para causas desconocidas se informa el código sin inventar una explicación.

Los trabajos que quedaron en `running` se recuperan al arrancar. Los temas ya publicados se reutilizan. Una descarga interrumpida antes de publicar el audio puede reiniciarse; las carpetas `.download-*` huérfanas se ignoran en el índice.

Los resultados se conservan mientras Telegram no esté disponible. Pueden notificarse nuevamente si el receptor cae justo después del envío y antes de eliminarlos. Como en el receptor original, el offset se guarda antes de ejecutar un comando: si cae entre guardar el offset y persistir la solicitud, hay que reenviar el enlace.

Ante disco ausente, UUID distinto, solo lectura o falta de permisos, se aborta antes de crear carpetas de playlists. El usuario recibe el motivo y puede reenviar al restaurar la biblioteca.

## Cookies opcionales

Si YouTube exige autenticación, guardá las cookies Netscape fuera del repositorio, por ejemplo en `/etc/ytmusic-rip/youtube.cookies`, propiedad del usuario del worker y modo `0600`. Agregá `YTMUSIC_COOKIES_FILE` con esa ruta al objeto `environment` de la configuración. No pegues cookies ni tokens en Git, logs o mensajes de Telegram.

El worker solo admite una lista fija de variables. No admite `YTMUSIC_EXTRA_ARGS` desde Telegram ni desde su configuración. El CLI conserva esa opción para uso manual.

## Verificación de aceptación

1. `/ayuda` muestra `/musica` y `/salud` sigue entregando el informe.
2. Una playlist corta con un tema existente en otra carpeta y uno faltante descarga solo el faltante, sin copiar ni mover el existente.
3. El M3U conserva rutas relativas, orden y repeticiones. Comprobá su importación y reproducción en Navidrome.
4. Reenviar la lista informa cero temas nuevos.
5. Un usuario ajeno o chat grupal se ignora; un enlace inválido se rechaza sin encolar.
6. Los fallos de montaje y permisos se ensayan en carpetas temporales, sin desmontar ni modificar la biblioteca real.

La suite usa audio sintético y un descargador controlado para probar parcial/reintento, errores tardíos, metadatos, Unicode, deduplicación, cola tras reinicio, exclusión de credenciales y concurrencia con `/salud`. Las pruebas automáticas no sustituyen el ensayo final en Telegram y Navidrome.

## Referencias

- [Configuración oficial de JavaScript/EJS para yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
- [Releases oficiales de Deno](https://github.com/denoland/deno/releases).
