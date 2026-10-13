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
