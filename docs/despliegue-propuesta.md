# Propuesta de despliegue y API — arquitectura base confirmada

Este documento registra la inspección y la arquitectura base confirmada por el usuario: API FastAPI en Cloud Run y agente/worker en la VM, caché temporal y validación con recursos actuales. Fecha: 2026-10-13. La especificación detallada está en [api-propuesta.md](api-propuesta.md). El plan incorpora esta arquitectura confirmada; aún no se ha desplegado la aplicación.

## Requisitos confirmados

- Una reunión simultánea.
- Videos de entrada con resolución máxima de 1080p. Se propone dimensionar inicialmente para hasta 30 FPS; FPS máximos pendientes de confirmar si fueran superiores.
- Contenedor alojado en la VM de GCE `zoom-bot-vm`.
- Videos almacenados en Storage y disponibles mediante enlaces públicos.
- Control mediante API: entrada independiente de presentación de video/audio/imagen, estado, pausa, reanudación, detención y salida. Las primeras pruebas serán de video.

## Inspección realizada

| Recurso | Resultado |
|---|---|
| gcloud | SDK 569.0.0, sesión activa; funciona con ruta completa porque no aparece en PATH de esta consola. |
| Proyecto | `zoom-app-dev` |
| VM / zona | `zoom-bot-vm`, `us-central1-a` |
| Estado | RUNNING, aprovisionamiento STANDARD |
| Tipo | `e2-standard-2`, 2 vCPU, 8192 MiB; `isSharedCpu=false` |
| Plataforma / arquitectura | AMD Rome, x86_64 |
| Sistema comprobado por SSH | Ubuntu 22.04.5 LTS, kernel 6.8.0-1070-gcp |
| Memoria observada | Aproximadamente 7,4 GiB disponibles antes del despliegue; sin swap. |
| Disco | 35 GB `pd-balanced`; aproximadamente 31 GB libres. |
| Docker | Cliente y servidor 29.1.3 funcionando; sin imágenes ni contenedores. |
| Permisos Docker | El usuario SSH no accede directamente al socket; las consultas con `sudo -n` funcionan. |
| Salida hacia Storage | HTTP HEAD al enlace de prueba desde la VM devuelve 200 y `video/mp4`. |

Para establecer SSH, gcloud creó la clave de acceso faltante y actualizó los metadatos SSH del proyecto. No se instaló software, no se desplegó la aplicación ni se cambió tamaño/disco/firewall de la VM.

Enlace proporcionado por el usuario:

`https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/videos/015%20Lo%C3%A1moste%2C%20%C2%A1oh%20Dios!.mp4`

FFprobe local confirmó H.264 640×480, aproximadamente 29 FPS, audio AAC estéreo 44100 Hz, duración 109,018 s y 4.004.494 bytes. Este archivo no prueba la carga de 1080p.

## CPU y RAM recomendadas

Mantener inicialmente `e2-standard-2` para un bot y agente ligero; la API se ejecuta en Cloud Run. Los 8 GiB ofrecen margen de memoria; el riesgo de capacidad principal es CPU al decodificar, escalar y codificar video en tiempo real.

Esta es una recomendación para iniciar las pruebas, no una garantía de 1080p en producción. La prueba local anterior consumió puntualmente 35,30% de CPU de Docker y 103,9 MiB con salida de 640×480/25 FPS; esos valores no se pueden extrapolar directamente a GCE ni a emisión 1080p.

Antes de dar por validada la VM: reproducir un archivo real 1080p/30 FPS durante al menos diez minutos, medir CPU/RAM, cuadros tardíos, errores del SDK y sincronía. Como criterio inicial propuesto, conservar aproximadamente 30% de margen de CPU y no observar acumulación de desfase ni cortes. Si falta CPU, evaluar 4 vCPU (`e2-standard-4` u otra familia tras medir), sin redimensionar ahora. No se propone GPU para el MVP.

La resolución del archivo y la resolución emitida son distintas: actualmente Zoom negoció 640×480/25 FPS. Una entrada de 1080p no garantiza que la reunión reciba 1080p; eso dependerá de capacidades/configuración de Zoom y deberá comprobarse aparte.

## Videos desde Storage

Flujo recomendado:

1. El bot ya conectado recibe una petición de reproducción con la URL del video.
2. El agente valida HTTPS y el host/bucket permitido, límites de tamaño/duración, timeouts y redirecciones.
3. Descarga una copia temporal a una caché en el disco de la VM, fuera de la imagen del contenedor.
4. Comprueba formato y pistas con FFprobe y publica el archivo completo de forma atómica.
5. Expone el archivo de solo lectura al worker e inicia reproducción dentro de la reunión ya conectada.
6. Elimina la copia temporal al finalizar o según una política de caché acordada.

