# Seguimiento técnico

Este archivo contiene hallazgos, errores, bloqueos, evidencias, decisiones y datos pendientes. Los pasos y sus casillas se mantienen en [plan.md](plan.md). No guardar secretos aquí.

## Entorno y SDK

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
