# Ver Swagger y probar la API

La API está en `https://zoom-bot-api-722146628233.us-central1.run.app`. Está protegida por IAM; abrir `/docs` directamente sin ID token puede devolver 403. Para usar Swagger desde tu PC se utiliza el proxy oficial de gcloud. No necesitas dominio ni desplegar tu backend para esta prueba.

## Abrir Swagger

En PowerShell, desde la raíz del repositorio:

```powershell
./scripts/open-swagger.ps1
```

Deja esa consola abierta y entra a [Swagger local](http://localhost:8085/docs). El componente `cloud-run-proxy` de gcloud ya está instalado en este equipo. Si cambias de equipo, gcloud puede pedir instalarlo. Tu cuenta activa debe tener permiso para invocar el servicio; `gcloud auth login` permite cambiar/iniciar la sesión si hace falta.

El proxy añade tu autenticación a todas las peticiones. No tienes que llenar **Authorize** en Swagger local. El ID token no se entrega al navegador. No abras el proxy a otros equipos: es para uso local. Para detenerlo usa Ctrl+C en la consola. Si el puerto está ocupado, usa `./scripts/open-swagger.ps1 -Port 8086` y abre `http://localhost:8086/docs`.

**Try it out ejecuta órdenes reales** en la VM y en Zoom. Inicia primero tu reunión y ten a mano número y contraseña. La documentación contiene datos ficticios para la reunión; sustitúyelos por los tuyos. Nunca pongas Client Secret/JWT del SDK en estas peticiones: el agente los obtiene de Secret Manager.

## Lista de endpoints

| Método | Ruta | Uso |
|---|---|---|
| GET | `/health/live` | Proceso HTTP vivo; no comprueba al agente. |
| GET | `/health/ready` | Heartbeat y disponibilidad del agente. |
| GET | `/v1/capacity` | Plaza disponible y bot que la reserva. |
| POST | `/v1/bots` | Entrar a Zoom sin reproducir medios. |
| GET | `/v1/bots` | Listar bots e historial; filtros y cursor. |
| GET | `/v1/bots/{bot_id}` | Estado de reunión, reproducción y limpieza. |
| DELETE | `/v1/bots/{bot_id}` | Cancelar trabajos, salir y liberar plaza. |
| POST | `/v1/bots/{bot_id}/play` | Iniciar video, audio o imagen. |
| POST | `/v1/bots/{bot_id}/pause` | Pausa coordinada del medio. |
| POST | `/v1/bots/{bot_id}/resume` | Continuar desde pausa, si no hay bloqueo externo. |
| POST | `/v1/bots/{bot_id}/stop` | Detener el medio manteniendo al bot conectado. |
| GET | `/v1/operations/{operation_id}` | Consultar el resultado de una orden. |
| GET | `/v1/bots/{bot_id}/events` | Consultar eventos por secuencia. |

`GET /docs` muestra Swagger; `GET /openapi.json` entrega el contrato OpenAPI, también a través del proxy. Allí están descritos parámetros, cuerpos por tipo de medio, respuestas, estados y errores.

## Secuencia de prueba en Swagger

1. Abre **Capacidad → GET /v1/capacity → Try it out → Execute**. Espera `available_slots: 1`, `accepting_new_sessions: true` y `worker_status: healthy`. Si hay un bot activo, consulta su estado antes de decidir salirlo.
2. Abre **Bots → POST /v1/bots → Try it out**. Completa `Idempotency-Key` con una clave nueva. Puedes generar un UUID en otra consola:

   ```powershell
   [guid]::NewGuid().ToString()
   ```

   Selecciona el ejemplo de entrada y reemplaza número (sin espacios), contraseña y nombre. `max_session_seconds: 600` limita esta prueba a diez minutos desde su aceptación. La entrada no activa medios.
3. Pulsa Execute. La respuesta 202 contiene `bot_id` y `operation_id`. **202 no significa entrada completada**. Copia ambos IDs.
4. Abre **Operaciones → GET /v1/operations/{operation_id}**. Introduce el ID y pulsa Execute cada 2-3 segundos hasta `succeeded`, `failed` o `cancelled`. Si hay sala de espera, admite al bot desde Zoom. Ante fallo revisa `error.code`.
5. Consulta **GET /v1/bots/{bot_id}**. Debe mostrar `status: active`. Consulta también `/events` para ver las transiciones.
6. Abre **Reproducción → POST .../play**. Introduce tu `bot_id`, otra clave de idempotencia y elige un ejemplo: video con audio, video sin audio, MP3, foto por 120 segundos o foto indefinida. Los enlaces de ejemplos son los archivos que proporcionaste en Storage. Guarda el `playback_id` y el nuevo `operation_id`.
7. Consulta esa operación hasta `succeeded`; esto confirma el inicio de los envíos, no que el archivo ya terminó. Comprueba imagen/sonido desde Zoom y posición desde GET del bot.
8. Prueba `/pause` con otra clave y tu `playback_id`. Consulta la operación. Repite con `/resume` para continuar y `/stop` para detener. Cada orden nueva usa otra clave. Los controles admiten `{}`, pero incluir `playback_id` evita actuar sobre un intento distinto.
9. Tras stop o EOF, el bot sigue conectado. Puedes hacer otro `/play` en el mismo `bot_id` sin volver a entrar. Para cambiar de un medio aún activo, primero usa stop.
10. Termina con **DELETE /v1/bots/{bot_id}**, otra clave y **sin cuerpo**. Consulta operación hasta `succeeded`, GET del bot hasta `resource_released: true` y capacidad hasta `available_slots: 1`.

Para una foto indefinida la duración es null y solo termina por stop o salida/límite de sesión. Audio independiente mantiene la cámara apagada. Los videos de ejemplo no validan rendimiento 1080p; esa prueba está pospuesta.

## Probar también desde PowerShell

Con el proxy abierto, en otra consola desde el repositorio:

```powershell
$base = 'http://localhost:8085'
Invoke-RestMethod "$base/v1/capacity"

# Entrada: usa tu configuración local ignorada por Git. No la imprimas.
$config = Get-Content -Raw config/local.json | ConvertFrom-Json
$body = @{
    meeting = @{
        number = [string]$config.meetingNumber
        password = [string]$config.meetingPassword
        participant_name = 'VideoBot-Prueba'
    }
    options = @{waiting_room_timeout_seconds = 180; max_session_seconds = 600}
} | ConvertTo-Json -Depth 5
$joinKey = [guid]::NewGuid().ToString()
$join = Invoke-RestMethod -Method Post -Uri "$base/v1/bots" `
    -Headers @{'Idempotency-Key' = $joinKey} -ContentType 'application/json' -Body $body
$botId = $join.bot_id
$operationId = $join.operation_id
Invoke-RestMethod "$base/v1/operations/$operationId"

# Cuando la entrada sea succeeded, reproducir un ejemplo.
$playKey = [guid]::NewGuid().ToString()
$play = Invoke-RestMethod -Method Post -Uri "$base/v1/bots/$botId/play" `
    -Headers @{'Idempotency-Key' = $playKey} -ContentType 'application/json' `
    -Body (Get-Content -Raw config/media-test.json.example)
Invoke-RestMethod "$base/v1/operations/$($play.operation_id)"
Invoke-RestMethod "$base/v1/bots/$botId"

# Salida (sin cuerpo). Consultar la operación devuelta y después capacidad.
$leaveKey = [guid]::NewGuid().ToString()
$leave = Invoke-RestMethod -Method Delete -Uri "$base/v1/bots/$botId" `
    -Headers @{'Idempotency-Key' = $leaveKey}
Invoke-RestMethod "$base/v1/operations/$($leave.operation_id)"
Invoke-RestMethod "$base/v1/capacity"
$config = $null
$body = $null
```

Para audio cambia el archivo por `config/audio-test.json.example`; para foto por `config/image-test.json.example`. Consulta siempre el resultado de la operación antes de depender de ella. El ejemplo muestra llamadas individuales: vuelve a consultar si el estado todavía es queued/running.

## Errores y reintentos

| Resultado | Qué hacer |
|---|---|
| 403 al abrir la URL run.app | Usar proxy gcloud; comprobar identidad y permiso Invoker. No es la contraseña de Zoom. |
| 400 IDEMPOTENCY_KEY_REQUIRED | Llenar la cabecera en cada POST/DELETE. |
| 409 CAPACITY_EXCEEDED | Hay una reunión/reserva activa; consultar capacidad y estado. |
| 409 IDEMPOTENCY_CONFLICT | Misma clave con otro cuerpo. Usa una clave nueva para otra orden. |
| 409 PLAYBACK_BUSY / INVALID_STATE | Esperar entrada, detener el medio anterior o revisar estado. |
| 409 PLAYBACK_CHANGED | El playback_id no corresponde al intento actual. |
| 409 PLAYBACK_BLOCKED | Hay bloqueo externo/reconexión; la política del anfitrión sigue pendiente de validación. |
| 422 VALIDATION_ERROR | Revisar número, UUID, tipo de medio, URL y campos permitidos. |
| 429 RATE_LIMITED | Reducir frecuencia; observar Retry-After. |
| 503 WORKER_UNAVAILABLE / STATE_RECONCILING | Agente no listo o recuperándose. Esperar y consultar salud. |
| Operación failed después de 202 | Revisar error.code de la operación: descarga, formato, SDK o timeout. |

Si pierdes la respuesta de una orden, **repite el mismo método/ruta/cuerpo con la misma clave**. No generes otra clave a ciegas. No reintentes indefinidamente una operación cuyo resultado es failed; primero resuelve su causa. Idempotencia retiene respuestas por 24 h; no confundas un éxito histórico con el estado actual del bot.

El proxy prueba directamente `zoom-bot-api` con tu cuenta de gcloud. Tu backend Node es una integración distinta, todavía no desplegada; su configuración y prueba están en [la guía Node](../api/integrations/node/README.md).

En `/events`, identifica y pagina por `sequence`, no por `type`. Una transición observada por el SDK y la finalización de su operación pueden producir dos eventos `meeting.joined` con secuencias distintas; eso no significa que el bot haya entrado dos veces. Usa `next_after_sequence` para continuar y el estado del bot para conocer su situación actual.

Para encender y apagar la VM cuando la uses ocasionalmente, consulta [operacion.md](operacion.md).

Referencias: [proxy oficial gcloud](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy), [autenticación de desarrolladores](https://docs.cloud.google.com/run/docs/authenticating/developers).
