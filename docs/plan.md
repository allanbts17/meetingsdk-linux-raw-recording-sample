# Plan: transmisión de video y audio a Zoom

## Objetivo y alcance

Construir un bot Linux x86_64 para una reunión simultánea, con entrada independiente de la presentación de video, audio o imagen. API Python/FastAPI en Cloud Run y agente/SDK C++ en la VM GCE `zoom-bot-vm`. Medios desde Storage mediante URL pública y caché temporal en la VM; videos de entrada hasta 1080p. Pausa, reanudación, detención y salida independientes. Las primeras pruebas serán de video. Compartir pantalla, múltiples reuniones e IA quedan fuera de esta etapa.

## Cómo mantener el seguimiento

- `[x]`: terminado y comprobado; `[ ]`: pendiente.
- Marcar cada tarea solo después de verificar su resultado.
- Mantener aquí únicamente los pasos, instrucciones para realizarlos y su estado de completado.
- Registrar hallazgos, errores, bloqueos, evidencias, decisiones y datos pendientes en [seguimiento.md](seguimiento.md), sin secretos.

## 0. Inspección inicial

- [x] Leer el README y revisar el Dockerfile Ubuntu y CMake.
- [x] Revisar los puntos de entrada y las fuentes virtuales de video y audio.
- [x] Confirmar acceso a la carpeta del SDK y presencia de `h`, `qt_libs`, `json` y bibliotecas principales.
- [x] Comprobar instalación y estado de Docker CLI y WSL.
- [x] Crear este plan de seguimiento.
- [x] Confirmar con el usuario si las reuniones serán de su cuenta o de terceros.
- [x] Confirmar archivo de prueba y reproducción única o en bucle.
- [x] Confirmar alcance inicial de los controles de reproducción.
- [x] Confirmar inicio automático para la prueba local inicial; en la API la entrada y reproducción serán órdenes independientes.

## 1. Confirmar la vía de integración con Zoom

- [x] Consultar documentación oficial actual de Meeting SDK para Linux.
- [x] Definir la vía de integración para la prueba técnica inicial.
- [x] Confirmar requisitos de la aplicación y de acceso a reuniones según la cuenta anfitriona.

Resultado esperado: ruta de integración definida antes de despliegue o uso automatizado operativo.

## 2. Preparar el entorno Linux

- [x] Iniciar Docker Desktop con motor de contenedores Linux.
- [x] Verificar `docker version` con respuesta de cliente y servidor.
- [x] Confirmar arquitectura Linux amd64 y ejecución de un contenedor básico.
- [x] Usar el Dockerfile Ubuntu 22.04 como punto de partida; contrastar dependencias con el paquete 7.1.5.
- [x] Revisar scripts shell y finales de línea LF para ejecución en Linux.

No es imprescindible instalar una distribución Ubuntu adicional si todo se compila y ejecuta dentro de Docker.

Resultado esperado: contenedores Linux funcionales en este equipo.

## 3. Integrar el SDK y compilar

- [x] Inventariar el paquete completo, su readme y los recursos requeridos por esta versión.
- [x] Copiar encabezados de `h` a `demo/include/h` y bibliotecas a `demo/lib/zoom_meeting_sdk`.
- [x] Copiar `qt_libs`, JSON y otros recursos requeridos conservando su estructura; no limitarse a las instrucciones antiguas del README.
- [x] Crear/verificar enlaces de bibliotecas dentro de Linux.
- [x] Revisar archivos ignorados por Git y evitar incorporar binarios del SDK o secretos accidentalmente.
- [x] Compilar la imagen desde la raíz del repositorio:

  ```powershell
  docker build -t zoom-msdk:7.1.5 -f Dockerfile-Ubuntu/Dockerfile .
  ```

- [x] Adaptar interfaces/callbacks que hayan cambiado en SDK 7.1.5, según errores reales y encabezados locales.
- [x] Verificar dependencias dinámicas y arranque del ejecutable.

