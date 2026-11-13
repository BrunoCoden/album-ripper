# Verificación reproducible

Desde la raíz del repositorio, con FFmpeg y un entorno Python que incluya mutagen:

```bash
python -m unittest discover -s tests -v
bash -n ytmusic-rip.sh ytmusic-rip-ui.sh deploy/activate.sh deploy/rollback.sh
```

La prueba de permisos debe ejecutarse con un usuario sin root; se omite cuando el entorno corre como root. El resto de las pruebas usa archivos temporales, audio sintético, un descargador controlado y un sustituto de Zenity. No necesita tokens ni realiza descargas reales de YouTube.

Los registros de aceptación de una instalación real se guardan en `.private/`, fuera de Git. La lista pública de comprobaciones para cada despliegue está en [TELEGRAM.md](TELEGRAM.md).
