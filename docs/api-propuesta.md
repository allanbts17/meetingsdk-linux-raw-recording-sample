# Propuesta de API del bot de Zoom

Estado al 2026-10-14: API FastAPI desplegada en Cloud Run y agente/SDK en `zoom-bot-vm`; video, audio e imagen comprobados por HTTP y otro participante. Una reunión simultánea; entrada de video hasta 1080p/30 FPS. Consumidor confirmado: servicio Cloud Run `api`, cuenta `722146628233-compute@developer.gserviceaccount.com`. Este contrato complementa [despliegue-propuesta.md](despliegue-propuesta.md).

Cloud Run valida IAM y usa un propietario fijo. La API no conserva estado duradero; envía órdenes al agente privado autenticado con otra credencial en Secret Manager. SQLite está en la VM, y el firewall restringe el agente al origen privado de Cloud Run. Swagger protegido está disponible mediante el proxy descrito en [probar-api.md](probar-api.md).

Retención de 30 días, pausa por causas externas y recuperación de red implementadas y comprobadas. Los campos de permisos/capacidades todavía no expuestos siguen siendo null. El audio puede recuperarse automáticamente si Zoom permite auto-unmute; detener cámara desde el anfitrión pausa ambas pistas y puede impedir reactivarla. La mejora de cámara independiente queda registrada para v2 en seguimiento. Stop idle/finished puede devolver 202 y completar después con no_op=true; no asumir HTTP 200 inmediato para todo no-op. Los eventos incluyen transiciones agregadas e IDs de reproducción; se paginan por sequence.

## 1. Alcance y componentes

- Python, FastAPI, Pydantic y Uvicorn para API y agente de control. SDK/FFmpeg permanecen en C++.
- Contenedor `api` en Cloud Run: HTTP, autenticación, validación y consulta/control del agente; sin estado local duradero.
- Contenedor `worker`: agente interno, descarga/validación del video, generación del JWT, proceso C++ y control estructurado de reproducción.
- Worker supervisado en la VM; el agente inicia el ejecutable dentro del worker, sin acceso al socket Docker desde la API.
- SQLite en un volumen persistente de la VM, administrado exclusivamente por el agente, para sesiones, operaciones, eventos e idempotencia. Transacciones reservan una sesión activa incluso con varias instancias de API.
- API pública con HTTPS run.app. Cloud Run usa Direct VPC egress hacia la IP interna de la VM; firewall restringido y autenticación del agente. No publicar el puerto del agente en Internet.

Acceso y costos detallados en [api-acceso-y-costos.md](api-acceso-y-costos.md): Cloud Run aporta URL y HTTPS sin dominio propio, Caddy ni balanceador adicional.

Primera versión: el bot entra y permanece en la reunión sin emitir medios. Otra petición selecciona el bot y un medio de tipo video, audio o imagen. Incluye pausa/reanudación, stop del medio y salida independiente de la reunión. Se admite un medio activo a la vez y medios sucesivos en el mismo bot después de detener/terminar el anterior. Seek, bucle, mezcla de varios medios simultáneos, reemplazo mientras está activo y múltiples bots quedan fuera de v1. El contrato incluirá los tres tipos desde el inicio; las pruebas prácticas comenzarán con videos.

La descarga, la reunión y la reproducción son trabajos administrados por el agente; una petición HTTP no permanece abierta durante ellos. No usar `BackgroundTasks` como único registro/ejecutor de sesiones de larga duración: el trabajo se registra duraderamente y el agente lo toma mediante una cola persistente y reconciliación.

## 2. Convenciones del contrato

| Elemento | Propuesta |
|---|---|
| URL base | `https://SERVICIO-ASIGNADO.run.app/v1` (ejemplo; URL real al desplegar) |
| Formato | JSON UTF-8; `Content-Type: application/json` en POST con cuerpo |
| Identificadores | UUID para `bot_id`, `operation_id` y `request_id` |
| Fechas | UTC, ISO 8601 terminadas en `Z` |
| Campos desconocidos | Rechazados con 422; no ignorarlos silenciosamente |
| Autenticación | `Authorization: Bearer ID_TOKEN` con audience de la URL del servicio Cloud Run |
| Peticiones mutables | `Idempotency-Key` obligatorio en POST de creación/control y DELETE |
| Correlación | `X-Request-ID` en respuestas; aceptar UUID del cliente o generar uno |
| Respuestas sensibles | `Cache-Control: no-store`; omitir secretos y cuerpos de peticiones en logs |
| Concurrencia | Una sesión ocupa capacidad desde su aceptación hasta que el agente confirme liberación |

El backend consumidor estará en Cloud Run/GCP. Usar la cuenta de servicio de ese backend con permiso roles/run.invoker sobre esta API, sin conceder invocación a allUsers. El backend obtiene un ID token cuya audience es la URL base del servicio Cloud Run; no usar un access token ni el JWT de Meeting SDK. Cloud Run comprueba la invocación antes de FastAPI. No se implementa login ni token estático público. El acceso API→agente privado usa una credencial distinta gestionada en Secret Manager. Falta identificar la cuenta de servicio concreta del backend para configurar IAM.

