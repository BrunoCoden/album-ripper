# Changelog

## v1.0.0 - 2026-07-19

Primera release estable del flujo unificado.

### Added

- soporte para procesar carpetas locales directamente desde `ytmusic-rip.sh`
- archivo `TAG_AUDIO_CONTEXT.md` con contexto tecnico y estado estable
- flujo estable de saneo + rename para descargas y carpetas locales

### Changed

- formato final de nombres unificado a `Artist - Title-VIDEO_ID.ext` cuando el ID esta disponible
- mejora del parser para evitar inversiones de `artist/title`
- mejor uso de YouTube `oEmbed` para resolver artista y simplificar titulos
- generacion de `.m3u` adaptada para reconocer nombres con `-VIDEO_ID`

### Fixed

- conservacion de `VIDEO_ID` en casos con guiones en el ID
- duplicacion de artista en nombres como `... - Pearl Jam`
- casos como `Audioslave - Like a Stone` que podian invertirse incorrectamente
- reduccion de nombres redundantes en varios casos provenientes de YouTube
