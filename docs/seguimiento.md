# Seguimiento técnico

Este archivo contiene hallazgos, errores, bloqueos, evidencias, decisiones y datos pendientes. Los pasos y sus casillas se mantienen en [plan.md](plan.md). No guardar secretos aquí.

## Entorno y SDK

### GCE y API: arquitectura confirmada, contrato en revisión

El usuario creó `zoom-bot-vm` para alojar el contenedor. Confirmó una reunión simultánea y videos de hasta 1080p, con origen en Storage mediante enlace público. Se inspeccionó gcloud/GCE/SSH/Docker y se comprobó accesibilidad del enlace. La propuesta inicial alojaba API y worker en VM; fue reemplazada por la confirmación de API en Cloud Run y agente/worker en GCE. Se mantienen caché temporal y recursos actuales. Solicitó elaborar primero una propuesta detallada de API: está en [api-propuesta.md](api-propuesta.md), junto a [despliegue-propuesta.md](despliegue-propuesta.md). Tras la confirmación, plan.md incorpora las etapas nuevas y conserva los pasos comprobados.

- Inspección inicial: 2026-10-13.
- SDK local: `C:\Users\allan\Downloads\zoom-meeting-sdk-linux_x86_64-7.1.5.4432`.
- Confirmada presencia de `h`, `qt_libs`, `json` y bibliotecas principales; compilación con 7.1.5 comprobada tras adaptar la API de fuente de video.
- Docker CLI 29.6.1 instalado, contexto `desktop-linux`.
- WSL2 instalado; distribución `docker-desktop` detenida durante la comprobación.

## Errores y bloqueos

- Resuelto: Docker no pudo conectar inicialmente con `dockerDesktopLinuxEngine`. Tras iniciar Docker Desktop se verificaron cliente/servidor y ejecución de Ubuntu.
- La consola restringida falló al iniciar PowerShell con `CreateProcessAsUserW`, código `-1073283067`, en operaciones de inspección. La misma inspección fuera del entorno restringido, con autorización, funcionó y permitió acceder al SDK.

## Hallazgos del código

- `PlayVideoFileToVirtualCamera()` está vacía: falta implementar envío de cuadros.
- El audio actual lee el archivo completo, lo envía de golpe a 44100 Hz y espera diez segundos. Debe sustituirse por transmisión PCM temporizada.
- El código imprime tokens; eliminar esas salidas antes de usar credenciales reales.
- El Dockerfile usa `COPY demo/`: el contexto de build debe ser la raíz del repositorio.

## Integración con Zoom pendiente de aclarar

La documentación oficial consultada indica que Meeting SDK está reservado para usos humanos y no soporta bots o asistentes de notas con IA. Esto requiere aclarar la vía de integración para el uso automatizado operativo; no demuestra imposibilidad técnica de emitir medios. La existencia de proveedores externos no confirma que esta aplicación tenga la misma vía de acceso.

RTMS es la alternativa indicada para acceso a medios. Su capacidad de sustituir la transmisión por cámara y micrófono no se ha comprobado. La preparación local puede continuar mientras se aclara este punto.

## Información pendiente del usuario

### API: separación entre entrada y reproducción

El usuario amplió el alcance a video, audio e imagen. El contrato usa `media.type` en play y define pistas/pausa/fin por tipo; las primeras pruebas prácticas serán de video. También pidió aclarar exposición y costo: propuesta documentada en [api-acceso-y-costos.md](api-acceso-y-costos.md), con API en Cloud Run y HTTPS run.app sin dominio, sustituyendo la propuesta anterior de Caddy en VM. IP actual verificada: 34.136.102.61. No se abrió ningún puerto ni se desplegó API.

El usuario aclaró que el bot puede entrar sin compartir video. Se actualizó el contrato: `POST /v1/bots` solo conecta; `POST /v1/bots/{id}/play` recibe el medio e inicia reproducción posteriormente. EOF/stop mantienen la reunión; un nuevo play puede iniciar otro intento sin salir/reentrar. Las órdenes se vinculan a playback_id para evitar controlar por accidente un intento posterior. Estos endpoints y la carga dinámica siguen siendo una propuesta, no código implementado.

### Confirmación del usuario

- Inicio del video confirmado: automáticamente al entrar a la reunión. Reproducción única; controles manuales posteriores.

- El usuario decidió intentar Meeting SDK para la prueba técnica pese a no conseguir aclaración de Zoom. Se completa la decisión de método del paso 1; esto no equivale a confirmación de soporte o autorización de Zoom. La aclaración se mantiene pendiente en este archivo y no bloquea preparación/compilación local.
- Se verificó la existencia de `video.mp4` en la raíz del proyecto.

- Archivo de prueba indicado por el usuario: `D:\Proyects\meetingsdk-linux-raw-recording-sample\video.mp4`. Existencia confirmada; formato aún no inspeccionado.
- Reproducción única. Pausa y detención se implementarán posteriormente.
- Forma de iniciar la reproducción aún pendiente de confirmar.

- El usuario confirmó que las reuniones serán propias.
- Tras las instrucciones de habilitar Meeting SDK y localizar credenciales de desarrollo, el usuario indicó «listo». Se registra la app y disponibilidad de credenciales como confirmadas por el usuario, sin inspección directa de Marketplace ni lectura de secretos.
- Para la prueba inicial se usará entrada como participante a una reunión dentro de la cuenta propietaria de la app, con JWT.
- Sigue pendiente la aclaración de Zoom sobre la vía admitida para el uso automatizado. El paso 1 del plan se cerró como decisión de prueba técnica por instrucción del usuario.
- Siguiente etapa técnica: finalizar verificación de imagen y configurar credenciales locales.

### Paso 1: requisitos verificados el 2026-10-13

- Reconsultada la documentación oficial de Linux y autorización; la restricción de uso automatizado sigue publicada.
- Para entrar como participante sin login a reuniones dentro de la cuenta propietaria de la app, la documentación indica JWT firmado con Client ID/Client Secret de la app.
- Para reuniones externas, la documentación exige revisión de Zoom y autorización atribuida a un usuario mediante ZAK u OBF según el flujo. OBF requiere un usuario asociado con ZAK ya presente en la reunión.
- Estos requisitos de autenticación no resuelven por sí mismos la admisibilidad del uso como bot.
- Resuelto por confirmación del usuario: reuniones propias y app con Meeting SDK disponible. No se necesitan secretos en esta etapa.
- Pendiente aclaración de Zoom sobre la vía admitida para emisión automatizada por cámara y micrófono. No se ha contactado a Zoom ni se ha obtenido autorización específica.
- Posteriormente el usuario confirmó reuniones propias, app y decisión de intentar este método; las tareas del paso 1 se completaron con ese alcance.

No hay preguntas pendientes para la prueba inicial de video. Inicio automático y reproducción única confirmados.

## Registro de avances

