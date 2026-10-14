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
