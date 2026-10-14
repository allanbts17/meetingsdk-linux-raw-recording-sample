# API y agente

El código Python de API/agente se organiza bajo `api/`. Contrato HTTP: [api-propuesta.md](../docs/api-propuesta.md). Despliegue previsto: FastAPI en Cloud Run con IAM Invoker; agente en GCE con estado SQLite. HTTP y despliegue aún pendientes.

`app/sdk_control.py` implementa el cliente privado del socket Unix del SDK. Se ejecuta dentro de Linux junto al agente; no conecta directamente desde Cloud Run ni expone el socket en Internet.

Protocolo: una línea JSON por conexión, versión 1, máximo 8192 bytes, `operation_id`, `command` y `playback_id` para controles. `play` recibe `path` absoluto local y `media_type`: video, video-silent, audio o image. El agente futuro valida/descarga la URL antes de entregar esa ruta. Imagen admite PNG/JPEG de hasta 10 MiB: duration_seconds omitido/null mantiene el cuadro hasta stop; entre 1 y 3600 limita el tiempo activo. Pause conserva el cuadro y congela posición/temporizador. Status incluye position_seconds y puede indicar failed por fallo de decodificación/emisión.

`play` confirma configuración/solicitud de emisión; consultar status hasta observar reproducción. No confundir ACK con primer cuadro o audio recibido en Zoom. stop confirma decodificadores detenidos y mantiene la reunión; quit solicita salida y requiere esperar la terminación del proceso. El socket exige acceso local por permisos 0600. La capa SQLite ofrece idempotencia duradera, pero todavía no está conectada al ejecutor del SDK. Ante timeout no repetir play a ciegas: consultar estado/playback_id.

Ejemplo dentro de Linux:

```python
from app.sdk_control import SdkControl
control = SdkControl()
control.command("status")
control.command("play", playback_id="intento-1", media_type="video", path="/app/media/video.mp4")
control.command("pause", playback_id="intento-1")
control.command("resume", playback_id="intento-1")
control.command("stop", playback_id="intento-1")
control.command("play", playback_id="imagen-1", media_type="image", path="/tmp/demo.png", duration_seconds=30)
```

## Persistencia del agente

`app/store.py` implementa SQLite: sesiones, reserva única transaccional, operaciones en cola, claim exclusivo, eventos e idempotencia por cliente/método/ruta/clave. La respuesta se devuelve solo después del commit de sesión/operación/clave. La consulta pública no expone el payload; se purga al terminar/cancelar. Failed no libera capacidad por sí solo: se exige confirmar limpieza. Reinicio del supervisor cancela trabajos afectados y nunca reentra automáticamente.

Store exige bytes y no cifra por sí mismo. `app/agent.py` valida y cifra las peticiones mediante `app/payloads.py` antes de reservar/encolar; un worker distinto ejecuta la cola. AES-256-GCM autentica el payload y su contexto (cliente, comando y bot), con nonce aleatorio por mensaje. HKDF separa la clave de cifrado y la de fingerprints HMAC de idempotencia. La clave maestra debe mantenerse entre reinicios y recuperarse desde Secret Manager; esta conexión sigue pendiente. No llamar directamente a Store con payloads en texto plano.

`app/runtime.py` administra el SDK Linux: configuración/JWT fresco y logs 0600 dentro de un directorio 0700 por bot, socket propio y proceso con grupo independiente. La entrada mantiene medios apagados. Play espera contadores de cuadros/bloques aceptados; ante timeout de envío consulta el intento original sin repetirlo. Leave espera cierre y limpia el grupo si hace falta, antes de confirmar capacidad libre. El SDK admite ZOOM_CONFIG_PATH y ZOOM_CONTROL_SOCKET; sin variables conserva el flujo local anterior.

Pendientes: Secret Manager, descargas/caché de Storage, heartbeat y reconciliación de procesos tras reinicio, límites completos de sesión, cancelación prioritaria de play/leave y endpoints HTTP. El agente todavía no está desplegado ni preparado para aceptar tráfico de producción.

## Imagen de agente y prueba local explícita

Desde la raíz del repositorio:

```powershell
docker build -t zoom-msdk:7.1.5 -f Dockerfile-Ubuntu/Dockerfile .
docker build -t zoom-agent:dev -f api/Dockerfile.agent api
```

La imagen del agente extiende la imagen SDK. No incluye secretos ni medios. `tools/agent_demo.py` es una prueba de integración: toma configuración local protegida montada de solo lectura, genera una clave efímera para su base temporal, entra sin medios, reproduce un video montado y sale. Su resolver local es exclusivo de prueba y no descarga URLs de Storage. No equivale al servicio HTTP ni configura Secret Manager.

Ejemplo dentro del contenedor, después de inicializar PulseAudio:

```text
python3 -m tools.agent_demo --config /secrets/local.json --video /app/media/video.mp4 --hold-seconds 30
```

La configuración local usa el formato de config/local.json existente. No pasar passwords/tokens como argumentos ni copiarla a la imagen. Al finalizar, la prueba elimina configuración/logs/base temporal y confirma liberación de la capacidad.

Referencias de cifrado: [AEAD/AESGCM](https://cryptography.io/en/stable/hazmat/primitives/aead/), [HKDF](https://cryptography.io/en/stable/hazmat/primitives/key-derivation-functions/#hkdf).

Pruebas desde api/:

```powershell
python -m unittest discover -s tests -v
```

Dependencia del agente: `requirements-agent.txt` fija cryptography 50.0.2. Las pruebas también se ejecutan en Linux con la imagen del agente; instalar dependencias en un entorno virtual para desarrollo local.