Todas las rutas funcionales y documentación requieren autenticación. `/health/live` se reserva a sondas del despliegue, con respuesta mínima y sin datos de sesiones. Si la API se consume directamente desde una aplicación web pública, sustituir el token de backend por autenticación de usuarios antes de publicar ese cliente; no distribuir el token de servidor en JavaScript.

## 3. Catálogo de endpoints

| Método | Ruta | Respuesta normal | Función |
|---|---|---|---|
| POST | `/v1/bots` | 202 | Reservar capacidad y solicitar entrada a la reunión, sin reproducir video. |
| GET | `/v1/bots` | 200 | Listar sesiones recientes, incluida la activa. |
| GET | `/v1/bots/{bot_id}` | 200 | Consultar reunión, reproducción, medio y error actual. |
| POST | `/v1/bots/{bot_id}/play` | 202 | Iniciar video, audio o imagen en un bot ya conectado. |
| POST | `/v1/bots/{bot_id}/pause` | 202; 200 si ya aplicada | Pausar conjuntamente ambas pistas. |
| POST | `/v1/bots/{bot_id}/resume` | 202; 200 si ya aplicada | Reanudar una pausa manual. |
| POST | `/v1/bots/{bot_id}/stop` | 202; consultar operación/no_op | Detener definitivamente el clip, manteniendo la reunión. |
| DELETE | `/v1/bots/{bot_id}` | 202; 200 si ya liberada | Cancelar preparación o salir de la reunión y liberar recursos. |
| GET | `/v1/operations/{operation_id}` | 200 | Consultar ejecución de una solicitud aceptada. |
| GET | `/v1/bots/{bot_id}/events` | 200 | Leer eventos ordenados del bot, con cursor. |
| GET | `/v1/capacity` | 200 | Consultar capacidad y disponibilidad para una nueva sesión. |
| GET | `/health/live` | 200 | Comprobar que el servidor HTTP responde. |
| GET | `/health/ready` | 200 o 503 | Comprobar base de datos, comunicación y salud del agente. |
| GET | `/openapi.json` | 200 | Contrato OpenAPI autenticado. |
| GET | `/docs` | 200 | Swagger UI autenticada. |

Sondeo recomendado: alternar operación/estado cada 2–3 segundos mientras cambia; cada 5 segundos en estados estables. El límite de 60 consultas/minuto se comparte entre todas las rutas del propietario. Los eventos son consultas HTTP normales; SSE/WebSocket y webhooks quedan para una ampliación posterior.

## 4. Crear una sesión: POST /v1/bots

### Petición

```http
POST /v1/bots
Authorization: Bearer ID_TOKEN
Idempotency-Key: 77bd482c-366d-4a98-a8d6-e671aa0d4031
Content-Type: application/json
```

```json
{
  "meeting": {
    "number": "12345678901",
    "password": "CONTRASENA_DE_EJEMPLO",
    "participant_name": "VideoBot"
  },
  "options": {
    "waiting_room_timeout_seconds": 900,
    "max_session_seconds": 5400
  }
}
```

Todos los datos son ilustrativos; no son credenciales reales.

| Campo | Regla / valor por defecto |
|---|---|
| `meeting.number` | Obligatorio, texto de 9–11 dígitos, sin espacios/guiones y no todo ceros. |
| `meeting.password` | Texto, opcional, vacío por defecto; máximo propuesto 128 caracteres, sin saltos de línea. Nunca se devuelve. |
| `meeting.participant_name` | Texto no vacío, 1–64 caracteres, sin controles; por defecto `VideoBot`. |
| `options.waiting_room_timeout_seconds` | Por defecto 900; rango propuesto 30–1800. Cuenta mientras espera anfitrión/admisión. |
| `options.max_session_seconds` | Por defecto 5400; rango propuesto 60–5400. Límite total desde aceptación, incluyendo preparación y espera. |

No aceptar `client_id`, `client_secret`, JWT de Zoom, comandos FFmpeg, rutas del sistema ni nombres de contenedor en la petición. Las credenciales de Meeting SDK se obtienen internamente de Secret Manager.

### Respuesta 202

```json
{
  "bot_id": "11223344-5566-4788-99aa-bbccddeeff00",
  "operation_id": "aabbccdd-1122-4334-8556-77889900aabb",
  "status": "accepted",
  "links": {
    "bot": "/v1/bots/11223344-5566-4788-99aa-bbccddeeff00",
    "operation": "/v1/operations/aabbccdd-1122-4334-8556-77889900aabb"
  }
}
```

Headers: `Location` apunta al bot y `Retry-After: 1`. La transacción reserva la capacidad, crea sesión/operación y persiste el trabajo antes de responder.

Flujo del agente: preparar configuración/JWT → iniciar C++ con medios apagados → autenticar → entrar/admisión. La operación de creación termina con éxito cuando Zoom confirma entrada efectiva. El bot queda `active` y la reproducción `idle`, con cámara/micrófono apagados. No necesita URL, archivo de video ni descarga para entrar. La reproducción comienza exclusivamente mediante `/play`.

Si ya existe una sesión reservada, descargando, esperando, conectada o liberándose: `409 CAPACITY_EXCEEDED`. Un reintento idempotente de la misma creación recupera la solicitud original y no consume otra capacidad.

