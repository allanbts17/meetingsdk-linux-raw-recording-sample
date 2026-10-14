# Ensayo prolongado de entrada 1080p

Muestra sintética autorizada por el usuario el 2026-10-14. Archivo H.264/AAC, 1920×1080, 30 FPS constantes, 600 segundos y 402.169.424 bytes. Patrón móvil testsrc2 y cuadro blanco/pulso de 1 kHz cada dos segundos, de 100 ms, para observar sincronía. El usuario confirmó fluidez y coincidencia al comenzar.

[Archivo público de prueba](https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/videos/benchmark-1080p30-600s.mp4). Solo este objeto recibió ACL pública para el ensayo; no se modificaron los permisos del bucket.

## Configuración y método

- GCE e2-standard-2: 2 vCPU y 8 GiB. Contenedor limitado a 2 CPU y 6 GiB.
- Una reunión, un bot; entrada/reproducción por la API Cloud Run, descarga y validación desde Storage.
- Muestreo cada dos segundos por [collect-benchmark.py](../scripts/collect-benchmark.py), ejecutado dentro del agente; contador CPU cgroup v2, memoria del contenedor y RSS conjunta de SDK/FFmpeg.
- Estado, posición y cuadros/bloques aceptados obtenidos por socket IPC, sin contraseñas ni tokens. Formato emitido y fallos SDK contrastados con diagnósticos privados filtrados.
- CPU expresada en núcleos utilizados: 1,0 equivale a la mitad de las 2 CPU disponibles. Memoria cgroup incluye caché; RSS de SDK/FFmpeg y docker stats tienen alcances diferentes.
- Cuadros no aceptados estimados como posición × FPS negociados menos cuadros aceptados. Si no hay errores de envío, representan cuadros omitidos por temporización, con posible redondeo de una unidad. No es una medición de pérdida de paquetes ni del video recibido por Zoom.
- La muestra usa contenido sintético y no sustituye probar perfiles, bitrates o videos reales más exigentes. Entrada 1080p y salida negociada por Zoom son datos distintos.

## Resultados

Ensayo completado el 2026-10-14: 301 muestras durante 601,34 segundos; playback finished y bot conectado. El usuario confirmó fluidez y sincronía al inicio y al final, sin repetición del clip. La comprobación de sincronía es perceptiva; no se midió desfase en milisegundos.

| Medición | Resultado |
|---|---|
| Entrada | 1920×1080, 30 FPS, 600 s |
| Salida negociada | 640×480, 25 FPS |
| CPU media | 0,587 núcleos; 29,4% de las 2 CPU |
| CPU p95 | 0,670 núcleos; 33,5% de las 2 CPU |
| CPU máxima entre muestras | 0,786 núcleos; 39,3% de las 2 CPU |
| Memoria máxima del contenedor | 606,6 MiB, incluida caché |
| RSS máxima conjunta SDK/FFmpeg | 310,8 MiB |
| Cuadros de video aceptados | 15.000 de 15.000 previstos |
| Bloques de audio aceptados | 60.000 de 10 ms; 600 s |
| Cuadros no aceptados estimados | 0 |
| Mensajes de error de envío SDK | 0 |

[Métricas completas y muestras](benchmarks/1080p30-600s-20261014.json).

## Dimensionamiento de v1

Mantener e2-standard-2 (2 vCPU/8 GiB), con límites actuales del contenedor. En este ensayo hubo margen de CPU y RAM y no se requiere aumentar recursos. El resultado valida una entrada sintética 1080p/30 FPS con salida 640×480/25 FPS para una reunión; no valida emisión 1080p ni cualquier perfil/bitrate de archivo. Si se habilita salida HD superior, cambia el número de bots o se usan medios más exigentes, repetir el dimensionamiento.

El bot se cerró por API al terminar; la VM se mantiene encendida según instrucción del usuario.

## Repetir el ensayo

Crear una sesión con límite total suficiente para descarga y diez minutos de reproducción; una hora como máximo de sesión es suficiente. Iniciar mediante POST /v1/bots/{bot_id}/play:

```json
{
  "media": {
    "type": "video",
    "url": "https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/videos/benchmark-1080p30-600s.mp4",
    "audio_enabled": true
  }
}
```

Seguir la autenticación, Idempotency-Key y consultas de operación de [probar-api.md](probar-api.md). Mientras arranca, ejecutar el colector dentro del contenedor agente con el bot_id de la sesión; necesita importar app.sdk_control. El colector es una herramienta de medición, no un endpoint ni un servicio permanente. Revisar al principio y al final los destellos y pulsos, esperar finished y comprobar que el bot permanezca active antes de DELETE.
