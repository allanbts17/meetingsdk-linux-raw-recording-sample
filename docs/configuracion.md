# Configuración local de la primera conexión

1. Editar `config/local.json` en el equipo. Se creó a partir de `config/local.json.example`; está excluido de Git y Docker.
2. Completar `clientId` y `clientSecret` de desarrollo de la app con Meeting SDK habilitado. También pueden cargarse como variables `ZOOM_CLIENT_ID` y `ZOOM_CLIENT_SECRET`.
3. Completar `meetingNumber` como texto con 9-11 dígitos sin espacios, `meetingPassword` (vacío si la reunión no exige contraseña) y `participantName`.
4. Usar una reunión de la misma cuenta propietaria de la app. Iniciar esa reunión desde el cliente Zoom habitual.
5. Generar configuración y JWT localmente desde la raíz:

   ```powershell
   node scripts/prepare-config.cjs
   ```

   Se escribe `demo/config.txt`, ignorado por Git y Docker. No se muestran secretos. El JWT dura aproximadamente dos horas; ejecutar de nuevo cuando venza. El reloj del equipo debe estar sincronizado.

6. Ejecutar el contenedor con la configuración montada de solo lectura:

   ```powershell
   $zoomConfigPath = (Resolve-Path demo/config.txt).Path
   docker run --rm -it --mount "type=bind,source=$zoomConfigPath,target=/app/demo/bin/config.txt,readonly" zoom-msdk:7.1.5
   ```

7. Admitir al participante si hay sala de espera. Esta primera prueba tiene recepción y envío de audio/video desactivados. Verificar el estado de entrada y el nombre desde otro cliente Zoom.

No pegar credenciales ni JWT en el chat. No se necesita modificar `generateToken.js`; se conserva el archivo existente y se usa el nuevo generador sin dependencias externas. Los permisos Unix del generador no sustituyen los permisos de acceso de Windows: mantener los archivos locales bajo el usuario actual.

## Prueba de video por cámara virtual

Desde la raíz, generar configuración con video activado y montar el MP4 de solo lectura:

```powershell
node scripts/prepare-config.cjs --video
$zoomConfigPath = (Resolve-Path demo/config.txt).Path
$zoomVideoPath = (Resolve-Path video.mp4).Path
docker run --rm -it --name zoom-video --mount "type=bind,source=$zoomConfigPath,target=/app/demo/bin/config.txt,readonly" --mount "type=bind,source=$zoomVideoPath,target=/app/media/video.mp4,readonly" zoom-msdk:7.1.5
```

La reproducción empieza automáticamente al entrar y termina una vez. El audio sigue desactivado. Se mantiene la última imagen al finalizar el clip. La ruta en el contenedor se configura mediante `video_source` en `demo/config.txt`.

Para salir, usar Ctrl+C en esa terminal o `docker stop --timeout 20 zoom-video` desde otra. El proceso espera que termine la salida de la reunión antes de limpiar el SDK.

## Video con audio del MP4

Usar el mismo montaje del video y generar configuración con `--av`:

```powershell
node scripts/prepare-config.cjs --av
$zoomConfigPath = (Resolve-Path demo/config.txt).Path
$zoomVideoPath = (Resolve-Path video.mp4).Path
docker run --rm -it --name zoom-av --mount "type=bind,source=$zoomConfigPath,target=/app/demo/bin/config.txt,readonly" --mount "type=bind,source=$zoomVideoPath,target=/app/media/video.mp4,readonly" zoom-msdk:7.1.5
```

El micrófono virtual transmite PCM de 16 bits, mono, 48 kHz en bloques de 10 ms (960 bytes). La prueba de estéreo fue rechazada por esta versión/ruta del SDK. Se solicita sonido original y desactivación de cancelación de eco y ganancia automática al iniciar la emisión VoIP; sus resultados aparecen en los logs. Las llamadas anteriores a VoIP se rechazaron con `WRONG_USAGE`. Ambas pistas esperan a estar listas antes de iniciar el reloj compartido. Cada pista termina al agotar su contenido y no se repite; las duraciones pueden diferir ligeramente según el archivo. El reproductor descarta datos con más de 150 ms de atraso para evitar acumular retraso. La recepción/grabación raw permanece apagada.

Comprobar sonido desde otro cliente Zoom. Si el anfitrión restringe el micrófono, debe permitir su activación. La aplicación intenta desmutear al inicio durante un máximo de 15 intentos y deja de hacerlo una vez iniciada la emisión; no insiste para contrarrestar un mute posterior del anfitrión.

Para salir: `docker stop --timeout 20 zoom-av`. Para reproducir otra vez, iniciar un nuevo contenedor; la reproducción automática no es un bucle.

## Pausar, reanudar y detener sin salir

Con un contenedor llamado `zoom-av`, ejecutar desde otra terminal:

```powershell
docker exec zoom-av bash /app/playback-control.sh pause
docker exec zoom-av bash /app/playback-control.sh resume
docker exec zoom-av bash /app/playback-control.sh stop
docker exec zoom-av bash /app/playback-control.sh status
docker logs --tail 10 zoom-av
```

Ejecutar cada orden cuando corresponda; no ejecutarlas todas juntas. Sustituir `zoom-av` por el nombre de tu contenedor.

- `pause`: congela la imagen y silencia la reproducción. El participante permanece conectado.
- `resume`: continúa desde donde se pausó, ajustando el reloj de ambas pistas para conservar sincronía.
- `stop`: termina ambas pistas y libera los decodificadores; el participante permanece conectado. La última imagen puede permanecer visible. `resume` no reinicia un clip detenido o terminado.
- `status`: escribe `waiting`, `playing`, `paused`, `stopped` o `finished` en los logs del participante.
- `quit`: sale de Zoom y termina el proceso limpiamente.

Para salir mediante una orden:

```powershell
docker exec zoom-av bash /app/playback-control.sh quit
```

Las órdenes se entregan mediante una FIFO local dentro del contenedor. El helper valida la orden y espera como máximo tres segundos al escribir. El resultado de la ejecución aparece en los logs; escribir correctamente la orden no significa que el proceso ya la haya ejecutado.