Errores de formato de la petición son inmediatos (422). Fallos de autenticación/entrada posteriores al 202 se consultan en operación/bot. Los errores de medio pertenecen a la operación `/play`, no a la creación del bot.

## 4.1. Presentar un medio: POST /v1/bots/{bot_id}/play

Requiere bot `active`, reproducción `idle`, `stopped`, `finished` o `failed`, ninguna operación incompatible pendiente y `Idempotency-Key`. No disponible en espera de admisión, reconexión o salida. Si otro clip está buffering/playing/paused, responder 409 `PLAYBACK_BUSY`; detenerlo explícitamente antes de solicitar otro.

```json
{
  "media": {
    "type": "video",
    "url": "https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/videos/demo.mp4",
    "audio_enabled": true
  }
}
```

`media.type` es obligatorio: `video`, `audio` o `image`. `media.url` es obligatorio en los tres casos: HTTPS al host/bucket permitido, máximo propuesto 2048 caracteres, sin rutas locales ni `gs://`. Validar con un esquema discriminado según type. No aceptar `leave_on_finish`: terminar un medio no hace salir al bot.

| Tipo | Campos específicos | Emisión en Zoom | Fin / pausa |
|---|---|---|---|
| `video` | `audio_enabled`, booleano, por defecto true | Cámara virtual; micrófono si está habilitado | Una reproducción hasta EOF. Pausa congela imagen y audio. |
| `audio` | Sin campos adicionales | Solo micrófono; cámara del bot apagada | Una reproducción hasta EOF. Pausa silencia y conserva posición. |
| `image` | `duration_seconds`, entero positivo opcional o null | Imagen estática por cámara virtual; micrófono apagado | null: permanece hasta stop. Valor: termina tras ese tiempo de presentación activa. Pausa conserva imagen y congela el tiempo. |

Para audio, `audio_enabled` se rechaza por ambiguo: ese tipo siempre emite audio. Para imagen, `audio_enabled` se rechaza y duration_seconds puede estar entre 1 y 3600, limitada también por el tiempo restante de sesión. Para video/audio se rechaza duration_seconds: manda la duración del archivo. Una imagen sin duración sigue sujeta al límite de sesión.

Ejemplo de audio:

```json
{"media":{"type":"audio","url":"https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/audios/demo.mp3"}}
```

Ejemplo de imagen permanente hasta stop:

```json
{"media":{"type":"image","url":"https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/imagenes/demo.png","duration_seconds":null}}
```

Estos prefijos son ilustrativos; permitir objetos del bucket autorizado, no solo la carpeta videos. En la imagen se preserva proporción con márgenes y se mantiene emisión de cuadros estáticos según las capacidades del SDK. Los cambios de tipo desactivan las pistas anteriores: audio no deja una cámara de video anterior activa, e imagen no deja un micrófono de audio anterior activo.

Respuesta 202:

```json
{
  "bot_id": "11223344-5566-4788-99aa-bbccddeeff00",
  "playback_id": "99887766-5544-4322-aabb-001122334455",
  "operation_id": "aabbccdd-1122-4334-8556-77889900aabb",
  "action": "play",
  "status": "queued",
  "links": {
    "bot": "/v1/bots/11223344-5566-4788-99aa-bbccddeeff00",
    "operation": "/v1/operations/aabbccdd-1122-4334-8556-77889900aabb"
  }
}
```

La operación reserva la reproducción (no otra reunión), descarga/valida el archivo, crea reloj/fuentes apropiados y activa únicamente las pistas requeridas por type. Durante descarga el bot sigue conectado y playback está `buffering`. Se completa al confirmar los primeros envíos requeridos: video y audio habilitado, audio solo, o primer cuadro de imagen. `playback_id` identifica ese intento y se conserva en operaciones/eventos.

Si descarga/validación falla, la operación y reproducción quedan failed; el bot permanece `active`, sin emitir ese medio, y admite otro `/play` después de limpiar temporales. No reconectar ni abandonar la reunión por un error del archivo.

Después de EOF de video/audio o de agotar la duración de una imagen, playback `finished`; después de stop, `stopped`. En ambos casos el bot permanece conectado. Una imagen sin duración continúa hasta stop o cierre de sesión. Un nuevo `/play`, incluso con la misma URL y una nueva clave de idempotencia, crea otra presentación desde cero. Repetir la misma clave solo recupera el intento original.

Las órdenes pause/resume/stop se aplican al playback actual. Admiten un cuerpo opcional `{"playback_id":"UUID"}` para comprobar que el cliente controla el intento esperado; si cambió, responder 409 `PLAYBACK_CHANGED`. Para automatizaciones se recomienda enviarlo siempre, evitando que una orden atrasada controle un video posterior.

## 5. Consultar sesión: GET /v1/bots/{bot_id}

