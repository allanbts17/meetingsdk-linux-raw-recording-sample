# Bot de reproducción para Zoom Meeting SDK Linux

Proyecto basado en [zoom/meetingsdk-linux-raw-recording-sample](https://github.com/zoom/meetingsdk-linux-raw-recording-sample), adaptado a Zoom Meeting SDK Linux x86_64 **7.1.5.4432** y Ubuntu 22.04.

Reproduce una vez un MP4 por cámara virtual y micrófono virtual, con reloj compartido, sonido original para conservar música y comandos de pausa, reanudación, detención y salida. Las pruebas actuales se realizan en reuniones de la cuenta propietaria de la app.

## Requisitos

- Docker con contenedores Linux amd64; en Windows se usa Docker Desktop/WSL2.
- SDK Linux descargado e integrado localmente; sus binarios y encabezados no se versionan.
- App de Zoom con Meeting SDK habilitado y credenciales locales.
- Node.js para generar configuración/JWT, sin dependencias externas.
- Archivo local compatible con FFmpeg que contenga las pistas activadas.

## Integrar el SDK

Copiar el contenido del paquete descargado:

- `h` a `demo/include/h`.
- Bibliotecas `lib*.so` a `demo/lib/zoom_meeting_sdk`.
- `qt_libs`, `json`, `images`, `imjs`, `new_home_page` y `diagnostic` dentro de `demo/lib/zoom_meeting_sdk`, conservando sus carpetas.

CMake crea el enlace `libmeetingsdk.so.1` en Linux. La imagen incluye FFmpeg y PulseAudio.

## Compilar

Desde la raíz del repositorio:

```powershell
docker build -t zoom-msdk:7.1.5 -f Dockerfile-Ubuntu/Dockerfile .
```

La imagen utiliza configuración de ejemplo. Las credenciales reales se montan al ejecutar el contenedor.

## Configurar y ejecutar

Seguir [docs/configuracion.md](docs/configuracion.md): crear `config/local.json` desde su ejemplo, completar los datos localmente y generar JWT con `node scripts/prepare-config.cjs --av`. Montar configuración y video de solo lectura al ejecutar Docker.

El reproductor actual valida un archivo local antes de conectar. La descarga desde un enlace de Storage y el control por API forman parte de una propuesta de despliegue pendiente de confirmar; todavía no están implementados.

## Documentación y seguimiento

- [Plan de tareas](docs/plan.md): pasos y casillas verificadas.
- [Seguimiento técnico](docs/seguimiento.md): hallazgos, errores, decisiones y datos pendientes.
- [Configuración y controles](docs/configuracion.md): ejecución y comandos.
- [Pruebas](docs/pruebas.md): suite automatizada y validaciones realizadas en Zoom.

No guardar credenciales ni videos en Git ni incluirlos en la imagen. La situación de soporte/uso automatizado de Meeting SDK está registrada en el seguimiento.

## Licencia

Se conserva la [licencia MIT del proyecto de origen](LICENSE.md). El SDK de Zoom tiene sus propios términos de uso.