El archivo original permanece en Storage. La caché es temporal y no forma parte de la imagen. Esto permite conservar el reproductor local ya probado, evita que los dos procesos FFmpeg descarguen el mismo video por separado y reduce la dependencia de la red durante pausa/reanudación. No se recomienda introducir streaming directo por URL como primera implementación. Si el usuario requiere cero copia temporal en VM, habría que cambiar esta decisión y evaluar buffering/seek remoto.

## API recomendada

**Python + FastAPI + Uvicorn**, manteniendo el SDK y FFmpeg en C++. FastAPI cubre validación de peticiones, documentación OpenAPI y rutas de control; el procesamiento multimedia queda en el worker.

Para el MVP, dos componentes desplegados por separado:

- **API en Cloud Run:** HTTP autenticado, validación y consultas/órdenes al agente. URL HTTPS run.app sin dominio propio. Sin estado local duradero.
- **Agente y worker en GCE:** descarga, JWT y control del SDK/FFmpeg. SQLite en volumen persistente guarda sesiones, operaciones, eventos e idempotencia; una transacción reserva la única reunión permitida.

Cloud Run usa Direct VPC egress hacia la IP interna de la VM, con firewall limitado y autenticación del agente. El SDK sigue conectado aunque la API cierre una instancia. El agente confirma persistencia antes de responder 202; ante timeout se reconcilia con la misma clave de idempotencia. La API no recibe acceso al socket Docker. Extender el IPC actual con respuestas y estados estructurados para confirmar ejecución efectiva.

Rutas propuestas:

| Ruta | Función |
|---|---|
| `POST /bots` | Solicitar entrada con número/contraseña de reunión; devolver ID y estado, sin reproducir medios. |
| `POST /bots/{id}/play` | Seleccionar bot conectado y URL/tipo para presentar video, audio o imagen. |
| `GET /bots/{id}` | Estado de reunión/reproducción y último error sin secretos. |
| `POST /bots/{id}/pause` | Pausar ambas pistas. |
| `POST /bots/{id}/resume` | Reanudar desde la pausa. |
| `POST /bots/{id}/stop` | Detener el clip y permanecer en la reunión. |
| `DELETE /bots/{id}` | Salir y liberar la sesión. |
| `GET /health` | Salud del servicio; separar disponibilidad para nueva sesión del estado activo. |

`stop` permanece definitivo para ese intento; un nuevo play permite compartir otro video o repetir el mismo dentro de la reunión. El bot no sale cuando termina un clip. La reproducción dinámica requiere adaptar el código actual y es parte de la propuesta de API.

## Recursos de Google Cloud

- Cloud Run: API FastAPI con HTTPS run.app, escalado y autenticación definidos antes de publicación.
- Compute Engine: agente/worker en zoom-bot-vm, sin puerto de control público.
- Direct VPC egress: comunicación privada Cloud Run→VM en us-central1.
- Artifact Registry: imágenes versionadas, sin secretos ni medios.
- Cloud Storage: origen de video/audio/imagen mediante enlaces autorizados.
- Secret Manager: credenciales SDK, API/agente y claves necesarias; JWT fresco por entrada.
- Logging/Monitoring: logs sin secretos, métricas y alertas.

Detalles de acceso y costos en [api-acceso-y-costos.md](api-acceso-y-costos.md). No se requiere dominio, Caddy ni balanceador adicional.

## Decisiones confirmadas y detalles pendientes

1. Confirmado: FastAPI en Cloud Run y agente/SDK en GCE.
2. Confirmado: entrada independiente de presentación de video, audio o imagen; primera prueba de video.
3. Confirmado: caché temporal en VM con Storage como origen.
4. Confirmado: una reunión y recursos actuales 2 vCPU/8 GiB antes de medir 1080p.
5. Confirmado: consumidor backend en Cloud Run/GCP, autenticación IAM Invoker con ID token. Pendiente: cuenta de servicio concreta y límites/tiempos del contrato.
6. Pendiente: implementar, desplegar y validar; las nuevas tareas están en [plan.md](plan.md).

## Referencias

- [Máquinas de propósito general de Compute Engine](https://docs.cloud.google.com/compute/docs/general-purpose-machines)
- [FastAPI en contenedores](https://fastapi.tiangolo.com/deployment/docker/)
- [Descargar objetos de Cloud Storage](https://docs.cloud.google.com/storage/docs/downloading-objects)
- [Contrato y ciclo de vida de Cloud Run](https://docs.cloud.google.com/run/docs/container-contract)
- [Direct VPC egress de Cloud Run](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Acceso a secretos en Secret Manager](https://docs.cloud.google.com/secret-manager/docs/access-secret-version)
