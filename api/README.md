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

Pendientes: Secret Manager, volumen de caché en GCE, heartbeat y reconciliación de procesos tras reinicio, límites completos de sesión, cancelación prioritaria de play/leave y endpoints HTTP. El agente todavía no está desplegado ni preparado para aceptar tráfico de producción.

## Medios desde Storage

`app/media.py` ofrece MediaCache y leases de archivos. Solo acepta HTTPS a storage.googleapis.com y objetos del bucket zoom-app-dev.firebasestorage.app; valida cada redirección y rechaza credenciales en URL, otros hosts/buckets y traversal. Descarga por bloques con límites aunque falte Content-Length. No registra URLs ni queries; errores se expresan con códigos fijos.

Defaults: video/audio hasta 1 GiB, imagen hasta 10 MiB, caché hasta 2 GiB y reserva mínima de 5 GiB libres. Conexión hasta 10 s, lectura hasta 30 s y descarga total hasta 300 s. Valida CRC32C/MD5 presentes en x-goog-hash; checksum_verified indica si se verificó al menos uno.

FFprobe valida contenedor, pistas, codecs, duración hasta 3600 s, orientación y dimensiones hasta 1920×1080; video hasta 30 FPS. Se decodifica una muestra inicial de 100 ms: errores posteriores corresponden a la reproducción, no a una validación completa previa. MP4/H.264 + AAC cuando se pide audio; MP3, WAV PCM y familia M4A/AAC para audio; PNG/JPEG estático para imagen. El SDK convierte según las capacidades negociadas por Zoom.

Los archivos se publican tras validar, con nombre derivado del contenido y permisos 0400. ETag/GET condicional detectan cambios del objeto; una versión nueva no reemplaza el archivo de otra reproducción. SHA-256 comprueba la copia local. Leases persistentes protegen archivos en reproducción/pausa, incluso frente a otra instancia de caché; la limpieza y eviction solo eliminan archivos no protegidos. Los .part se eliminan en fallos/cancelación. Tras una caída, conservar pins hasta que la supervisión confirme que el SDK anterior terminó.

El agente conserva el lease hasta stop/leave o antes de reemplazar un medio ya terminado. Ante emisión incierta, exige stop antes de liberarlo. Una petición play mientras hay un medio activo falla sin detener ni eliminar el medio actual. La limpieza de caché al finalizar la prueba borra archivos elegibles; el servicio podrá reutilizarlos bajo la política limitada de caché.

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

Para probar Storage, montar config/media-test.json.example como /requests/media.json y usar --media-request; no montar ningún MP4 local:

```text
python3 -m tools.agent_demo --config /secrets/local.json --media-request /requests/media.json --hold-seconds 30
```

Diagnóstico de descarga sin entrar a Zoom:

```text
python3 -m tools.media_probe --media-request /requests/media.json
```

Ese diagnóstico solo muestra metadata/códigos; --diagnose añade campos seleccionados de FFprobe. La configuración de caché persistente en volumen de GCE sigue pendiente. La prueba utiliza un directorio temporal fuera de la imagen.