El contexto del build es la raíz: el Dockerfile usa `COPY demo/`. El CMake actual genera el ejecutable y copia configuración/recursos a `demo/bin`.

Resultado esperado: compilación completa y ejecutable que arranca sin errores de bibliotecas.

## 4. Configuración y credenciales

- [x] Confirmar que existe una app con Meeting SDK habilitado y credenciales correspondientes.
- [x] Revisar `generateToken.js` sin imprimir posibles secretos; adaptar o reemplazar su configuración si hace falta.
- [x] Cargar Client ID y Client Secret desde configuración local protegida o variables de entorno.
- [x] Generar JWT con los campos y tiempos exigidos para SDK nativo; comprobar vencimiento y reloj.
- [x] Eliminar impresión de JWT, recording token y OBF del código y otros logs.
- [x] Crear configuración de ejemplo sin secretos y validar errores por campos ausentes.
- [x] Montar configuración real al ejecutar el contenedor para evitar incluir credenciales en la imagen.
- [x] Configurar número, contraseña y nombre visible del participante.
- [x] Mantener inicialmente `GetVideoRawData`, `GetAudioRawData`, `SendVideoRawData` y `SendAudioRawData` en `false`.

Datos que necesitaremos: existencia de la app, ubicación local de sus credenciales, número/contraseña de una reunión de prueba y nombre visible. No pedir pegar Client Secret ni tokens en el chat: indicar dónde configurarlos localmente. Empezar con una reunión dentro de la cuenta propietaria de la app; para reuniones externas verificar revisión de app y autorización ZAK/OBF aplicable. El recording token corresponde a recepción/grabación raw y no se presupone necesario para emitir cámara/micrófono.

Resultado esperado: configuración validada y JWT generado sin exponer credenciales.

## 5. Entrar y salir de una reunión

- [x] Ejecutar el contenedor con configuración montada y medios desactivados.
- [x] Verificar inicialización SDK y callback de autenticación exitosa.
- [x] Verificar entrada efectiva `MEETING_STATUS_INMEETING`, incluida admisión desde sala de espera si existe.
- [x] Confirmar nombre del participante desde un cliente Zoom humano.
- [x] Manejar contraseña incorrecta, JWT vencido y reunión no disponible con mensajes útiles.
- [x] Salir, finalizar el proceso y liberar SDK/controladores correctamente.

Resultado esperado: participante visible y ciclo de entrada/salida reproducible. La respuesta inmediata de `Join()` no basta para confirmar entrada.

## 6. Enviar video por cámara virtual

- [x] Confirmar contrato `IZoomSDKVideoSender`, formatos, capacidades y callbacks en los encabezados 7.1.5.
- [x] Implementar primero una fuente de cuadros de prueba para validar la cámara externa.
- [x] Registrar fuente externa y activar video en el momento correcto del ciclo SDK.
- [x] Verificar imagen visible desde otro participante.
- [x] Preparar un archivo local mediante FFmpeg a formato compatible (por ejemplo YUV420p/I420 si lo admite la API).
- [x] Implementar lectura/decodificación y envío de cuadros con dimensiones, tamaño y FPS correctos.
- [x] Respetar capacidades negociadas y cambios de resolución.
- [x] Implementar reproducción única y finalización al terminar el archivo.
- [x] Añadir pausa y detención en una etapa posterior.
- [x] Sustituir flags compartidos inseguros y threads detached de video por control de vida y sincronización adecuados.

Resultado esperado: video continuo visible por la cámara del participante, sin pantalla negra ni envío después de parar.

## 7. Enviar audio por micrófono virtual

