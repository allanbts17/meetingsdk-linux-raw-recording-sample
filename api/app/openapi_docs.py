"""Documentation only: enrich the generated contract without filtering replies."""
from copy import deepcopy

BOT_ID = "11223344-5566-4788-99aa-bbccddeeff00"
OP_ID = "aabbccdd-1122-4334-8556-77889900aabb"
PLAY_ID = "12345678-1234-4234-8234-123456789abc"
BUCKET = "https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/"
DESCRIPTION = """
Controla un bot para **una reunión simultánea**. Entrar y presentar medios son
órdenes independientes. Stop/fin del archivo conservan la reunión; DELETE sale.

### Abrir y probar en el navegador
Desde la raíz del proyecto, ejecutar `./scripts/open-swagger.ps1` y abrir
`http://localhost:8085/docs`. El proxy oficial de gcloud añade tu ID token;
no hace falta pegarlo en Authorize. La URL run.app directa exige IAM incluso
para /docs y /openapi.json. Firebase Auth no sustituye ese ID token.

### Flujo de prueba
1. GET /v1/capacity: comprobar available_slots=1 y worker_status=healthy.
2. POST /v1/bots: introducir número sin espacios, contraseña y nombre.
3. Copiar bot_id y operation_id; consultar GET /v1/operations/{operation_id}
   hasta succeeded. 202 significa **aceptado**, no que ya entró.
4. POST /v1/bots/{bot_id}/play: elegir ejemplo video, audio o imagen.
5. Consultar operación y estado. Guardar playback_id para los controles.
6. Probar pause, resume, stop. Después de stop se puede iniciar otro play.
7. DELETE /v1/bots/{bot_id}; consultar operación y capacidad hasta liberar plaza.

En cada POST/DELETE llenar **Idempotency-Key**. Generar una clave con
`[guid]::NewGuid().ToString()`. Nueva orden: nueva clave. Reintento de la misma
orden tras perder respuesta: **misma clave y mismo cuerpo**. Las claves duran
24 h; una operación antigua puede seguir siendo succeeded aunque el bot ya salió.

### Límites y medios
Solo HTTPS público de storage.googleapis.com/zoom-app-dev.firebasestorage.app.
Video: MP4 H.264, AAC si se habilita audio, hasta 1920x1080 y 30 FPS.
Audio: MP3, WAV PCM o M4A AAC. Imagen: PNG/JPEG, hasta 4096 por lado y 16 MP.
Máximo 1 GiB por video/audio, 10 MiB por imagen y 60 min por video/audio.
La resolución emitida depende de lo negociado con Zoom, no de la entrada.
Imagen sin duration_seconds sigue hasta stop/salida; una imagen no tiene audio.

60 solicitudes/minuto, 10 órdenes/minuto, ráfaga máxima de 5 órdenes/segundo.
Consultar operaciones cada 2-3 s. 409 expresa conflicto de estado/capacidad,
422 entrada inválida, 429 límite y 503 agente no disponible. Los errores de
descarga/SDK posteriores a 202 aparecen en la operación, no en la respuesta inicial.
Las políticas del anfitrión/red siguen en validación: no se garantiza reactivar
automáticamente una pista bloqueada por Zoom.
"""


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


STRING = {"type": "string"}
UUID = {"type": "string", "format": "uuid"}
BOOL = {"type": "boolean"}
INT = {"type": "integer", "minimum": 0}
NULL_UUID = {"anyOf": [UUID, {"type": "null"}]}
NULL_TIME = {"type": ["string", "null"], "format": "date-time"}