```json
{
  "bot_id": "11223344-5566-4788-99aa-bbccddeeff00",
  "status": "active",
  "meeting": {
    "number": "12345678901",
    "participant_name": "VideoBot",
    "status": "in_meeting",
    "audio_permission": "allowed",
    "video_permission": "allowed"
  },
  "playback": {
    "media_type": "video",
    "playback_id": "99887766-5544-4322-aabb-001122334455",
    "status": "playing",
    "position_seconds": 28.4,
    "duration_seconds": 109.018,
    "audio_enabled": true,
    "pause_reasons": [],
    "can_pause": true,
    "can_resume": false,
    "can_stop": true
  },
  "media": {
    "download_status": "ready",
    "downloaded_bytes": 4004494,
    "total_bytes": 4004494,
    "source": {"width": 640, "height": 480, "fps": 29.01},
    "output": {"width": 640, "height": 480, "fps": 25, "audio_sample_rate": 48000, "audio_channels": 1}
  },
  "pending_operation_id": null,
  "resource_released": false,
  "state_version": 17,
  "created_at": "2026-10-13T19:00:00Z",
  "updated_at": "2026-10-13T19:00:28Z",
  "last_error": null
}
```

`position_seconds` es la posición de reproducción del reloj compartido, congelada durante pausa/stop y limitada a la duración al finalizar. No es una medición de sincronía observada por otro cliente Zoom. Las métricas desconocidas se devuelven como null; `total_bytes` puede ser null mientras descarga.

Para imagen, position_seconds representa tiempo de presentación activa; duration_seconds es null si no tiene límite propio. En audio, `media.source`/`output` contienen información de audio y campos de video null; en imagen contienen información de imagen/video y campos de audio null. Pistas ausentes/desactivadas no bloquean preparación ni generan motivos de pausa.

No devolver password, JWT, secretos, rutas de disco ni URL completa del medio. Puede identificarse el medio mediante un `media_id`/hash interno. `output` muestra capacidades realmente negociadas: entrada 1080p no implica emisión 1080p. `state_version` aumenta con cada transición y ayuda a distinguir estados viejos; no garantiza por sí sola orden de comandos.

Bot desconocido o eliminado por retención: 404. Un bot terminado conserva su registro y devuelve 200 hasta vencer la retención.

## 6. Estados y capacidad

### Ciclo de vida del bot

| `status` | Significado |
|---|---|
| `accepted` | Trabajo persistido y capacidad reservada. |
| `preparing` | Preparando credenciales y proceso de entrada, sin descargar medios. |
| `joining` | SDK autenticando/conectando. |
| `waiting_room` | Esperando anfitrión o admisión. |
| `active` | Participante en la reunión; reproducción puede estar playing/paused/stopped/finished. |
| `reconnecting` | Se perdió conexión, se conserva la reserva y se pausa reproducción. |
| `leaving` | Cancelación/salida y liberación en curso. |
| `ended` | Salida confirmada y recursos liberados. |
| `failed` | Fallo registrado; puede estar completando limpieza. Consultar `resource_released`. |

### Estado de reproducción

`idle`, `buffering`, `playing`, `paused`, `stopped`, `finished`, `failed`. `idle` significa conectado sin haber solicitado un video: playback_id, posición y duración son null; `media` es null y can_pause/can_resume/can_stop son false.

Ejemplos: `active + idle`, `active + buffering`, `active + paused`, `active + stopped`, `active + finished`. Todos siguen ocupando la única capacidad hasta salir. Durante preparación/entrada, reproducción `idle`. Descargar un video posteriormente no cambia el estado de reunión a preparing.

`pause_reasons` distingue `user`, `host_audio_muted`, `host_video_disabled`, `network_reconnecting` y `sdk_not_ready`. La política propuesta para eventos externos es pausar ambas pistas si alguna pista requerida deja de estar disponible, conservar la posición y no contrarrestar decisiones del anfitrión. Al recuperarse la disponibilidad, retirar ese motivo; reanudar solo si no quedan otros motivos. Una pausa manual permanece hasta `resume`.

La política actual se verificó con mute permitido, cámara detenida por el anfitrión y un corte de red de 30 segundos; las limitaciones de cámara están registradas en seguimiento. Si termina la reunión, marcar `ended` y liberar; si vence un timeout de reconexión o se agota recuperación, marcar `failed` y limpiar.

## 7. Pausar: POST /v1/bots/{bot_id}/pause

Cuerpo opcional con `playback_id`; requiere `Idempotency-Key`.

- Disponible en bot `active`, reproducción `playing` o `paused`.
- Añade motivo `user`; pausa ambos emisores y congela el reloj.
- Si ya existe pausa manual, devolver 200 con operación completada `no_op=true`.
- Si estaba pausado por el anfitrión, registrar también la intención de pausa manual; no se reanudará al recuperarse permisos.
- Bot preparando/entrando/saliendo/terminado, o reproducción idle/buffering/stopped/finished/failed: 409 `INVALID_STATE`.

### Respuesta de control

```json
{
  "operation_id": "aabbccdd-1122-4334-8556-77889900aabb",
  "bot_id": "11223344-5566-4788-99aa-bbccddeeff00",
  "action": "pause",
  "status": "queued",
  "no_op": false,
  "links": {"operation": "/v1/operations/aabbccdd-1122-4334-8556-77889900aabb"}
}
```