Referencia: [Cloud Storage: verificación de integridad con CRC32C/MD5](https://docs.cloud.google.com/storage/docs/data-validation).

Referencias de cifrado: [AEAD/AESGCM](https://cryptography.io/en/stable/hazmat/primitives/aead/), [HKDF](https://cryptography.io/en/stable/hazmat/primitives/key-derivation-functions/#hkdf).

Pruebas desde api/:

```powershell
python -m unittest discover -s tests -v
```

Dependencias fijadas del agente: cryptography 50.0.2 y google-crc32c 1.9.0. La caché usa flock y se prueba en Linux dentro de la imagen, incluidos FFprobe/FFmpeg reales; instalar dependencias en un entorno virtual para desarrollo local.

## Secret Manager

`app.secrets.SecretProvider` usa el cliente oficial 2.31.0 e identidad ADC, sin archivos de claves de cuentas de servicio. Recibe dos nombres completos con versión numérica: `projects/PROJECT/secrets/SECRET/versions/1`. No permite `latest`: cambiar silenciosamente la clave maestra impediría recuperar payloads e idempotencia persistidos.

El secreto SDK contiene únicamente JSON con `clientId` y `clientSecret`. El secreto de cifrado contiene 32 bytes aleatorios codificados en Base64, sin salto de línea. Se comprueba CRC32C en cada lectura; el timeout es 10 segundos y los errores públicos son códigos fijos. Las credenciales se obtienen mediante `provider.credentials` al iniciar el runtime; `provider.master_key()` inicializa PayloadCipher y debe conservar la misma versión entre reinicios.

Comprobación de acceso, sin entrar a Zoom ni imprimir valores:

```text
python3 -m tools.secret_probe --credentials-version projects/PROJECT/secrets/zoom-sdk/versions/1 --master-key-version projects/PROJECT/secrets/zoom-key/versions/1
```

Secret Manager está habilitado en zoom-app-dev. Existen zoom-bot-sdk y zoom-bot-master-key, versión 1, con acceso por secreto para la identidad actual de la VM. Se comprobó desde la VM acceso, formato y CRC32C mediante metadata/REST sin imprimir valores. El servicio usa ADC con el cliente oficial; su ejecución en GCE con el SDK real sigue pendiente del despliegue. La VM tiene scope cloud-platform; este scope no sustituye los permisos IAM. Referencia: [acceso y verificación de secretos](https://docs.cloud.google.com/secret-manager/docs/access-secret-version).

El script scripts/provision-agent-secrets.ps1 es de bootstrap: lee la configuración local, usa temporales con ACL privada y los elimina al terminar. Rechaza secretos existentes para impedir la regeneración accidental de la clave maestra. La rotación requiere una migración explícita de datos; no volver a ejecutar el bootstrap sobre estos secretos.

## Servicio persistente y recuperación

El CMD de la imagen inicia PulseAudio y Uvicorn con `app.private_http:app_factory`. El lifespan crea AgentService y ejecuta el worker/heartbeat en threads separados del servidor HTTP. El agente espera órdenes en SQLite; no entra a ninguna reunión al arrancar. `config/agent.env.example` contiene únicamente nombres de recursos, propietario y ruta de estado, sin valores privados. `tools.agent_service` sigue disponible como entrada de diagnóstico sin HTTP.

El volumen `/state` contiene state.db, WAL, configuración pública de la versión de clave, caché y directorios privados de ejecución. Debe conservarse entre reinicios; no ejecutar dos agentes con distintos volúmenes contra la misma capacidad. Un flock exclusivo impide dos propietarios del mismo estado. La versión de clave registrada debe coincidir al reiniciar; un cambio falla antes de ejecutar trabajos.

El heartbeat se persiste cada 5 segundos en un thread independiente, incluso durante descargas o espera de admisión. Su consulta deja de estar ready tras 15 segundos sin actualización o al detenerse. Esto no libera la capacidad. La supervisión del SDK corre en el thread del worker y guarda snapshots con campos permitidos, sin rutas, URLs ni credenciales. El máximo de sesión cuenta desde la aceptación, incluida cola/entrada; cancela descargas y espera y provoca limpieza. Una reconexión tiene 120 segundos; IPC inaccesible durante 15 segundos provoca limpieza. Estos límites requieren pruebas reales de red/anfitrión en GCE.

Antes de iniciar el SDK se persiste un token de propietario; sus hijos heredan el token. Un wrapper Linux configura parent-death SIGKILL antes de exec, con comprobación de la carrera de arranque. La recuperación identifica procesos por ese token y utiliza pidfds para evitar matar un PID reutilizado. Solo después de confirmar ausencia de procesos elimina configuración/logs y libera capacidad/pins. Un fallo de inspección conserva la reserva. Al reiniciar, cancela trabajos anteriores y mantiene sus respuestas idempotentes; no reentra automáticamente.

Ejemplo previsto dentro de la imagen en GCE, con un volumen persistente montado en `/state` y las variables públicas de agent.env.example:

```text
/opt/agent/tools/run-agent.sh
```

Prueba de acceso metadata/REST sin dependencias, exclusiva de GCE:

```text
python3 -m tools.vm_secret_probe
```

Pendientes: despliegue, prueba HTTP con SDK real desde GCE y supervisión al arrancar la VM. La identidad actual es la cuenta Compute predeterminada; sustituirla por una cuenta dedicada al configurar infraestructura, sin retirar permisos preexistentes de la VM.

La recuperación registra boot ID y namespace PID. Si un contenedor nuevo conserva directorios de ejecución de otro namespace durante el mismo arranque de la VM, falla con RUNTIME_NAMESPACE_CHANGED y conserva la reserva: sus procesos no serían visibles desde el nuevo contenedor. El despliegue debe comprobar desde el host que el contenedor anterior y sus procesos terminaron antes de limpiar esos directorios. Esa comprobación del host se implementará con la supervisión de GCE. Tras un reinicio completo de la VM, los procesos del boot anterior no pueden seguir vivos y se reconcilian automáticamente.

## API HTTP y cancelaciones

Swagger y guía práctica: [probar-api.md](../docs/probar-api.md). Para verlo y ejecutar solicitudes autenticadas desde el navegador, usar `./scripts/open-swagger.ps1` desde la raíz y abrir http://localhost:8085/docs. La API desplegada permanece protegida por IAM.

`app.public_http` es el proxy stateless para Cloud Run; `app.private_http` es el servidor del agente. Ambos exponen POST/GET /v1/bots, GET/DELETE /v1/bots/{bot_id}, play/pause/resume/stop, operations, events, capacity y health, además de docs/OpenAPI. El contrato detallado está en docs/api-propuesta.md.

La API pública usa IAM de Cloud Run: desplegar como el nuevo servicio zoom-bot-api, autenticado, y conceder Invoker al consumidor confirmado 722146628233-compute@developer.gserviceaccount.com (servicio actual api). No reemplazar ese servicio api. El factory exige K_SERVICE y configuración de propietario; las pruebas del proxy en memoria no prueban IAM. No publicar la imagen pública como un servidor sin IAM: Google valida las invocaciones delante del contenedor. No se interpreta el token cuya firma Google puede retirar, ni se acepta un propietario suministrado por el cliente.

Se creó zoom-bot-api@zoom-app-dev.iam.gserviceaccount.com para la nueva API y zoom-bot-agent-token versión 1 como credencial interna de 32 bytes aleatorios/Base64. La nueva identidad tiene acceso por secreto únicamente a esa credencial. La identidad actual de GCE también puede leerla. El bootstrap `scripts/provision-agent-secrets.ps1 -AgentTokenOnly` no modifica SDK ni clave maestra y rechaza un secreto existente. Los nombres son públicos; sus valores solo se leen con ADC. `config/api.env.example` contiene la configuración pública; asignar la IP privada al desplegar.

El agente exige bearer constante comparado con hmac.compare_digest y X-Bot-Owner igual al propietario configurado. La API añade ambas cabeceras; nunca reenvía la autorización pública al agente. Firewall/Direct VPC y los permisos Invoker del servicio nuevo se configuran en el siguiente paso. El factory privado de prueba recibe un agente/token sintéticos; el factory productivo usa Secret Manager.

Las órdenes se registran antes del 202. Play obtiene un playback_id estable al aceptar, antes de descargar. Pause/resume/stop capturan el intento actual dentro de la transacción; un ID antiguo se rechaza antes de cancelar/aplicar nada. La URL/password solo se guardan cifrados en la cola y se purgan al reclamar/finalizar/cancelar. El historial conserva número/nombre y metadata saneada, sin URL completa ni credenciales.

Leave tiene prioridad y cancela trabajos en cola o pide cancelación al trabajo activo, incluida entrada/admisión/descarga. Stop puede cancelar un play pendiente conservando la reunión. Una segunda salida en curso recupera la misma operación; una sesión liberada admite DELETE no-op 200. El claim activo se conserva hasta que el worker termina/limpia, por lo que nunca se ejecutan dos comandos SDK simultáneamente. Cancelación durante lecturas de red espera los timeouts ya acotados; no implica cierre instantáneo. Un ACK ya confirmado conserva succeeded aunque una salida/stop posterior haya pedido cancelación.

Pause/resume comprueban estado aplicado; un timeout IPC se reconcilia sin reenviar el comando. Si no se confirma, se bloquean nuevas órdenes hasta obtener estado, permitiendo salida. El proxy devuelve 503 ante timeout/desconexión del agente y no inventa 202 ni repite peticiones; el consumidor reintenta con la misma Idempotency-Key y recupera los IDs originales. SQLite permanece en GCE aunque escale/reinicie la API.

Validación Pydantic estricta por tipo, campos desconocidos rechazados, allowlist Storage, JSON/cuerpo limitado a 64 KiB, UUIDs, claves 16–128 caracteres alfanuméricos/guion/guion bajo, Cache-Control no-store y X-Request-ID. Errores no incluyen valores recibidos ni excepciones privadas; logs de acceso Uvicorn desactivados. Rate limit persistente por propietario: 60 peticiones/minuto, 10 mutaciones/minuto, hasta 5 mutaciones en un segundo. Esta ráfaga usa ventana móvil de un segundo.

Consulta de listas con cursor de fecha+ID ligado al propietario/filtro; eventos ordenados con posición/IDs y transiciones agregadas. Valores no expuestos por IPC, incluidos permisos/capacidades de salida, permanecen null. Las políticas del anfitrión/red todavía requieren implementación/pruebas.

Actualización de infraestructura: retención automática implementada cada hora en lotes de25 sesiones confirmadas como terminadas, preservando operaciones pendientes, actividad reciente y claves vigentes. El despliegue monta caché de solo lectura en /sdk-media para las rutas entregadas al SDK, conservando escritura de caché por el worker en /state/media; se verifica que ambas rutas sean el mismo archivo. Scripts de supervisión/recuperación del host en deploy/. Las políticas del anfitrión/red siguen pendientes.

Construcción de la imagen independiente para Cloud Run, sin SDK ni medios y con usuario no privilegiado:

```powershell
docker build -t zoom-api:dev -f api/Dockerfile api
```

La imagen del agente conserva SDK/FFmpeg y se construye con Dockerfile.agent. Usar un solo worker Uvicorn en el agente (flock rechaza propietarios duplicados). Reservar al menos 75 segundos de gracia al detener su contenedor para terminar transferencias y limpieza nativa. La imagen del proxy puede tener múltiples instancias; todas consultan el mismo agente.

Referencias: [IAM entre servicios de Cloud Run y cabeceras de ID token](https://docs.cloud.google.com/run/docs/authenticating/service-to-service), [lifespan FastAPI](https://fastapi.tiangolo.com/advanced/events/).