def enrich_openapi(schema):
    schema["info"]["description"] = DESCRIPTION
    schema["tags"] = [
        {"name": "Salud", "description": "Proceso HTTP y disponibilidad del agente privado."},
        {"name": "Capacidad", "description": "Una sola plaza; se conserva hasta confirmar limpieza."},
        {"name": "Bots", "description": "Entrar sin medios, consultar y salir de Zoom."},
        {"name": "Reproducción", "description": "Video, audio e imagen en una sesión existente."},
        {"name": "Operaciones", "description": "Resultado asíncrono de cada orden aceptada."},
        {"name": "Eventos", "description": "Historial ordenado, con paginación por secuencia."},
    ]
    schemas = schema["components"]["schemas"]
    schemas.update({
        "ApiErrorBody": obj({"error": obj({"code": STRING, "message": STRING,
            "request_id": UUID, "details": {"type": "array", "items": {"type": "object"}}},
            ("code", "message", "request_id"))}, ("error",)),
        "AcceptedOperation": obj({"bot_id": UUID, "operation_id": UUID,
            "status": {"type": "string", "enum": ["accepted", "queued", "succeeded"]},
            "action": {"type": "string", "enum": ["join", "play", "pause", "resume", "stop", "leave"]},
            "playback_id": NULL_UUID, "no_op": BOOL,
            "links": obj({"bot": STRING, "operation": STRING}, ("bot", "operation"))},
            ("bot_id", "operation_id", "status", "action", "links")),
        "PlaybackStatus": obj({"playback_id": NULL_UUID, "media_type": {"type": ["string", "null"]},
            "status": {"type": "string", "enum": ["idle", "buffering", "waiting", "playing", "paused", "stopped", "finished", "failed"]},
            "position_seconds": {"type": ["number", "null"]},
            "duration_seconds": {"type": ["number", "null"]}, "audio_enabled": {"type": ["boolean", "null"]},
            "pause_reasons": {"type": "array", "items": STRING},
            "can_pause": BOOL, "can_resume": BOOL, "can_stop": BOOL}),
        "BotStatus": obj({"bot_id": UUID, "status": {"type": "string", "enum": ["accepted", "preparing", "joining", "waiting_room", "active", "reconnecting", "leaving", "ended", "failed"]},
            "meeting": obj({"number": STRING, "participant_name": STRING, "status": STRING,
                "audio_permission": {"type": ["boolean", "null"]}, "video_permission": {"type": ["boolean", "null"]}}),
            "playback": ref("PlaybackStatus"),
            "media": {"type": ["object", "null"], "description": "Metadata de descarga y source; output puede ser null si el SDK no lo expone. No incluye URL ni rutas."},
            "pending_operation_id": NULL_UUID, "resource_released": BOOL, "state_version": INT,
            "created_at": NULL_TIME, "updated_at": NULL_TIME,
            "last_error": {"type": ["object", "null"], "properties": {"code": STRING}}}),
        "BotList": obj({"items": {"type": "array", "items": ref("BotStatus")},
            "next_cursor": {"type": ["string", "null"]}}, ("items", "next_cursor")),
        "OperationStatus": obj({"operation_id": UUID, "bot_id": UUID, "action": STRING,
            "playback_id": NULL_UUID, "status": {"type": "string", "enum": ["queued", "running", "succeeded", "failed", "cancelled"]},
            "no_op": BOOL, "requested_at": NULL_TIME, "started_at": NULL_TIME, "completed_at": NULL_TIME,
            "result": {"type": ["object", "null"], "description": "Resultado aplicado, por ejemplo posición y estado de reproducción."},
            "error": {"type": ["object", "null"], "properties": {"code": STRING}}}),
        "EventPage": obj({"items": {"type": "array", "items": obj({"sequence": INT,
            "type": STRING, "occurred_at": NULL_TIME, "data": {"type": "object"}}, ("sequence", "type", "occurred_at", "data"))},
            "next_after_sequence": INT, "has_more": BOOL}, ("items", "next_after_sequence", "has_more")),
        "Capacity": obj({"max_concurrent_bots": INT, "reserved_slots": INT, "available_slots": INT,
            "active_bot_id": NULL_UUID, "accepting_new_sessions": BOOL,
            "worker_status": {"type": "string", "enum": ["healthy", "unavailable"]}}),
        "Liveness": obj({"status": {"type": "string", "enum": ["ok"]}}, ("status",)),
        "Readiness": obj({"status": {"type": "string", "enum": ["ready", "not_ready"]},
            "checks": obj({"database": STRING, "worker": STRING})}),
    })
    schema["components"]["securitySchemes"]["BearerAuth"].update({
        "bearerFormat": "Google ID token",
        "description": "IAM Cloud Run: ID token con audience igual a URL base run.app y permiso run.invoker. Con el proxy local gcloud, no llenar Authorize.",
    })
    ticket = {"bot_id": BOT_ID, "operation_id": OP_ID, "status": "queued", "action": "play",
              "playback_id": PLAY_ID, "links": {"bot": "/v1/bots/" + BOT_ID, "operation": "/v1/operations/" + OP_ID}}
    routes = {
        ("/health/live", "get"): ("Salud", "Proceso HTTP vivo", "No comprueba conexión con el agente ni capacidad. IAM Cloud Run también protege esta ruta pública.", "Liveness", {"status": "ok"}),
        ("/health/ready", "get"): ("Salud", "Disponibilidad del agente", "200 si el heartbeat está vigente; 503 si no está listo. No libera plazas por falta de heartbeat.", "Readiness", {"status": "ready", "checks": {"database": "ok", "worker": "healthy"}}),
        ("/v1/capacity", "get"): ("Capacidad", "Consultar plaza disponible", "Antes de entrar, comprobar available_slots=1 y accepting_new_sessions=true. Una salida incompleta conserva la reserva.", "Capacity", {"max_concurrent_bots": 1, "reserved_slots": 0, "available_slots": 1, "active_bot_id": None, "accepting_new_sessions": True, "worker_status": "healthy"}),
        ("/v1/bots", "post"): ("Bots", "Entrar a Zoom sin medios", "Número de 9-11 dígitos sin espacios. No reproduce medios. Copiar bot_id/operation_id y esperar succeeded en la operación. La sala de espera puede exigir admisión del anfitrión.", "AcceptedOperation", dict(ticket, status="accepted", action="join", playback_id=None)),
        ("/v1/bots", "get"): ("Bots", "Listar bots e historial", "Orden descendente de creación. next_cursor permite otra página; conservar el mismo filtro status. No devolver credenciales.", "BotList", {"items": [], "next_cursor": None}),
        ("/v1/bots/{bot_id}", "get"): ("Bots", "Consultar reunión y reproducción", "active confirma entrada. resource_released confirma limpieza. position_seconds y capacidades pueden ser null cuando no se conocen. Un join histórico succeeded no implica sesión aún conectada.", "BotStatus", {"bot_id": BOT_ID, "status": "active", "meeting": {"number": "123456789", "participant_name": "VideoBot", "status": "in_meeting", "audio_permission": None, "video_permission": None}, "playback": {"playback_id": PLAY_ID, "media_type": "video", "status": "playing", "position_seconds": 12.4, "duration_seconds": 109.018, "audio_enabled": True, "pause_reasons": [], "can_pause": True, "can_resume": True, "can_stop": True}, "resource_released": False}),
        ("/v1/bots/{bot_id}", "delete"): ("Bots", "Salir y liberar el bot", "Sin cuerpo. Cancela órdenes pendientes y pide salida. Esperar operación succeeded y resource_released=true antes de asumir plaza libre. 200 si ya estaba liberado; 202 si debe ejecutarse.", "AcceptedOperation", dict(ticket, action="leave")),
        ("/v1/bots/{bot_id}/play", "post"): ("Reproducción", "Presentar video, audio o imagen", "Bot active y reproducción anterior detenida/terminada. Descarga y valida antes de emitir. El playback_id se asigna al aceptar. Succeeded confirma los primeros envíos requeridos, no el fin del clip. Video/audio se reproducen una vez.", "AcceptedOperation", ticket),
        ("/v1/bots/{bot_id}/pause", "post"): ("Reproducción", "Pausar el medio actual", "Congela posición, imagen y sonido manteniendo la reunión. Cuerpo opcional; playback_id protege frente a controlar otro intento. 200 no-op si la pausa ya estaba aplicada.", "AcceptedOperation", dict(ticket, action="pause")),
        ("/v1/bots/{bot_id}/resume", "post"): ("Reproducción", "Reanudar desde la pausa", "Continúa la posición; no reinicia un clip terminado. Bloqueos externos pueden rechazar resume con 409 PLAYBACK_BLOCKED. 200 no-op si ya estaba reproduciendo.", "AcceptedOperation", dict(ticket, action="resume")),
        ("/v1/bots/{bot_id}/stop", "post"): ("Reproducción", "Detener sin salir de Zoom", "Detiene ambas pistas y permite otro play desde cero. Puede cancelar una descarga en curso. 200 no-op si ya estaba detenido/terminado. La última imagen puede permanecer visible.", "AcceptedOperation", dict(ticket, action="stop")),
        ("/v1/operations/{operation_id}", "get"): ("Operaciones", "Consultar resultado de una orden", "Consultar cada 2-3 segundos hasta succeeded, failed o cancelled. Los fallos de SDK/medios posteriores a 202 aparecen en error.code. Las operaciones ya completadas permanecen históricas después de salir.", "OperationStatus", {"operation_id": OP_ID, "bot_id": BOT_ID, "action": "play", "playback_id": PLAY_ID, "status": "succeeded", "no_op": False, "requested_at": "2026-10-14T03:21:49Z", "started_at": "2026-10-14T03:21:49Z", "completed_at": "2026-10-14T03:21:51Z", "result": {"playback_id": PLAY_ID, "playback_status": "playing", "position_seconds": 0.04}, "error": None}),
        ("/v1/bots/{bot_id}/events", "get"): ("Eventos", "Consultar eventos por secuencia", "Historial agregado, no SSE ni WebSocket. Usar next_after_sequence en la siguiente consulta; si has_more=true quedan eventos. Ejemplos: meeting.joined, playback.started, operation.succeeded.", "EventPage", {"items": [{"sequence": 1, "type": "meeting.joined", "occurred_at": "2026-10-14T03:21:31Z", "data": {"operation_id": OP_ID}}], "next_after_sequence": 1, "has_more": False}),
    }
    error_codes = {400: "IDEMPOTENCY_KEY_REQUIRED", 404: "BOT_NOT_FOUND", 409: "CAPACITY_EXCEEDED",
                   413: "REQUEST_TOO_LARGE", 415: "UNSUPPORTED_CONTENT_TYPE", 422: "VALIDATION_ERROR",
                   429: "RATE_LIMITED", 503: "WORKER_UNAVAILABLE"}
    for (path, method), (tag, summary, description, model, example) in routes.items():
        operation = schema["paths"][path][method]
        operation.update(tags=[tag], summary=summary, description=description,
                         operationId=method + "_" + path.strip("/").replace("/", "_").replace("{", "").replace("}", ""))
        operation["security"] = [{"BearerAuth": []}]
        success = "202" if method in {"post", "delete"} else "200"
        operation["responses"][success] = {"description": "Orden aceptada: consultar operación" if success == "202" else "Consulta completada",
            "content": {"application/json": {"schema": ref(model), "example": example}}}
        if "200" in operation["responses"] and success == "202":
            operation["responses"]["200"]["content"] = {"application/json": {"schema": ref(model), "example": dict(example, status="succeeded", no_op=True)}}
        for status, code in error_codes.items():
            if method == "get" and status in {400, 413, 415, 409}:
                continue
            operation["responses"][str(status)] = {"description": code + ("; conflictos también incluyen PLAYBACK_BUSY, INVALID_STATE, PLAYBACK_CHANGED, PLAYBACK_BLOCKED, OPERATION_IN_PROGRESS e IDEMPOTENCY_CONFLICT" if status == 409 else ""),
                "content": {"application/json": {"schema": ref("ApiErrorBody"), "example": {"error": {"code": code, "message": code.replace("_", " ").lower(), "request_id": OP_ID}}}}}
        operation["responses"]["403"] = {"description": "Cloud Run IAM rechazó la identidad o su ID token. Puede responder HTML/texto antes de entrar a la aplicación."}
        for parameter in operation.get("parameters", []):
            name = parameter["name"]
            descriptions = {"bot_id": "UUID devuelto por POST /v1/bots.", "operation_id": "UUID devuelto al aceptar una orden.",
                "Idempotency-Key": "Obligatorio. Nueva clave por orden; conservarla para reintentar la misma orden/cuerpo. Ejemplo: UUID generado en PowerShell.",
                "cursor": "next_cursor de la página anterior, con el mismo filtro status.", "limit": "Máximo de elementos en esta página.",
                "status": "Filtra estado de sesión (no estado de reproducción).", "after_sequence": "Solo eventos con secuencia mayor; usar next_after_sequence anterior."}
            parameter["description"] = descriptions.get(name, parameter.get("description", ""))
            if name == "Idempotency-Key":
                parameter.update(required=True, example="swagger-test-20261014-001")
                parameter["schema"] = {"type": "string", "minLength": 16, "maxLength": 128, "pattern": "^[A-Za-z0-9_-]+$"}
    examples = {
        ("/v1/bots", "post"): {"entrar_sin_medios": {"summary": "Reemplazar por tu reunión", "value": {"meeting": {"number": "123456789", "password": "", "participant_name": "VideoBot-Prueba"}, "options": {"waiting_room_timeout_seconds": 180, "max_session_seconds": 600}}}},
        ("/v1/bots/{bot_id}/play", "post"): {
            "video": {"summary": "Video y audio", "value": {"media": {"type": "video", "url": BUCKET + "videos/015%20Lo%C3%A1moste%2C%20%C2%A1oh%20Dios!.mp4", "audio_enabled": True}}},
            "video_sin_audio": {"summary": "Solo video", "value": {"media": {"type": "video", "url": BUCKET + "videos/015%20Lo%C3%A1moste%2C%20%C2%A1oh%20Dios!.mp4", "audio_enabled": False}}},
            "audio": {"summary": "MP3, cámara apagada", "value": {"media": {"type": "audio", "url": BUCKET + "audios/Vientos%20susurrantes(6).mp3"}}},
            "imagen": {"summary": "Foto fija sin sonido por 120 s", "value": {"media": {"type": "image", "url": BUCKET + "images/IMG-20220410-WA0123.jpg", "duration_seconds": 120}}},
            "imagen_indefinida": {"summary": "Foto hasta stop o salida", "value": {"media": {"type": "image", "url": BUCKET + "images/IMG-20220410-WA0123.jpg"}}},
        },
    }
    for command in ("pause", "resume", "stop"):
        examples[("/v1/bots/{bot_id}/" + command, "post")] = {"intento_actual": {"value": {"playback_id": PLAY_ID}}, "sin_id": {"summary": "Controlar intento actual sin protección de ID", "value": {}}}
    for (path, method), values in examples.items():
        schema["paths"][path][method]["requestBody"]["content"]["application/json"]["examples"] = deepcopy(values)
    schema["paths"]["/health/ready"]["get"]["responses"]["503"] = {
        "description": "Heartbeat no listo, o comunicación con el agente no disponible.",
        "content": {"application/json": {"schema": {"oneOf": [ref("Readiness"), ref("ApiErrorBody")]},
            "example": {"status": "not_ready", "checks": {"database": "ok", "worker": "unavailable"}}}}
    }
    return schema
