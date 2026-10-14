# Encender, probar y apagar el bot

El agente arranca automáticamente con `zoom-bot-vm`. Arrancar la VM **no entra a Zoom**: la entrada requiere POST /v1/bots. La API y Swagger permanecen en Cloud Run aunque la VM esté detenida; las operaciones que necesitan al agente devuelven 503 mientras no esté disponible.

## Encender

```powershell
$gcloud = 'C:\Users\allan\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
& $gcloud compute instances start zoom-bot-vm --project zoom-app-dev --zone us-central1-a
```

Después abre el proxy desde la raíz:

```powershell
./scripts/open-swagger.ps1
```

En http://localhost:8085/docs comprueba GET /health/ready y GET /v1/capacity. Espera `ready`, `worker_status: healthy` y `available_slots: 1` antes de entrar. El arranque puede tardar; un 503 inicial no significa que tengas que volver a enviar la entrada con otra clave.

La IP interna usada por la API es 10.128.0.2. La IP pública puede cambiar al apagar/encender; no se usa como dirección del agente para Cloud Run. Para SSH se emplea IAP:

```powershell
& $gcloud compute ssh zoom-bot-vm --project zoom-app-dev --zone us-central1-a --tunnel-through-iap
```

Comprobaciones desde la VM:

```bash
sudo systemctl is-active zoom-bot-agent.service zoom-bot-watchdog.timer
sudo docker ps --filter name=zoom-bot-agent
```

## Apagar cuando lo decidas

La instrucción vigente es mantener la VM encendida hasta que el usuario indique apagarla. Cerrar un bot no implica apagar la VM. Cuando decidas apagarla, si hay un bot conectado usa DELETE /v1/bots/{bot_id}, espera succeeded y comprueba `resource_released: true` y plaza libre. Solo entonces ejecuta:

```powershell
& $gcloud compute instances stop zoom-bot-vm --project zoom-app-dev --zone us-central1-a
& $gcloud compute instances describe zoom-bot-vm --project zoom-app-dev --zone us-central1-a --format='value(status)'
```

El estado final esperado es TERMINATED. Los discos conservan SQLite, caché e imágenes. Tras un fallo/reinicio el agente reconcilia las sesiones anteriores y no las vuelve a conectar automáticamente; consulta el estado actual antes de decidir una nueva entrada.

Los logs Docker locales están limitados a tres archivos de 10 MiB. No se han configurado alertas por correo ni presupuesto: se dejaron fuera del alcance actual a petición del usuario. Las políticas de v1 y recuperación de red están verificadas; las limitaciones de cámara y su mejora para v2 están registradas en seguimiento. Los resultados del ensayo 1080p se documentan por separado.

Guías: [probar API](probar-api.md), [despliegue y recuperación](../deploy/README.md).