202 significa orden persistida/aceptada. La operación pasa a succeeded después del ACK del proceso C++ y de comprobar el estado aplicado. En un no-op, devolver 200 con el mismo esquema y `status=succeeded`. Se conserva una operación también para no-ops nuevos, para mantener trazabilidad.

## 8. Reanudar: POST /v1/bots/{bot_id}/resume

Cuerpo opcional con `playback_id`; mismo esquema de control e idempotencia.

- Disponible en bot `active` y playback `paused` por `user`.
- Retira motivo `user` y reajusta la base temporal de ambas pistas para continuar desde el punto pausado.
- Si existen motivos externos que impiden emisión, devolver 409 `PLAYBACK_BLOCKED`, sin retirar la pausa manual. El cliente puede consultar los motivos y esperar.
- Si ya está playing: 200 con no-op. No empezar desde cero.
- idle/buffering/stopped/finished/failed o bot no active: 409 `INVALID_STATE`.
- Bot reconnecting: 409 `PLAYBACK_BLOCKED`.

Después de stop/finish, iniciar otro intento mediante `/play` en el mismo bot. `resume` continúa una pausa; nunca reinicia un clip terminado/detenido.

## 9. Detener: POST /v1/bots/{bot_id}/stop

Cuerpo opcional con `playback_id`; mismo esquema de control e idempotencia.

- Disponible en bot `active` o `reconnecting`, con playback buffering/playing/paused; si está buffering, cancela descarga/preparación del intento y libera sus temporales.
- Detención definitiva: bloquea nuevos envíos, libera ambos decodificadores y conserva al participante conectado si la reunión continúa.
- No modifica ni anula restricciones del anfitrión. La última imagen puede permanecer visible.
- Si ya está idle/stopped/finished, stop puede responder 202 y completar la operación con no_op=true; finished se conserva sin convertirlo en stopped. Un playback failed admite limpieza si queda alguna tarea o recurso pendiente.
- En preparing/joining/waiting_room, devolver 409 `INVALID_STATE`; para cancelar la sesión usar DELETE.
- Una operación stop completada implica que no quedan decodificadores/emisiones del clip, no solo que se escribió una orden a la FIFO.

## 10. Salir/cancelar: DELETE /v1/bots/{bot_id}

Sin cuerpo; `Idempotency-Key` obligatorio.

- Válido en cualquier fase de una sesión conocida.
- accepted/preparing: cancelar entrada y borrar configuración temporal.
- joining/waiting_room/active/reconnecting: cancelar descarga de medios si existe, detener reproducción, solicitar salida, esperar cierre y liberar proceso/configuración/caché.
- leaving: devolver referencia a la operación leave que ya está en curso, sin crear otra salida.
- ended o failed con `resource_released=true`: 200 no-op.
- failed con recursos aún presentes: aceptar la operación de limpieza.

Respuesta 202 con operación `action=leave`. La capacidad no se libera hasta confirmar cierre y `resource_released=true`. Si la salida normal excede su plazo, el agente termina el grupo de procesos de la sesión, comprueba que desapareció y registra salida forzada. Nunca mata al servidor API ni al propio agente para terminar una sesión.

DELETE cierra la sesión operativa; no borra inmediatamente su historial. `GET` sigue disponible hasta la retención configurada. El cliente no necesita esperar al fin del clip para salir.

## 11. Consultar operaciones: GET /v1/operations/{operation_id}

```json
{
  "operation_id": "aabbccdd-1122-4334-8556-77889900aabb",
  "bot_id": "11223344-5566-4788-99aa-bbccddeeff00",
  "action": "pause",
  "status": "succeeded",
  "no_op": false,
  "requested_at": "2026-10-13T19:00:30Z",
  "completed_at": "2026-10-13T19:00:30.150Z",
  "result": {"playback_id": "99887766-5544-4322-aabb-001122334455", "playback_status": "paused", "position_seconds": 28.4},
  "error": null
}
```

Estados: `queued`, `running`, `succeeded`, `failed`, `cancelled`. `completed_at` y `result` son null mientras no haya resultado.

Las órdenes se serializan por bot. Aceptar como máximo una operación mutable pendiente por sesión; peticiones adicionales devuelven 409 `OPERATION_IN_PROGRESS`, salvo reintentos idempotentes, DELETE y stop de un play pendiente. DELETE tiene prioridad, cancela creación/descarga/controles que todavía no se aplicaron y pide salida. stop puede cancelar un play en buffering y liberar solo esa reproducción. Las operaciones en curso pueden quedar cancelled o succeeded según el ACK real; no afirmar que se deshizo una orden ya aplicada. Capturar `playback_id` al aceptar cada control; una orden de un intento anterior nunca se aplica a uno nuevo.

Si un control vence sin ACK, registrar `COMMAND_TIMEOUT`, reconciliar el estado y no repetirlo a ciegas. Durante reconciliación devolver 503 a nuevas órdenes, salvo leave/consulta. La operación fallida puede haber producido un efecto; `GET bot` reconciliado es la fuente del estado final.

## 12. Listado e historial

### GET /v1/bots

Query: `limit` (por defecto 20, máximo 100), `cursor` opaco opcional, `status` opcional según el enum de ciclo de vida.

