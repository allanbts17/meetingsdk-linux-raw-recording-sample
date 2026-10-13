# Pruebas y errores frecuentes

## Pruebas automatizadas

Desde la raíz del proyecto, tras construir `zoom-msdk:7.1.5`:

```powershell
node --test scripts/prepare-config.test.cjs
$zoomTestsPath = (Resolve-Path scripts).Path
docker run --rm --entrypoint /bin/bash --mount "type=bind,source=$zoomTestsPath,target=/tests,readonly" zoom-msdk:7.1.5 /tests/run-media-tests.sh
```

Las pruebas usan archivos sintéticos y emisores SDK simulados. Verifican JWT/firma/vencimiento, tamaños de cuadros y bloques PCM, inicio conjunto, fin sin repetición, cancelación de ambas pistas activas, detección de archivos inválidos/pistas ausentes y propagación de fallos del SDK. No necesitan credenciales reales ni una reunión.

## Validaciones realizadas en Zoom

- Entrada con JWT real, nombre visible y medios apagados.
- Video de música: voz y música confirmadas por el usuario después de activar sonido original al comenzar VoIP.
- `video_habla.mp4`: usuario confirma sincronización de labios y voz; duración aproximada de 1 minuto 54 segundos. No sustituye una prueba prolongada de diez minutos.
- Reproducción única: ambas pistas terminan sin reiniciarse.
- Cierre después del clip y durante reproducción activa: estados de desconexión/fin, limpieza del SDK y salida 0. Contenedor detenido sin procesos residuales.
- Muestra puntual durante reproducción del clip hablado: CPU 35,30% y memoria 103,9 MiB. Es una medición de este equipo, no un límite de capacidad ni una prueba de carga.
- Revisados los valores privados configurados contra archivos versionables, logs de consola de la prueba y configuración incluida en la imagen; no se encontraron. Archivos locales de credenciales permanecen excluidos. No se ha auditado cada archivo interno de log/dump que genere Zoom.

Pendientes: prueba de diez minutos, cambios de resolución durante reproducción real, mute/desactivación del anfitrión, cortes de red, pausa y detención manual sin salir.

## Errores frecuentes

| Mensaje / síntoma | Acción |
|---|---|
| Motor Docker no responde | Iniciar Docker Desktop con motor Linux. |
| Falta Client ID/Secret | Completar `config/local.json` o sus variables de entorno. |
| JWT inválido o vencido | Generar nuevamente con `node scripts/prepare-config.cjs --av`; comprobar credenciales y reloj. El proceso termina con salida 1. |
| Contraseña incorrecta / reunión inexistente | Corregir datos locales y regenerar configuración. Los callbacks muestran un mensaje y finalizan con salida 1. Casos cubiertos con callbacks simulados. |
| Archivo ausente | Revisar el montaje de solo lectura y `video_source`. Se rechaza antes de iniciar SDK. |
| Archivo inválido / falta pista | Usar un archivo que FFmpeg pueda decodificar y que contenga las pistas activadas; usar `--video` si no tiene audio. |
| Música filtrada | Revisar `VoIP original sound, SDK result: 0`. Debe configurarse después de entrar a VoIP y activar el micrófono. |
| Audio estéreo devuelve error 3 | Mantener PCM mono de 48 kHz: esta ruta/versión rechazó estéreo. |
| `Broken pipe` al cancelar | FFmpeg puede emitirlo cuando se cierra su salida. Es esperado si el proceso del participante termina con salida 0. |

Para revisar una prueba: `docker logs --tail 80 NOMBRE`. Para terminarla: `docker stop --timeout 20 NOMBRE`.
