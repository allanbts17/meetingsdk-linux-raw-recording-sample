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

Esta es la base persistente, no un agente completo ya desplegado. Antes de integrarla, implementar cifrado autenticado de sealed_payload con clave gestionada en Secret Manager: Store exige bytes y no cifra por sí mismo. No entregar JSON/password/URL sensible en texto plano. Pendientes ejecutor de trabajos, descargas, heartbeat, supervisión de procesos, cancelación prioritaria de play/leave y API HTTP. No usarla todavía para aceptar peticiones de producción.

Pruebas desde api/:

```powershell
python -m unittest discover -s tests -v
```