```json
{
  "items": [
    {"bot_id": "11223344-5566-4788-99aa-bbccddeeff00", "status": "active", "playback_status": "paused", "created_at": "2026-10-13T19:00:00Z"}
  ],
  "next_cursor": null
}
```

Orden estable de más reciente a más antiguo, usando fecha e ID; el cursor conserva filtros. Cursor inválido: 422. No incluir secretos ni cuerpos de creación.

### GET /v1/bots/{bot_id}/events

Query: `after_sequence` (por defecto 0), `limit` (por defecto 50, máximo 200). Secuencia creciente por bot.

```json
{
  "items": [
    {"sequence": 18, "type": "playback.paused", "occurred_at": "2026-10-13T19:00:30Z", "data": {"position_seconds": 28.4, "reason": "user"}}
  ],
  "next_after_sequence": 18,
  "has_more": false
}
```

Sin eventos nuevos: `items=[]` y el cursor no cambia. Tipos propuestos: `bot.accepted`, `media.download_started`, `media.ready`, `meeting.joining`, `meeting.waiting_room`, `meeting.joined`, `meeting.reconnecting`, `playback.started`, `playback.paused`, `playback.resumed`, `playback.stopped`, `playback.finished`, `playback.failed`, `bot.leaving`, `bot.ended`, `bot.failed`, `operation.failed`. Eventos de medios/reproducción incluyen `playback_id` para distinguir videos sucesivos.

Publicar cambios/progreso agregados; no emitir un evento por cuadro/bloque. Nunca publicar trazas internas, passwords, URLs con query ni tokens.

## 13. Capacidad y salud

### GET /v1/capacity

```json
{
  "max_concurrent_bots": 1,
  "reserved_slots": 1,
  "available_slots": 0,
  "active_bot_id": "11223344-5566-4788-99aa-bbccddeeff00",
  "accepting_new_sessions": false,
  "worker_status": "healthy"
}
```

Una VM/worker ocupado no es un fallo de salud. Una sesión failed sigue reservando capacidad hasta confirmar limpieza. Si el agente no responde o su estado es desconocido, `accepting_new_sessions=false`; no liberar el slot por asumir que expiró un heartbeat.

### GET /health/live

200: `{"status":"ok"}`. Respuesta mínima para la sonda; no depende de que el bot esté libre.

### GET /health/ready

Autenticado. 200 si base de datos accesible, agente responde, versiones IPC compatibles y reconciliación completa. 503 si falta alguna condición; responder `{"status":"not_ready","checks":{"database":"ok","worker":"unavailable"}}` sin datos internos sensibles. Estar ocupado produce 200; falta de capacidad se consulta aparte.

## 14. Idempotencia y errores

`Idempotency-Key`: texto 16–128 caracteres, alfanuméricos/guion/guion bajo. Alcance por cliente y ruta/método. Persistir fingerprint del cuerpo normalizado, IDs creados y respuesta original antes de ejecutarlo.

- Misma clave y mismo contenido: devolver la respuesta original, con `Idempotency-Replayed: true`; consultar operación/bot para estado actual.
- Misma clave con contenido distinto: 409 `IDEMPOTENCY_CONFLICT`.
- Retener claves al menos 24 horas y mientras la operación/sesión sigan activas. Después de retención, una clave antigua puede representar una petición nueva; el cliente debe conservar IDs y generar claves nuevas para acciones nuevas.
- La exclusión del slot es transaccional y también verificada por el agente; no depende de comprobar primero `/capacity`.

Formato uniforme de error:

```json
{
  "error": {
    "code": "INVALID_STATE",
    "message": "El clip está detenido y no puede reanudarse.",
    "request_id": "7a702d21-0e7c-4a23-bb09-82e882318f78",
    "details": {"current_playback_status": "stopped"}
  }
}
```

| HTTP | Códigos / significado |
|---|---|
| 400 | `IDEMPOTENCY_KEY_REQUIRED`, JSON mal formado. |
| 401 | `UNAUTHORIZED`, token ausente/incorrecto; incluir `WWW-Authenticate: Bearer`. |
| 403 | `FORBIDDEN`, cliente autenticado sin permiso o fuente no permitida. |
| 404 | `BOT_NOT_FOUND`, `OPERATION_NOT_FOUND`. |
| 409 | `CAPACITY_EXCEEDED`, `INVALID_STATE`, `PLAYBACK_BUSY`, `PLAYBACK_CHANGED`, `PLAYBACK_BLOCKED`, `OPERATION_IN_PROGRESS`, `IDEMPOTENCY_CONFLICT`. |
| 415 | `UNSUPPORTED_CONTENT_TYPE`, cuerpo distinto a JSON cuando se requiere. |
| 422 | `VALIDATION_ERROR`, campo/rango/cursor/URL inválidos. |
| 429 | `RATE_LIMITED`, incluir `Retry-After`. |
| 503 | `WORKER_UNAVAILABLE`, `STATE_RECONCILING`, `NOT_READY`. |
| 500 | `INTERNAL_ERROR`, mensaje genérico y correlación en logs. |