- [x] Verificar PulseAudio y `zoomus.conf` generados por el script del contenedor.
- [x] Confirmar formato, canales, frecuencia y tamaño de bloques admitidos por `IZoomSDKAudioRawDataSender` 7.1.5.
- [x] Registrar fuente externa, entrar a VoIP y activar el micrófono al iniciar según callbacks y permisos del anfitrión.
- [x] Preparar PCM compatible; no enviar cabecera WAV como muestras de audio.
- [x] Enviar bloques de audio con temporización, comprobando errores del SDK.
- [x] Probar primero un tono o voz corta y después el audio del video.
- [x] Verificar sonido desde otro cliente y parada sin emisiones residuales.

Resultado esperado: audio inteligible y continuo por el micrófono del participante.

## 8. Sincronizar y controlar la reproducción

- [x] Usar reloj monotónico y una base temporal compartida para audio/video.
- [x] Evitar acumular retraso: definir qué hacer con cuadros tardíos y buffers llenos.
- [x] Coordinar inicio y fin de ambas pistas para reproducción única.
- [x] Añadir pausa y detención coordinadas de ambas pistas en una etapa posterior.
- [x] Exponer ruta del medio y opciones mediante configuración; retirar nombres de archivo hardcodeados.
- [x] Elegir interfaz de control inicial sencilla (configuración/CLI); añadir chat o API solo si se requiere.
- [ ] Manejar mute del anfitrión, desactivación de video y desconexión de forma predecible.

Resultado esperado: clip con voz e imagen sincronizadas durante una prueba de al menos diez minutos, con criterio de tolerancia acordado.

## 9. Validación del prototipo local

- [x] Probar flujo completo desde build hasta reproducción en una reunión de prueba.
- [x] Probar archivo ausente, formato inválido, fin del clip, ausencia de repetición y salida de la reunión.
- [x] Comprobar consumo de CPU/memoria y ausencia de hilos activos tras finalizar.
- [x] Verificar que archivos versionables, logs de consola y configuración incluida en imagen no contienen los valores privados configurados.
- [x] Documentar comandos, formatos aceptados, configuración y solución de errores frecuentes.
- [x] Añadir pruebas automatizadas útiles para conversión, tamaños de cuadros/bloques y control de reproducción; validar Zoom con prueba real.
- [x] Confirmar con otro participante video, música/voz y sincronización de labios en el clip de prueba.
- [ ] Completar prueba continua de al menos diez minutos y verificar eventos del anfitrión/red pendientes del paso 8.

## 10. Preparar el despliegue confirmado

- [x] Retirar Dockerfiles y scripts de distribuciones que no se usan y actualizar README.
- [x] Comprobar gcloud, VM, CPU/RAM, sistema, Docker y disco disponibles.
- [x] Confirmar una reunión simultánea y entrada máxima 1080p.
- [x] Verificar acceso al enlace público de Storage desde la VM.
- [x] Confirmar API en Cloud Run y agente/worker en GCE, sin dominio propio.
- [x] Elaborar contrato de endpoints para entrada independiente y video/audio/imagen.
- [ ] Identificar cuenta de servicio del backend y cerrar límites/tiempos propuestos en api-propuesta.md.
- [x] Confirmar backend consumidor en Cloud Run/GCP y seleccionar IAM Invoker con ID token.
- [ ] Preparar archivo de prueba 1080p/30 FPS para dimensionar la VM.

## 11. Reproducción dinámica e IPC

- [x] Entrar con cámara/micrófono desactivados y esperar comandos sin salir de Zoom.
- [x] Implementar socket Unix JSON con IDs de operación/reproducción y consulta de estado; cliente Python dentro de /api.
- [ ] Completar eventos, posición y errores de emisión en IPC y confirmar ejecución de comandos.
- [x] Implementar play de video después de entrar y nueva reproducción tras stop/EOF, sin reiniciar la sesión.
- [x] Implementar audio independiente e imagen estática, con políticas de pistas/duración del contrato.
- [x] Verificar decodificación de audio independiente y video sin audio con fuentes reutilizadas en pruebas automatizadas.
- [x] Aplicar pause/resume/stop por playback_id y liberar fuentes previas de forma segura.
- [ ] Verificar videos sucesivos, audio, imagen, eventos del anfitrión y desconexión.
- [x] Confirmar con otro participante imagen estática sin audio y audio independiente con cámara apagada.

