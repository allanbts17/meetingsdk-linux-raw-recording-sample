# API y agente

El código Python de API/agente se organiza bajo `api/`. Contrato HTTP: [api-propuesta.md](../docs/api-propuesta.md). Despliegue previsto: FastAPI en Cloud Run con IAM Invoker; agente en GCE con estado SQLite. HTTP y despliegue aún pendientes.

`app/sdk_control.py` implementa el cliente privado del socket Unix del SDK. Se ejecuta dentro de Linux junto al agente; no conecta directamente desde Cloud Run ni expone el socket en Internet.

Protocolo: una línea JSON por conexión, versión 1, máximo 8192 bytes, `operation_id`, `command` y `playback_id` para controles. `play` recibe `path` absoluto local y `media_type`: video, video-silent o audio. El agente futuro valida/descarga la URL antes de entregar esa ruta. Imagen todavía devuelve MEDIA_TYPE_UNSUPPORTED.

`play` confirma configuración/solicitud de emisión; consultar status hasta observar reproducción. No confundir ACK con primer cuadro o audio recibido en Zoom. stop confirma decodificadores detenidos y mantiene la reunión; quit solicita salida y requiere esperar la terminación del proceso. El socket exige acceso local por permisos 0600. Las órdenes no tienen aún idempotencia duradera; será responsabilidad del agente SQLite. Ante timeout no repetir play a ciegas: consultar estado/playback_id.

Ejemplo dentro de Linux:

```python
from app.sdk_control import SdkControl
control = SdkControl()
control.command("status")
control.command("play", playback_id="intento-1", media_type="video", path="/app/media/video.mp4")
control.command("pause", playback_id="intento-1")
control.command("resume", playback_id="intento-1")
control.command("stop", playback_id="intento-1")
```