| Fecha | Evidencia / cambio | Siguiente acción |
|---|---|---|
| 2026-10-13 | Limpieza creada en commit `5df118b`: retirados Dockerfiles CentOS/Oracle y script PulseAudio CentOS; README enfocado al flujo Ubuntu actual y versión SDK actualizada. VM GCE comprobada: e2-standard-2, 2 vCPU, 8 GiB, Ubuntu 22.04 x86_64, Docker funcionando con sudo y disco libre ~31 GB. Enlace Storage devuelve 200 desde VM; clip público 640×480/109 s inspeccionado. | Usuario confirma propuesta de API/worker, caché temporal y benchmark 1080p; después modificar el plan. |
| 2026-10-13 | Controles `pause/resume/stop/status/quit` por FIFO local añadidos. Suite valida congelación de ambos contadores, preservación de 30 cuadros/100 bloques al reanudar y stop definitivo incluso desde pausa. En Zoom usuario confirma imagen/sonido pausados y participante conectado; confirma reanudación sincronizada. `stop` libera ambos FFmpeg; proceso sigue ejecutándose, status stopped y resume no reinicia. `quit` termina la reunión, limpia SDK y devuelve salida 0. | Mantener pendientes estabilidad prolongada y eventos del anfitrión/red. |
| 2026-10-13 | Pipes con `O_CLOEXEC`: regresión sintética de cancelación conjunta pasa. En Zoom, cierre con ambas pistas activas devuelve limpieza exitosa, salida 0 y PID 0. Comprobación de datos privados pasa para archivos versionables, consola y configuración de imagen. Muestra activa: CPU 35,30%, 103,9 MiB. Suite repetible y guía de errores añadidas. | Prueba prolongada y controles manuales pendientes; no se marca MVP completo. |
| 2026-10-13 | Usuario confirma sincronización de labios/voz con `video_habla.mp4`. Clip termina sin repetir: 2844 cuadros y 11360 bloques PCM; salida posterior 0. Pruebas de validación detectan archivos ausentes/inválidos o sin audio. JWT ficticio inválido sale con código 1 y limpieza exitosa; callbacks simulados cubren contraseña/reunión/token inválidos. | Continuar validación de cierre durante reproducción activa. |
| 2026-10-13 | Prueba de cierre durante reproducción activa se bloqueó y Docker forzó salida 137. Se cambia a pipes `O_CLOEXEC` para impedir que los decodificadores hereden descriptores entre sí y se añade regresión con ambas pistas activas. | Verificar la corrección en prueba sintética y reunión. |
| 2026-10-13 | Usuario solicita prueba de sincronización de labios con `video_habla.mp4`. Archivo verificado: 113,76 s, H.264 1024×576, AAC estéreo 44100 Hz. Montado como fuente de solo lectura en `zoom-msdk-sync-speech-test`. Entrada, sonido original/eco/ganancia y primeros cuadros/bloques: resultado 0. Nuevo MP4 excluido de Git y del contexto Docker. | Usuario evalúa sincronización de voz y labios; no se marca prueba prolongada como completada. |
| 2026-10-13 | Prueba final completa: usuario confirma música y voz; EOF de ambas pistas sin repetición (1652 cuadros, 6611 bloques). Contenedor retirado con `CleanSDK meetingSdk:success` y salida 0. Pruebas PCM/reloj/cancelación y JWT pasan; diff sin errores. | Pendientes pruebas prolongadas, cambios de capacidades/mute, pausa y detención manual. |
| 2026-10-13 | Configuración de sonido original aplicada desde `onMicStartSend`, después de VoIP/unmute. Original, eco y auto-gain devuelven 0. Usuario confirma que música y voz se escuchan bien; sincronía aparente confirmada en prueba anterior. PCM mono compatible conservado. | Comprobar fin/salida final y mantener pendientes pruebas prolongadas y controles manuales. |
| 2026-10-13 | La prueba estéreo devuelve error 3 (`INVALID_PARAMETER`); llamadas de sonido original antes de VoIP devuelven error 2 (`WRONG_USAGE`). Se restaura PCM mono y se mueve configuración de sonido original/eco/ganancia al callback de inicio de emisión, con reintento tras confirmarse el micrófono activo. | Comprobar retorno 0 y confirmar que la música llega correctamente. |
| 2026-10-13 | Primera prueba AV: usuario oye voz y considera que parece sincronizado, pero reporta música filtrada. Ambas pistas terminaron (1652 cuadros, 6611 bloques); salida del contenedor limpia. Se cambia a PCM estéreo y se solicita sonido original/desactivación de eco usando APIs Linux. | Verificar resultados de SDK y confirmar música desde Zoom. |
| 2026-10-13 | Micrófono virtual implementado: FFmpeg extrae PCM s16le mono a 48000 Hz, bloques de 960 bytes/10 ms. Cámara y audio usan reloj monotónico compartido con barrera de preparación. Prueba sintética: 30 cuadros, 100 bloques, inicio con desfase 0 ms, cancelación y no repetición correctos. Prueba real iniciada en `zoom-msdk-av-test`: registro de micrófono y unmute resultado 0; primeros bloques/cuadros aceptados. | Usuario confirma sonido y sincronía desde Zoom; comprobar EOF de ambas pistas y salida. |
| 2026-10-13 | Cámara virtual implementada con FFmpeg e I420 limitado; cuadros temporizados y ajustados a capacidades del SDK. Usuario confirma imagen del MP4 en Zoom. Reproducción real finaliza sin repetirse: 1.652 cuadros a 640×480, 25 FPS. Prueba sintética verifica tamaño, EOF, no repetición y cancelación. | Implementar audio PCM y sincronización; pausa/detención manual posteriores. |
| 2026-10-13 | Primera prueba de SIGTERM terminó con error 139 al limpiar antes de concluir `Leave`. Se corrigió esperando estado final y liberando recursos en el loop principal. Segunda prueba: estados 4→7, `CleanSDK meetingSdk:success`, salida 0. Participantes de prueba retirados. | Verificar también salida durante transmisión activa al ampliar pruebas. |
| 2026-10-13 | Usuario confirma que ve al participante en Zoom. Se marca verificación visual del paso 5. | Continuar con pruebas de salida y transmisión de video. |
| 2026-10-13 | Configuración real generada sin imprimir secretos; JWT con vencimiento registrado por el generador. Contenedor `zoom-msdk-connection-test` iniciado con montaje de solo lectura. Logs: `Auth succeeded: JWT`, `join_meeting:success` y estado 3 (`MEETING_STATUS_INMEETING`, confirmado en encabezado local). Medios desactivados. | Usuario confirma nombre visible desde Zoom. Contenedor permanece en la reunión; pendientes salida limpia y pruebas de errores. |
| 2026-10-13 | Preparado `config/local.json` vacío sin sobrescribir datos existentes, ignorado por Git/Docker. Nuevo generador Node sin dependencias, probado con firma HS256 y vencimiento de dos horas usando datos ficticios. Eliminadas salidas de secretos del sample; nombre configurable y medios apagados al entrar. Imagen reconstruida correctamente; configuración inválida rechazada antes de conectar y sin imprimir el token ficticio. | Usuario completa credenciales y datos de reunión en el archivo local; generar JWT real y probar montaje/entrada. |
| 2026-10-13 | Imagen corregida compilada. `ldd` sin bibliotecas ausentes. PulseAudio crea `SpeakerOutput` y `SpeakerOutput.monitor`, s16le estéreo 44100 Hz. SDK inicializa; JWT ficticio rechazado como resultado esperado (salida 1). | Configurar JWT y reunión reales; retirar logs de secretos antes de esa prueba. |
| 2026-10-13 | Contenedor Ubuntu ejecutado: x86_64. SDK y recursos copiados. Primera imagen compilada tras añadir formato I420 limitado a `setExternalVideoSource`. Enlace `.so.1` confirmado; ejecutable inicializa SDK 7.1.5 (4432). JWT de ejemplo rechazado como se esperaba. | Verificar reconstrucción con correcciones de PulseAudio y `pciutils`, después configurar credenciales locales. |
| 2026-10-13 | Docker Desktop iniciado. `docker version` responde con cliente y servidor; Engine 29.6.1, servidor Linux/amd64. `docker info` confirma linux/x86_64. | Validar un contenedor básico e integrar el SDK. |
| 2026-10-13 | README, CMake, Dockerfile y fuentes virtuales revisados. SDK accesible. Docker CLI presente; motor Linux sin respuesta y WSL `docker-desktop` detenido. | Iniciar/verificar Docker e inventariar SDK antes de copiar. |
| 2026-10-13 | Separado el plan de tareas del seguimiento técnico según indicación del usuario. Conservadas las casillas completadas. | Mantener errores, bloqueos y otros registros en este archivo. |