## 12. Agente persistente en GCE

- [ ] Implementar agente Python con SQLite en volumen persistente: sesiones, operaciones, eventos e idempotencia.
- [x] Implementar base SQLite para sesiones, operaciones en cola, eventos e idempotencia.
- [x] Reservar capacidad mediante transacción y rechazar una segunda reunión aun con peticiones concurrentes.
- [x] Verificar claim exclusivo, recuperación de idempotencia y conservación de capacidad hasta confirmar limpieza.
- [x] Cifrar payloads sensibles e integrar la persistencia con el ejecutor del agente.
- [x] Registrar trabajos antes de aceptar órdenes y ejecutarlos en un worker independiente del consumidor HTTP.
- [x] Probar entrada, reproducción y salida mediante el agente con proceso/configuración/socket por sesión.
- [x] Descargar medios HTTPS de Storage con allowlist, límites, timeouts y validación FFprobe.
- [x] Verificar CRC32C/MD5 disponibles, publicar archivos completos de forma atómica y protegerlos mientras el SDK los usa.
- [x] Probar reproducción desde el enlace público de Storage sin montar videos locales.
- [x] Implementar caché limitada, archivos de solo lectura, limpieza de temporales y reserva de disco libre.
- [ ] Montar caché temporal de solo lectura, limpiar archivos y controlar espacio libre.
- [ ] Obtener credenciales desde Secret Manager, generar JWT por entrada y proteger configuración temporal.
- [ ] Supervisar procesos, heartbeat, salida y reinicio; reconciliar sin reentrar automáticamente.
- [ ] Probar idempotencia, fallos de descarga, cancelaciones, reinicios y limpieza de capacidad.

## 13. API en Cloud Run

- [ ] Implementar FastAPI/Pydantic, endpoints de api-propuesta.md y OpenAPI autenticado.
- [ ] Mantener API sin estado local duradero; consultar y entregar órdenes al agente privado.
- [ ] Propagar idempotencia y persistir en el agente antes de devolver 202; reconciliar timeouts sin duplicar órdenes.
- [ ] Implementar autenticación acordada, validación, errores, correlación y logs sin secretos.
- [ ] Verificar comportamiento al escalar y reiniciar instancias de API mientras el bot sigue conectado.

## 14. Infraestructura y despliegue

- [ ] Construir y publicar imágenes versionadas en Artifact Registry sin medios ni secretos.
- [ ] Configurar cuentas de servicio y permisos mínimos para Cloud Run y VM.
- [ ] Configurar Direct VPC egress en us-central1 y acceso al agente por IP interna de la VM.
- [ ] Limitar firewall del agente al origen de Cloud Run y autenticar la comunicación interna.
- [ ] Desplegar agente/worker con volumen persistente y supervisión al arrancar la VM.
- [ ] Desplegar API Cloud Run con URL HTTPS run.app, autenticación y escalado configurados.
- [ ] Configurar logs, métricas, alertas de fallos y control de costos.

## 15. Validación integral y entrega

- [ ] Probar por API: entrar sin medios, reproducir URL, pausar, reanudar, detener, reproducir otro medio y salir.
- [ ] Verificar EOF/stop sin salida de reunión y que DELETE libera procesos y capacidad.
- [ ] Probar video, audio e imagen; comprobar rechazos, operaciones/eventos e idempotencia.
- [ ] Medir al menos diez minutos de entrada 1080p/30 FPS: CPU/RAM, cuadros tardíos, errores y sincronía.
- [ ] Comprobar resolución realmente negociada por Zoom y dimensionar CPU según resultados.
- [ ] Verificar reinicios, conectividad privada, autenticación y ausencia de secretos en logs/imágenes.
- [ ] Documentar uso, despliegue, recuperación y actualización; marcar entrega completa tras validar con otro participante.