Errores asíncronos en `operation.error` / `bot.last_error`: `MEDIA_NOT_FOUND`, `MEDIA_DOWNLOAD_FAILED`, `MEDIA_TOO_LARGE`, `MEDIA_INVALID`, `MEDIA_TRACK_MISSING`, `MEDIA_LIMIT_EXCEEDED`, `MEDIA_TYPE_UNSUPPORTED`, `ZOOM_AUTH_FAILED`, `MEETING_PASSWORD_INVALID`, `MEETING_NOT_FOUND`, `WAITING_ROOM_TIMEOUT`, `MEETING_PERMISSION_DENIED`, `CONNECTION_LOST`, `COMMAND_TIMEOUT`, `SESSION_TIMEOUT`, `WORKER_RESTARTED`, `PROCESS_EXITED`.

Los errores de validación indican nombres de campos y mensajes; no incluir el valor recibido. Traducir códigos SDK a mensajes y conservar un `sdk_code` numérico cuando sea útil, sin devolver logs sin filtrar. Un fallo posterior al 202 se consulta como recurso con HTTP 200 y `status=failed`.

## 15. Descarga, límites y secretos

Límites operativos de v1 comprobados mediante pruebas de validación, tiempos y carga HTTP acotada. El ensayo prolongado de entrada 1080p está documentado en [benchmark-1080p.md](benchmark-1080p.md); la salida negociada fue 640x480/25 FPS:

| Límite | Valor actual |
|---|---|
| Fuente permitida | `https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/...` |
| Archivo video | MP4, H.264 y audio AAC cuando audio esté habilitado; puede ampliarse tras pruebas. |
| Archivo audio | MP3, WAV PCM o M4A/AAC, validado por decodificación y convertido a PCM del SDK. |
| Archivo imagen | PNG o JPEG estático; validar dimensiones/decodificación. SVG, GIF animado y otros formatos quedan fuera de v1. |
| Resolución de entrada | Video: hasta 1920×1080 en orientación de reproducción. Imagen: hasta 4096 por lado y 16 megapíxeles; se adapta al tamaño de cámara negociado. Considerar rotación al validar. |
| FPS de entrada | Hasta 30 FPS; 60 FPS fuera de v1. |
| Tamaño | 1 GiB por video/audio; 10 MiB por imagen. |
| Duración | Hasta 3600 s, además del límite de sesión elegido. |
| Descarga | Conexión 10 s; sin recibir datos 30 s; total 300 s. |
| Reconexión Zoom | Máximo 120 s por incidente. |
| ACK de controles | 5 s; salida normal 20 s antes de limpieza forzada. |
| Capacidad de caché | Máximo 2 GiB; eliminar temporales al terminar/cancelar/fallar. |
| Reserva de disco | Mantener al menos 5 GiB libres antes/durante descarga. |
| Retención | Historial/eventos/operaciones terminados durante 30 días. |
| Rate limit | 60 peticiones/minuto por cliente; mutaciones 10/minuto, ráfaga 5. |

Son defaults de diseño, no capacidades ya medidas ni condiciones impuestas por Zoom.

Aceptar exclusivamente destinos/bucket configurados, limitar redirecciones a los mismos destinos permitidos, no permitir IPs privadas/metadata ni credenciales embebidas en URL. Descargar por bloques a `.part`, contar bytes aunque falte Content-Length y limpiar ante cualquier fallo. Comprobar checksum cuando Storage lo facilite, validar con FFprobe y renombrar de forma atómica antes de usarlo. Evitar dos descargas del mismo objeto; dentro de una sesión, ambos decodificadores leen la misma copia local.

Credenciales de Meeting SDK en Secret Manager, accesibles por el agente con la identidad de la VM. JWT fresco antes de entrar, configuración temporal con acceso restringido y eliminación tras cierre. La API mantiene password de reunión únicamente mientras sea necesario para entregarlo al agente: si se persiste en un trabajo pendiente, cifrar el payload con una clave separada gestionada en Secret Manager; purgarlo al iniciar/finalizar/cancelar. Ni clave API ni JWT de Zoom ni passwords aparecen en respuestas, logs, eventos o historial. Desactivar logs de cuerpos y redactar valores en validaciones.

La URL completa se conserva solo el tiempo necesario para descargar, sin registrarla en logs; el historial mantiene referencia saneada o hash. URLs públicas actuales no requieren credenciales de Storage. Si se admiten enlaces firmados después, tratar su query como secreto.

## 16. Agente interno e IPC del SDK

El agente ofrece un protocolo privado autenticado para tomar trabajos, ejecutar controles, reportar resultados y reconciliar. Estas rutas no forman parte de la API pública. Usar `bot_id`, `operation_id` y versión de protocolo en cada intercambio.

Ampliar la FIFO actual o reemplazarla por Unix socket con mensajes JSON enmarcados. El proceso C++ devuelve ACK con ID de operación/playback, estado y posición aplicados; emite eventos de reunión y capacidades. Consultas de estado estructuradas sustituyen el parseo de logs. En control, `stop` debe confirmar threads/FFmpeg liberados antes de ACK; `leave` requiere cierre del proceso o evento final seguido de limpieza.