## Referencias

- [Reporte directo del mismo problema y secuencia después de VoIP](https://devforum.zoom.us/t/sendshareaudio-returns-sdkerr-invalid-parameter-3-for-every-documented-format-on-linux-is-custom-share-audio-supported-on-linux/144826): usado como hipótesis a validar con logs de nuestra versión, no como prueba de funcionamiento local.

Video inspeccionado: duración 66,14 s; H.264 1280×720 a 30000/1001 FPS, AAC estéreo 44100 Hz. La prueba actual transmite solo video y mantiene audio desactivado. Se conserva la última imagen al terminar; no se vuelve a decodificar el archivo. FFmpeg se lanza con argumentos directos (sin shell), y se cancela/libera su proceso al detener la fuente. Cambios de capacidad paran y reinician el decodificador desde la posición alcanzada; aún no se ha provocado un cambio de resolución durante la prueba real.

Cambios de preparación: CMake usa `config.txt.example` cuando no hay configuración local. `.dockerignore` excluye configuración real, video y script de tokens. SDK y video excluidos de Git. Se normalizó el script PulseAudio a LF y se fijó LF para scripts en `.gitattributes`; se añadió creación de su carpeta de configuración. La configuración de ejemplo desactiva recepción raw. Se añadió `pciutils` para proporcionar `lspci`.

- [Repositorio y README](https://github.com/zoom/meetingsdk-linux-raw-recording-sample)
- [Meeting SDK para Linux y política actual](https://developers.zoom.us/docs/meeting-sdk/linux/)
- [Autorización JWT, ZAK y OBF](https://developers.zoom.us/docs/meeting-sdk/auth/)
- Fuentes locales: `demo/meeting_sdk_demo.cpp`, `demo/ZoomSDKVideoSource.cpp`, `demo/ZoomSDKVirtualAudioMicEvent.cpp`, `demo/CMakeLists.txt`, `Dockerfile-Ubuntu/Dockerfile`.

## Arquitectura Cloud Run confirmada — 2026-10-13

El usuario confirmó API en Cloud Run y agente/worker en GCE, sin dominio propio. Estado persistente en SQLite de la VM; Direct VPC egress y autenticación interna para órdenes breves. El SDK mantiene la reunión independientemente de la instancia de API. Se actualizaron plan, contrato, despliegue y acceso/costos. No se desplegaron recursos ni se cambiaron firewall, IAM o tamaños. Autenticación del cliente, límites del contrato y benchmark 1080p siguen pendientes. Nuevas tareas de implementación sin marcar como completadas.

## Reproducción dinámica e inicio de /api — 2026-10-13

Commit de documentación creado antes de implementar: `696c61a`. Usuario confirmó consumidor backend propio en Cloud Run/GCP; se seleccionó IAM Invoker con ID token. Cuenta de servicio concreta pendiente, sin cambios IAM/despliegue.

Las fuentes C++ conservan sus objetos registrados y aceptan otro archivo con reloj/posición/fin reiniciados. Nuevo play después de EOF/stop no reinicia SDK ni reentra a la reunión. Se conserva FIFO de diagnóstico y se añade socket Unix JSON privado 0600, mensajes acotados, versión e IDs de operación/reproducción. Cliente y CLI Python en `api/app`; HTTP y agente SQLite aún pendientes. Imagen, eventos/posición detallada y manejo completo del anfitrión/red pendientes; no anunciar capacidades todavía inexistentes.

Suite multimedia y socket completada; seis pruebas del cliente Python pasan en Windows con mocks y en Linux. Se verifica reutilización tras stop/EOF, video sin audio y audio independiente, y callbacks de inicio duplicados sin reiniciar decodificadores. Socket prueba permisos, mensajes fragmentados/inválidos/excesivos y rechazo de sustituir listener activo.

Prueba real: bot entra con medios apagados; fragmento de ~8 s termina con 201 cuadros/801 bloques; luego video_habla.mp4 reproduce en el mismo participante. Usuario confirma video/voz sincronizados y sin salida/reentrada. La primera transición falló porque mute/unmute de pistas reutilizadas y callbacks duplicados interrumpían decodificadores; corregido evitando mutear las pistas que se reutilizan, evitando reconectar VoIP y haciendo idempotentes callbacks de inicio. Nueva prueba acepta los primeros cuadros/bloques y confirma playing. pause/resume/stop por playback_id devuelve estados aplicados y mantiene reunión; tercer play tras stop comprobado por estado/logs.

Configuración local regenerada con medios automáticos desactivados para esta prueba. Credenciales no incluidas en imagen ni commit. La última validación visual queda asociada a dos videos sucesivos; prueba de audio/imagen en Zoom y despliegue GCE todavía pendientes.

## Imagen, audio independiente y base persistente — 2026-10-13

Commit solicitado del avance previo: `b5b090a`, sin push. Cambios posteriores todavía en implementación local, sin despliegue cloud.

Imagen PNG/JPEG hasta 10 MiB: FFmpeg decodifica un cuadro I420 con proporción preservada, se recoge su proceso y el worker repite el cuadro en memoria. Imagen indefinida termina con stop; duración finita usa tiempo activo y pausa congela posición/temporizador. Capacidades nuevas vuelven a preparar el cuadro con la posición conservada. IPC añade posición, fallo de decodificación/emisión, estado numérico de reunión y contadores de envíos aceptados por SDK para distinguir ACK de primer envío.

Suite multimedia aprobada: imagen igual en todos los cuadros, duración de un segundo, pausa de 800 ms sin avance, presentación indefinida, detención, rechazo de tipos de imagen no admitidos y fallo al decodificar. Prueba real: usuario confirma imagen azul sin audio y luego voz de video_habla.mp4 con cámara apagada en el mismo participante. Imagen pausada mantuvo position_seconds=41.44 en consultas separadas; imagen finita pasó a finished exactamente en posición 3.0, manteniendo reunión. Quit devolvió salida 0. FFmpeg no quedó ejecutándose durante la imagen indefinida.

Base `api/app/store.py`: SQLite WAL/transacciones, sesiones, reserva única, operaciones en cola, claim exclusivo, eventos e idempotencia con respuesta persistida antes de devolverla. Trece pruebas Python (cliente IPC + persistencia) pasan en Windows y Linux. Ocho peticiones concurrentes con claves distintas aceptan solo una reunión; misma clave recupera el mismo bot/operación. Failed conserva capacidad hasta limpieza confirmada. Reinicio de supervisor cancela trabajos afectados, purga payload y no reentra; reinicio de API solo debe consultar al agente, sin invocar esa reconciliación.

Esta capa no es aún el agente completo. `sealed_payload` exige bytes y debe cifrarse antes de guardar; pruebas usan datos ficticios. Pendientes cifrado autenticado con Secret Manager, ejecutor y supervisión reales, descargas/caché, heartbeat, cancelación prioritaria, eventos completos del SDK y endpoints HTTP. No aceptar credenciales reales mediante esta capa hasta conectar el cifrado. Ningún dato secreto se registró en estas pruebas/documentos.

## Cifrado y ejecutor conectado al SDK — 2026-10-13

Commit solicitado del avance previo: `134a710`, sin push. El usuario autorizó git add/commit sin confirmación adicional y guardó reglas para ambos prefijos.

Agente bajo /api: valida reuniones y medios discriminados, cifra payloads antes de SQLite y ejecuta trabajos en cola. AES-256-GCM autentica cliente/comando/bot; HKDF separa clave de cifrado y HMAC de fingerprints. Clave maestra no incluida en imagen ni logs; conexión con Secret Manager pendiente. Dependencia Linux verificada: cryptography 50.0.2, fijada en requirements-agent.txt. Windows probó la API compatible con su dependencia preexistente 46.0.3; pruebas de despliegue usan Linux 50.0.2.

SdkRuntime genera JWT fresco y archivos 0600 bajo directorio 0700 por bot. SDK acepta ZOOM_CONFIG_PATH y ZOOM_CONTROL_SOCKET. Proceso en grupo independiente; leave solicita quit, espera y limpia el grupo antes de liberar capacidad y borrar configuración/logs. Store claim incluye propietario para autenticar el contexto del payload. Play espera los contadores requeridos de envíos aceptados por SDK; un timeout de envío se reconcilia con el mismo playback_id, sin repetir play.

Prueba real mediante tools/agent_demo.py e imagen zoom-agent:dev: join → play → leave administrados por el agente. Usuario confirma video_habla.mp4 y voz sincronizados. Eventos agent.joined, agent.playing y agent.ended; capacidad disponible=1 y salida del contenedor 0. Se usó config/local.json montado readonly, clave/base temporales y resolver local exclusivo de la prueba. No se descargó el medio desde Storage ni se desplegó en GCE/Cloud Run.

Pruebas cubren cifrado/contexto alterado, reintento idempotente, payloads sensibles ausentes de ciphertext, ACK anterior al primer envío, timeout sin play duplicado, controles de intento anterior y errores privados saneados. Nuevas validaciones rechazan número inválido, credenciales extra en petición, campos incompatibles por tipo y duración booleana antes de encolar.

Resultado final: 26 pruebas Python aprobadas dentro de la imagen Linux del agente con cryptography 50.0.2; build SDK/agente y git diff --check aprobados. La prueba real finalizó por sí misma sin participantes/procesos activos de prueba.

Pendientes del agente: descarga/validación/caché de Storage, Secret Manager, heartbeat y recuperación de procesos tras reinicio, límites completos de sesión y cancelación prioritaria. HTTP también pendiente. La prueba temporal no es la configuración de producción.

## Descarga y caché de Storage — 2026-10-13

MediaCache implementada bajo /api: HTTPS/host/bucket permitidos, redirecciones revalidadas, tamaño real y Content-Length, timeouts, reserva de disco, CRC32C/MD5 y comprobación de archivo mediante FFprobe/decodificación inicial. Publicación atómica y permisos 0400; hashes/ETags sin guardar URL/query en metadata. Leases persistentes y bloqueo de caché protegen archivos usados, revalidación condicional detecta versiones nuevas y eviction mantiene el límite sin borrar pins. Fallos/cancelación limpian .part.

Primera prueba entró pero falló preparando el medio y salió limpiamente. Causa: nombre stream_side_data no admitido por FFprobe 4.4 de la imagen. El selector genérico side_data también activaba packets/frames y producía JSON inválido en un fixture. Corregido a stream_side_data_list y agregado test con FFprobe/FFmpeg reales para video, audio, PNG, rotación y contenido inválido.

Segunda prueba mediante agente: enlace público proporcionado, sin mount de video local. Descargados 4.004.494 bytes; CRC32C/MD5 verificados; H.264/AAC, 640×480 y 109.018 s. Usuario confirma video/audio correctos en Zoom. Eventos agent.joined, agent.playing, media.ready y agent.ended; capacidad libre=1 y salida 0. No se desplegaron recursos en GCE/Cloud Run.

44 pruebas aprobadas en Linux. Cubren descarga interrumpida o excesiva, checksum incorrecto, falta de espacio, URLs/redirecciones no permitidas, cancelación durante transferencia, errores sin queries, caché corrompida, actualización de objeto sin reemplazar versión protegida y leases entre instancias. Una petición play incompatible no detiene ni libera el medio actual. Error de descarga conserva el bot activo sin enviar play al SDK.

El fixture de enlace público está en config/media-test.json.example; diagnóstico tools/media_probe.py y demo --media-request disponibles. La caché temporal se probó dentro del contenedor; montaje del volumen de GCE pendiente. Pins tras caída no se eliminan hasta reconciliar procesos. La cancelación prioritaria vía endpoint sigue pendiente; las pruebas de cancelación actuales usan el evento de parada del worker.

## Secret Manager: proveedor y revisión de identidad (2026-10-13)

- La VM zoom-bot-vm usa 722146628233-compute@developer.gserviceaccount.com y scope cloud-platform. No se modificó la identidad ni IAM.
- La consulta de servicios habilitados no encontró secretmanager.googleapis.com. La habilitación, creación de secretos y acceso real siguen pendientes.
- Implementado SecretProvider con ADC, cliente oficial 2.31.0, timeout 10 s, CRC32C, versiones numéricas fijas y errores sanitizados. Credenciales JSON limitadas a clientId/clientSecret; clave maestra Base64 de 32 bytes. No se trasladaron credenciales locales a GCP.
- Añadido diagnóstico tools.secret_probe que no imprime secretos ni entra a Zoom. El ejecutor conserva códigos de errores de secretos sin registrar payloads.
- Imagen zoom-agent:dev construida y 49 pruebas Linux aprobadas, incluidas 5 nuevas pruebas de secretos: corrupción, versión inválida, clave estable, formatos y errores privados.
- La supervisión persistente, heartbeat y recuperación de procesos tras reinicios siguen pendientes; esta entrega solo prepara el proveedor y el diagnóstico.

## Secret Manager real y servicio supervisado (2026-10-13)

- Habilitada secretmanager.googleapis.com en zoom-app-dev. Creados zoom-bot-sdk y zoom-bot-master-key, ambos versión 1 enabled. El SDK contiene únicamente las credenciales ya configuradas localmente; la clave AES es nueva, aleatoria, de 32 bytes en Base64.
- Concedido roles/secretmanager.secretAccessor por cada secreto a 722146628233-compute@developer.gserviceaccount.com, identidad actual de zoom-bot-vm. No se cambiaron la identidad de la VM ni sus permisos previos. La cuenta dedicada se configura en el paso de infraestructura.
- Bootstrap mediante temporales Windows con ACL privada, eliminación al terminar y rechazo de secretos existentes. No se imprimieron secretos ni se copiaron a archivos versionados.
- Diagnóstico desde GCE con metadata/REST: VM_SECRET_ACCESS_AND_CHECKSUM_OK. Verificados acceso, formato y CRC32C de ambos secretos. No se desplegó el contenedor de aplicación ni se inició un bot en Zoom durante esta etapa.
- Implementado AgentService con ADC/SecretProvider, PayloadCipher estable, versión de clave persistida, SQLite/caché en un directorio configurable y bloqueo exclusivo de propietario. CMD inicializa PulseAudio y ejecuta el servicio; HTTP privado pendiente.
- Heartbeat cada 5 s en thread independiente y readiness inválida después de 15 s sin actualización. Supervisión guarda snapshots con campos permitidos, detecta muerte del SDK y aplica reconexión de 120 s/IPC inaccesible de 15 s. La duración máxima cuenta desde aceptación; la cancelación se comprueba durante espera y transferencia. Las operaciones de red/limpieza conservan sus propios timeouts, por lo que el cierre no es instantáneo al vencer el límite.
- El launcher establece parent-death SIGKILL con control de carrera. Manifiesto/token duradero antes del proceso; recuperación por tokens heredados y pidfds para evitar reutilización de PID. Se conservan reserva/pins si la limpieza no se confirma. Los trabajos anteriores se cancelan sin reentrada automática y sus respuestas idempotentes permanecen.
- Registrados boot ID y namespace PID. Un namespace distinto en el mismo boot produce RUNTIME_NAMESPACE_CHANGED: la supervisión del host debe confirmar que el contenedor anterior terminó. Esta parte del despliegue sigue pendiente. Un boot nuevo confirma que los procesos previos desaparecieron.
- Imagen zoom-agent:dev reconstruida; 64 pruebas Linux aprobadas. Incluyen procesos Linux reales y descendientes, muerte del padre, singleton, reinicio/idempotencia, pins, clave estable, heartbeat durante trabajo, sesiones vencidas y reconexión. Arranque sin configuración verificado: INVALID_SECRET_VERSION, exit 1 esperado, sin entrar a Zoom.
- Pendientes inmediatos: prioridad/cancelación de stop y leave; transporte HTTP privado y FastAPI Cloud Run. Pendientes de despliegue: identidad dedicada, volúmenes, comprobación host de contenedor anterior y SDK real desde GCE.

## API HTTP, cancelación prioritaria e identidad consumidora (2026-10-13/14)

- El usuario identificó inicialmente la cuenta App Engine como candidata. Se consultaron los servicios: api, downloadvideo y generatevideothumbnail usan 722146628233-compute@developer.gserviceaccount.com. Confirmó que el consumidor será api; no se modificó ese backend ni su identidad.
- Implementados FastAPI/Pydantic/Uvicorn bajo /api: entrada independiente, play de video/audio/imagen, pause/resume/stop, DELETE, consultas de bots/operaciones/eventos/capacidad, salud y docs/OpenAPI. API pública sin estado, proxy a agente HTTP privado; SQLite y SDK permanecen en el agente. La prueba HTTP usa un SDK simulado; todavía no hay validación de Zoom real por esta interfaz ni despliegue.
- Versiones verificadas en PyPI: FastAPI 0.143.0, Pydantic 2.14.1, Uvicorn 0.54.0 y httpx 0.28.1. FastAPI/Starlette emite deprecation de su TestClient con httpx; las pruebas funcionan. No se cambia transporte productivo por ese aviso de pruebas.
- Creada cuenta zoom-bot-api@zoom-app-dev.iam.gserviceaccount.com para el nuevo servicio zoom-bot-api. Creado zoom-bot-agent-token versión 1, aleatorio de 32 bytes/Base64, distinto de SDK/clave de cifrado. Accessor por ese secreto para la nueva identidad y la identidad actual de GCE; acceso a los tres secretos y CRC32C comprobados desde la VM. No se concede todavía Invoker: el nuevo servicio no existe.
- Autenticación pública delegada a IAM Cloud Run; factory requiere entorno K_SERVICE/propietario y no confía en headers del usuario para identidad. El agente verifica bearer privado y propietario fijo. La API no reenvía el ID token público. Protección real IAM/Direct VPC/firewall pendientes de despliegue.
- Leave preempta entradas/descargas/controles; stop cancela play pendiente. Cancelación persistida y claim único conservado hasta fin/limpieza. Cancelar entrada mantiene reserva hasta que leave termine. Una salida pendiente se reutiliza; ACK confirmado no se retaggea como cancelado. Controles capturan playback_id transaccional y rechazan IDs antiguos antes de cancelar/aplicar nada.
- Play obtiene ID estable al aceptar. Payload cifrado purgado al claim/finalizar/cancelar; metadata pública sin password/URL/token. Consultas con timestamps UTC, cursor ligado a propietario/filtro, eventos agregados con IDs/posición y snapshots de estados. Permisos/capacidades no expuestos por IPC permanecen null. Retención automática y pausa por eventos externos pendientes.
- Controles verifican estado aplicado después del ACK o timeout, sin repetir a ciegas. Ante estado incierto bloquean nuevas órdenes hasta reconciliar; leave permanece permitido. Timeout/problema de autenticación privada en el proxy produce 503, sin fabricar 202. Reintentar con la misma clave recupera los IDs originales.
- Validación estricta de medios, claves/UUID, JSON, máximo cuerpo 64 KiB, no-store/correlación y errores sin valores recibidos ni trazas privadas. Rate limit SQLite: 60/min, 10 mutaciones/min y 5 mutaciones en 1 s. No logs de acceso Uvicorn.
- Docker Desktop quedó apagado después del bloqueo del equipo y se reinició. Se conservaron archivos y las dependencias ya construidas; no hubo bot conectado ni contenedor de aplicación desplegado durante esta etapa.
- 85 pruebas Linux aprobadas: HTTP de los tres tipos y controles, sesiones sucesivas, replay con dos instancias de API, cursores/eventos, auth privada/redacción, límites persistentes, timeouts, prioridad durante descarga/entrada y carrera de ACK. Una prueba nueva de segunda sesión requirió corregir su helper: comprobar que submit no agrega llamadas SDK, en vez de exigir un historial vacío.
- Construidas zoom-agent:dev y zoom-api:dev. Imagen pública comprobada con usuario 65532, OpenAPI, sin ejecutable SDK ni SQLite local. Factory rechaza el arranque fuera de Cloud Run con CLOUD_RUN_IAM_REQUIRED (exit 1 esperado); las pruebas de proxy no simulan permisos IAM reales.
- Próximo: retención pendiente, preparación/publicación de imágenes, identidad GCE dedicada, volúmenes y confirmación host de contenedor anterior, red privada e IAM, despliegue separado del backend api y prueba HTTP con bot real. No hay push ni despliegue en esta entrega.

## Preparación del despliegue, retención y red (2026-10-14)

- Artifact Registry privado zoom-bot creado en us-central1; se conserva gcf-artifacts. Nueva identidad zoom-bot-agent@zoom-app-dev.iam.gserviceaccount.com con Accessor por los tres secretos y Reader solo en ese repositorio.
- Red default sin peerings; IP privada de VM 10.128.0.2. Creada subred zoom-bot-run 10.42.0.0/26 y firewall del tag zoom-bot-agent: allow TCP8080 desde la subred, prioridad900; deny otros orígenes, prioridad901. No se modificaron reglas preexistentes ni otros puertos.
- VM inspeccionada sin contenedores, disco31GiB libres y RAM7.4GiB disponible. Detenida brevemente para cambiar service account y scopecloud-platform, añadir tag y arrancar. IP interna conservada; externa cambió de34.136.102.61 a34.55.35.91. No se cambió CPU/RAM/disco.
- Retención implementada cada hora en lotes25: solo sesiones terminadas y liberadas, 30d sin actividad reciente, sin trabajos pendientes ni claves idempotentes vigentes. Media mirror readonly verifica mismo inode/archivo antes de entregar ruta al SDK.
- Scripts de host y systemd preparados: manifiesto incluye container ID/hostname; antes de borrar directorio UUID exige etiqueta managed, mountestado correcto, contenedor exited/dead PID0 y namespace ausente, o un boot anterior. Flock comparte propiedad con worker. Sin prueba, conserva datos/capacidad.
- Contenedor propuesto con 2CPU/6GiB, shm256MiB, logs locales acotados, 80s de parada, sin restart-policy que eluda recuperación. Probe SQLite y watchdogsystemd reinician tras unhealthy confirmado. Inicio/recuperación no reentran a Zoom.
- 93 pruebas Linux aprobadas, incluyendo retención/FK/idempotencia, namespace/contendor vivo o ajeno, symlinks, boot anterior, media mirror y healthsin liberar reserva. Scripts de publicación usan configDocker temporal privada y tags por commit; publicación/instalación verificadas se registrarán al ejecutarlas.

## Despliegue operativo y prueba real por Cloud Run (2026-10-14)

- Publicadas las imágenes del commit a800fab889b9; referencias inmutables en deploy/images.json y deploy/image.env. Dos intentos de push fallaron por cierre de conexión/proxy Docker; el tercer intento completó ambas imágenes reutilizando las capas subidas.
- Instalado el agente con systemd y watchdog en zoom-bot-vm, estado persistente /var/lib/zoom-bot y caché montada de solo lectura para el SDK. HTTP solo en IP privada y loopback. SSH/SCP mediante IAP resolvió los timeouts del acceso directo.
- API zoom-bot-api desplegada, revisión zoom-bot-api-00001-hdx, en https://zoom-bot-api-722146628233.us-central1.run.app. Direct VPC hacia 10.128.0.2:8080, CPU 1, RAM 512 MiB, min 0/max 1, concurrencia 20. No se modificó el backend existente api.
- Invoker concedido a 722146628233-compute@developer.gserviceaccount.com, identidad del backend api. Sin allUsers; acceso anónimo devolvió 403. Salud, capacidad y OpenAPI autenticados devolvieron 200. Estas peticiones de comprobación usaron la identidad del operador; falta probar la llamada desde el backend consumidor.
- Acceso real de la nueva identidad de VM a los tres secretos comprobado con CRC32C. Retiradas las concesiones explícitas anteriores de Secret Accessor a la cuenta Compute compartida para estos secretos, conservando sus demás permisos.
- Prueba real: VideoBot-GCE entró sin medios, reprodujo el video público de Storage y el usuario confirmó imagen y audio. Join y play finalizaron succeeded. Pausa confirmada a 46.32 s; resume volvió a playing desde esa posición; stop a 62.84 s dejó la sesión active. Segunda reproducción del mismo video con nuevo playback_id completó el inicio sin reconectar.
- DELETE completó la salida; capacidad final reserved_slots=0, available_slots=1, worker_status=healthy. Confirmación de controles por estado del SDK/API; la confirmación humana fue de imagen/audio inicial, no una medición de sincronía ni del comportamiento visual de cada control.
- El video usado tiene entrada 640x480 y duración 109.018 s: esta prueba no valida rendimiento 1080p ni diez minutos. Siguen pendientes audio/imagen por API desplegada, eventos del anfitrión/red, recuperación real ante reinicios y llamada desde el backend api.
- El cliente Google del agente avisó que Python 3.10 está fuera de soporte para futuras actualizaciones. El despliegue funciona; actualizar la base a Python >=3.11 queda pendiente antes de actualizar dependencias Google.

## Audio independiente y corrección JPEG (2026-10-14)

- Audio de audios/Vientos%20susurrantes(6).mp3 reproducido por API desde GCE; el usuario confirmó audio correcto y cámara apagada. Salida solicitada antes de actualizar el agente.
- Imagen JPEG de thumbnails/videos/004%20Alabanzas%20sin%20cesar.jpg falló con OPERATION_TIMEOUT: SDK reportó fin con cero cuadros. Reproducción aislada confirmó que FFmpeg con -ss 0 produce cero bytes; sin seek produjo 460800 bytes (640x480 I420).
- Las imágenes ahora se decodifican sin seek ni filtro fps; el reloj repite el cuadro cacheado al FPS negociado. Los videos conservan seek y filtro fps. Añadida prueba JPEG de 25 FPS, además de PNG/duración/pausa/imagen indefinida. Pruebas nativas de video, AV y controles pasaron; el primer intento del nuevo test requirió una variable lvalue para la capacidad SDK y luego pasó.
- Pendiente validar la corrección desplegada con images/IMG-20220410-WA0123.jpg, enlace indicado por el usuario.
- Corrección JPEG publicada en agente sha256:b1eca582b2bdaab78d254d02054f5cd2b412f227aa9355e6a9736a196d503970. Reinicio con plaza libre: breve 503 durante arranque; luego healthy. La miniatura anterior ahora inició correctamente con play succeeded, sin reconectar la nueva sesión.
- Foto del usuario: 1600x1203, rechazada inicialmente por límite de video compartido. Política de imágenes separada: máximo 4096 por lado y 16 megapíxeles, manteniendo máximo de archivo 10 MiB; decodificación única y escalado al tamaño de cámara existente. Los videos conservan 1920x1080/30 FPS. 16 pruebas de medios aprobadas, incluyendo límites de foto y rechazo de videos verticales sin rotación.
- Agente actualizado a commit 3ec612f6d850, digest sha256:3883cc0aa26b02b8c25db381258608231a73ab8ce0c302ae44c07a6cca73e3b0. Cloud Run conserva la imagen API anterior (sin cambios necesarios en contrato/proxy); deploy/images.json refleja referencias efectivamente desplegadas.
- IMG-20220410-WA0123.jpg original inició con play succeeded y el usuario confirmó foto correcta sin sonido. No se modificaron archivos ni permisos de Storage. Finalizada la prueba mediante DELETE; salida succeeded y plaza libre/worker healthy comprobados.
- Pruebas actuales: 93 del agente reconstruido con corrección C++, y 16 de medios después de separar límites de imágenes. Los nuevos ejemplos config/audio-test.json.example e image-test.json.example permiten repetir las pruebas con las URLs proporcionadas.

## Recuperación real de agente y renovación de API (2026-10-14)

- El usuario pidió posponer el benchmark 1080p de diez minutos porque no dispone del archivo. Permanece pendiente; no se considera validada la potencia de la VM para ese caso.
- VideoBot-Recovery entró sin medios. Repetir POST con misma clave devolvió mismo bot/operación. Se provocó SIGKILL del contenedor managed, conservando prueba de ID/namespace/boot sin credenciales. systemd arrancó otro contenedor; host.reconciled confirmó la eliminación de un directorio de ejecución después de comprobar el anterior detenido.
- Recuperación: contenedor nuevo healthy, cero procesos meetingSDKDemo/FFmpeg, directorio anterior ausente, sesión anterior failed y plaza libre. Replay posterior conservó los IDs y la operación join histórica succeeded, sin nueva reserva ni conexión. El estado de sesión failed expresa el cierre posterior; el éxito histórico de join no significa que siga conectada.
- Linux reutilizó el identificador pid:[4026532262] para el contenedor nuevo. La comprobación posterior por string indicó namespace presente; se verificó que pertenecía al contenedor nuevo. La prueba de ausencia relevante se ejecutó antes de crear el nuevo contenedor mediante host_reconcile. No inferir supervivencia de procesos antiguos por coincidencia de inode después del reinicio.
- Observación humana de salida/reentrada inconclusa: el usuario no estuvo pendiente y vio un bot después. Para entonces se había iniciado expresamente otra sesión, VideoBot-API-Recovery, para una prueba distinta. La evidencia de recuperación anterior es del host y de la API, no una confirmación visual del usuario.
- VideoBot-API-Recovery entró; se renovó Cloud Run con exactamente la misma imagen desplegada, creando zoom-bot-api-00002-gzt con 100% del tráfico. La sesión permaneció active con el mismo bot ID. Replay devolvió los mismos IDs y una segunda entrada con otra clave produjo 409 CAPACITY_EXCEEDED. SDK log contado sin publicar contenidos: una autenticación exitosa y un callback In Meeting.
- DELETE posterior succeeded; capacidad final reserved_slots=0, available_slots=1, worker healthy. No queda bot de esta prueba conectado. El máximo Cloud Run sigue siendo una instancia; no se ha probado ampliarlo ni reiniciar la VM entera.
- Actualizada documentación para distinguir inspección histórica de despliegue actual y explicar URL Swagger/IAM. Falta validar llamada desde el backend consumidor y eventos del anfitrión/red.

## Integración consumidora y pausa externa (2026-10-14)

- Inspeccionado backend Node 22 en D:\Proyects\zoom-media-app\backend; servicio api usa Firebase Functions gen2 y la cuenta Compute ya autorizada como Invoker. Rutas Recall existentes no verifican Firebase Auth. El usuario eligió Firebase Auth con lista de UID para las rutas nuevas y luego aclaró que configurará el resto del backend.
- Preparados módulos cliente/router bajo api/integrations/node, copiados al backend local y montados en /zoom-bot; dependencia Google Auth 9.15.1 declarada (versión existente). No se desplegó ni se configuró el UID en ese backend. No se tocaron rutas Recall. Lint y build completos pasaron; dos pruebas Node de autorización y cliente IAM pasaron. Node local 26 produjo aviso engines frente al runtime 22 del backend.
- Primera prueba del anfitrión: mute detuvo audio pero el video siguió, confirmado por el usuario. Cerrada la sesión para corregir el comportamiento.
- Clock ahora mantiene motivos independientes user/audio_unavailable/video_unavailable/network_unavailable. Stop de una fuente por SDK pausa ambas pistas; restaurar disponibilidad retira solo ese motivo tras decodificar el primer bloque/cuadro, conservando pausa manual. Resume bloqueado no retira user ni fuerza unmute/video. Reconexión detiene el reloj en comprobación periódica de un segundo.
- IPC/snapshots/API exponen pause_reasons; resume con bloqueo externo se rechaza 409 PLAYBACK_BLOCKED. Eventos registran cambios de motivo, además del estado. Pruebas nativas de pausa externa/audio/video, restauración con pausa manual, PNG/JPEG, AV y controles aprobadas. 95 pruebas Python aprobadas. Falta comprobar estos cambios desplegados con los controles reales del anfitrión y probar red.

## Swagger completo y acceso local autenticado (2026-10-14)

- El usuario pidió documentación completa en Swagger y guía para probar. OpenAPI enriquecido con 13 operaciones, grupos, descripciones, parámetros, respuestas/modelos/errores y ejemplos de entrada, video con/sin audio, MP3, imagen limitada/indefinida y controles. Idempotency-Key se declara obligatorio para POST/DELETE. Las rutas de salud pública también se describen bajo IAM de Cloud Run.
- Guía docs/probar-api.md: proxy, flujo de aceptación/operación/estado, medios sucesivos, limpieza, paginación, claves y resolución de errores; ejemplos PowerShell sin imprimir configuración privada. Script scripts/open-swagger.ps1 inicia el proxy oficial en localhost:8085.
- Instalado componente cloud-run-proxy 0.5.1 de gcloud 569. El intento no interactivo inicial necesitó components copy-bundled-python para instalar el componente con Python externo a la instalación en actualización. Proxy iniciado: /docs devolvió 200 con Swagger HTML, capacidad healthy/plaza libre.
- La sesión de prueba del anfitrión anterior se cerró mediante DELETE y la operación succeeded. Cambio local adicional de detección de mute/cámara permanece sin validar/desplegar; el usuario pospuso esa política y aclaró que quiere reactivación cuando Zoom lo permita. No se incorpora ese cambio nativo a la publicación de Swagger.
- 98 pruebas Python aprobadas, incluyendo cobertura de todas las rutas, ejemplos aceptados por los modelos reales y resolución de referencias del contrato. Publicación -Component api construye solo contexto /api confirmado en Git, sin reconstruir SDK/agente con cambios pendientes.
- Publicada solo la API del commit 350a734b6f92, digest sha256:d544645aec072ca86bf3ff31bac45a5fa6b35da5fba85c33b47b340b5396f821. Desplegada como zoom-bot-api-00003-kzr, 100% tráfico. Agente conservó su digest anterior; deploy/images.json actualizado con las referencias realmente desplegadas.
- Verificación por proxy local de la revisión desplegada: OpenAPI contiene las 13 operaciones con descripciones, seis grupos y cinco ejemplos de medios; Idempotency-Key obligatorio. /docs 200 con Swagger y persistAuthorization=false; salud ready y capacidad libre. El proxy oficial quedó ejecutándose en localhost:8085 para acceso del usuario. No se inició una reunión durante esta validación de documentación.

## Reanudación, reinicio completo y EOF/eventos reales (2026-10-14)

- Se respetan los aplazamientos de benchmark 1080p y reactivación frente al anfitrión. El único cambio nativo local previo permanece sin validar/desplegar.
- VM encendida desde TERMINATED: systemd agente y watchdog enabled/active, contenedor healthy, digest desplegado conservado y caché /sdk-media readonly. Boot observado f4e88815-e088-4816-9085-d12105088f5e; host.reconciled sin directorios pendientes. Cloud Run devolvió ready y capacidad libre; no hubo reentrada automática. IP privada 10.128.0.2 conservada; externa 35.202.73.81.
- El usuario descartó las alertas y el presupuesto por uso ocasional. No se creó canal ni política de alerta, ni se instaló monitor. Se retiraron los permisos monitoring.metricWriter/logging.logWriter añadidos durante la preparación, y se deshicieron exclusivamente los archivos/cambios provisionales de esa tarea. Quedó un directorio temporal vacío en /tmp, sin servicio instalado.
- Docker Desktop estaba apagado: el intento de pruebas provisionales del monitor no pudo conectar al daemon. No se arrancó Docker ni se ejecutaron pruebas innecesarias después de cancelar esa tarea. Se restauraron sus dos archivos de código a HEAD; no se modificó la implementación activa del bot.
- VideoBot-EOF entró y reprodujo una vez el clip público de 109.018 s. SDK: salida 640x480/25 FPS, fin de video con 2723 cuadros y audio con 10902 bloques. API playback finished, posición 108.92 s, sesión active y reserva conservada; usuario confirmó fin sin repetición y permanencia en reunión.
- Eventos reales: páginas limit=2 y continuación con after_sequence sin repetir secuencias; has_more y next_after_sequence correctos. Observados playback.started, playback.finished y bot.ended. Dos meeting.joined tienen secuencias diferentes (snapshot SDK y operación): no equivalen a dos entradas; documentado paginar/deduplicar por sequence.
- Rechazos comprobados sin alterar reproducción: playback incorrecto 409 PLAYBACK_CHANGED, clave ausente 400 IDEMPOTENCY_KEY_REQUIRED, bot inexistente 404 BOT_NOT_FOUND y URL no permitida 422 VALIDATION_ERROR, sin devolver la URL recibida.
- Stop tras EOF: aceptación 202, mismo ID de operación al repetir clave y cabecera Idempotency-Replayed=true. Operación luego succeeded con no_op=true y playback_status finished. No suponer que todo no-op devuelve inmediatamente 200: este stop se verifica asíncronamente por el worker.
- DELETE succeeded, sesión ended/resource_released=true, evento bot.ended, capacidad reserved=0/available=1 y worker healthy. Host confirmó cero procesos meetingSDKDemo/FFmpeg y directorio de ejecución ausente. Se solicitó apagar la VM al terminar.
- Nueva guía docs/operacion.md para arrancar, comprobar salud, usar Swagger y apagar. Backend Node queda a cargo del usuario; no se despliega desde esta sesión.
- Estado final de VM verificado: TERMINATED. No quedan alertas configuradas ni permisos nuevos de telemetría; se conserva el cambio nativo pospuesto fuera de estos commits.

## Reactivación de pistas retomada (2026-10-14)

- El usuario indicó mantener la VM encendida hasta nueva orden y retomar el punto de audio/video frente al anfitrión. VM y Docker Desktop iniciados; no se apagará la VM al terminar estas pruebas.
- Sustituida la detección local pospuesta por una política activa cada 200 ms en el hilo principal del SDK. Solo interviene mientras hay reproducción waiting/playing/paused; nunca tras stop/EOF/salida ni para una pista ausente (audio-only/video-silent/imagen).
- Audio usa CanUnMuteBySelf y UnMuteAudio; video usa UnmuteVideo y comprueba el estado real posterior. Un resultado de éxito no se toma como recuperación hasta observar la pista activa. Reintento tras éxito pendiente: 1 s; error: 3 s; sin permiso audio no llama unmute. Fuentes detenidas se reinician solo tras recuperar estado, sin eliminar pausa manual.
- Retirado el bucle antiguo de unmute inicial que podía intentar actuar tras stop antes del primer callback. Pruebas nativas de reintentos/permisos/pausa manual y suites de video/AV/controles/imágenes aprobadas; ejecutable SDK compilado. Falta despliegue y comprobación con anfitrión real.
- Referencias consultadas: https://marketplacefront.zoom.us/sdk/meeting/linux/class_i_meeting_audio_controller.html y https://marketplacefront.zoom.us/sdk/meeting/linux/class_i_meeting_video_controller.html. La política no puede garantizar activación si Zoom rechaza la operación.