La sesión SDK se inicializa una vez al entrar. play posterior registra/activa fuentes en esa sesión; cada intento nuevo reinicia reloj, contadores y estado de fin/detención. Se liberan las fuentes previas en orden seguro para callbacks antes de sustituirlas. No reiniciar el ejecutable ni usar salir/reentrar como sustituto de play. Esta capacidad dinámica requiere adaptar el código actual, que hasta ahora usa archivo/flags al arrancar.

El worker selecciona reproductor por tipo: video utiliza las dos pistas requeridas y reloj compartido; audio utiliza solo decodificador PCM; imagen decodifica una vez y mantiene cuadros por cámara virtual. Ninguno espera una pista que no corresponde a su tipo. Las capacidades del proceso se publican para que el agente falle con `MEDIA_TYPE_UNSUPPORTED` si un despliegue no implementa aún el tipo solicitado, sin simular éxito.

El agente crea una sesión aislada, administra su grupo de procesos y recoge exit codes. Publica heartbeat cada 5 s; después de 15 s sin heartbeat, API declara estado desconocido/servicio no preparado y bloquea nuevas creaciones. No libera capacidad ni inicia otra sesión hasta reconciliar.

Reinicio de API: consultar al agente; SQLite permanece en la VM y no se monta en Cloud Run. Escalar a cero o reemplazar instancias de API no detiene el bot. Antes de responder 202, el agente debe confirmar la transacción duradera; ante timeout, consultar/reintentar con la misma clave de idempotencia. Si el agente no está disponible, devolver 503 y no inventar aceptación ni capacidad libre. Reinicio de worker/VM: marcar sesión interrumpida `failed` con `WORKER_RESTARTED`, cancelar operaciones y liberar solo después de comprobar que la sesión anterior ya no existe. No volver a entrar automáticamente a Zoom. La sesión nueva requiere una nueva petición del cliente.

## 17. Ejemplo de flujo del cliente

1. Consultar `/v1/capacity`; sirve como información, no como reserva.
2. Crear bot con una clave de idempotencia única y guardar ambos IDs.
3. Consultar operación hasta éxito/fallo; consultar bot si está esperando admisión.
4. Verificar bot active y playback idle. Puede permanecer así sin compartir nada.
5. Cuando corresponda, solicitar `/play` en ese bot con URL, nueva clave y guardar playback_id/operation_id. Esperar primeros envíos mediante consulta de operación.
6. Solicitar pause/resume/stop con playback_id y nuevas claves; verificar resultados sin desconexión.
7. Tras stop/finish, solicitar otro `/play` en el mismo bot si se quiere otro video. No crea otra reunión.
8. Solo cuando se quiera salir, usar DELETE y esperar `resource_released=true`.
9. Crear otra sesión de reunión únicamente cuando el servicio vuelva a admitir capacidad.

## 18. Criterios de aceptación y decisiones restantes

- Creación concurrente nunca produce dos sesiones activas.
- Reintentos HTTP no duplican bots ni órdenes.
- Una aceptación 202 es recuperable tras reinicio y no se confunde con ejecución.
- Crear bot no descarga ni reproduce medios; entra con cámara/micrófono apagados y permanece conectado.
- play inicia video/audio/imagen en el bot seleccionado; medios sucesivos no provocan salir/reentrar a Zoom. Las primeras pruebas reales se centran en video.
- pause/resume/stop/leave cumplen los controles ya confirmados en Zoom.
- Mute/video off pausan temporalmente ambas pistas y el bot intenta reactivarlas mediante las APIs permitidas por Zoom. Si Zoom niega el permiso, conserva el bloqueo y limita los reintentos. Recuperar disponibilidad no elimina una pausa manual. Reconexión pausa ambas pistas.
- Invalidar medio impide emitirlo y mantiene al bot conectado. stop/fallo del medio liberan recursos de reproducción; solo leave/fin de reunión/fallo de sesión liberan capacidad de reunión.
- JWT/password/API key no aparecen en interfaces persistentes ni logs.
- Tests incluyen API, agente, IPC, reinicios, concurrencia, idempotencia y validación de URL.
- Prueba prolongada 1080p/30 FPS de diez minutos en GCE con muestra sintética autorizada, cuadros omitidos estimados y sincronía confirmada; resultados y límites de extrapolación en benchmark-1080p.md.

Confirmado: consumidor, cuenta de servicio, IAM Invoker, URL HTTPS run.app, despliegue y controles independientes. Ensayo prolongado de entrada 1080p/30 FPS y dimensionamiento completados con muestra sintética autorizada; se conservan los recursos actuales. Varias instancias desplegadas solo requieren validación adicional si se aumenta el máximo actual de una. El usuario configura su backend consumidor.

## Referencias de implementación

- [FastAPI: seguridad y HTTP Bearer/OpenAPI](https://fastapi.tiangolo.com/tutorial/security/)
- [Cloud Run: autenticación entre servicios con IAM e ID token](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)
- [FastAPI: tareas en segundo plano y sus límites](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [FastAPI: despliegue en contenedores](https://fastapi.tiangolo.com/deployment/docker/)
- [Cloud Storage: descarga de objetos](https://docs.cloud.google.com/storage/docs/downloading-objects)
- [Secret Manager: acceso a una versión de secreto](https://docs.cloud.google.com/secret-manager/docs/access-secret-version)
