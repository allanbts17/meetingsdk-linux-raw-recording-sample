# Despliegue del bot

Proyecto zoom-app-dev, VM zoom-bot-vm en us-central1-a, API nueva zoom-bot-api en us-central1. El backend existente api se conserva. Parámetros públicos en gcp.json; nombres de secretos y propietario en config/*.env.example. Nunca copiar credenciales a estos archivos.

La identidad de VM es zoom-bot-agent@zoom-app-dev.iam.gserviceaccount.com: lectura por secreto de SDK, clave maestra y token privado, y Artifact Registry Reader solo en el repositorio zoom-bot. La API usa zoom-bot-api@zoom-app-dev.iam.gserviceaccount.com y solo lee el token privado. IAM Invoker corresponde a la identidad Compute actual del backend api.

Red: default, subred de salida zoom-bot-run 10.42.0.0/26; VM 10.128.0.2. Firewall del tag zoom-bot-agent permite TCP8080 desde esa subred con prioridad900 y lo deniega a otros orígenes con prioridad901. La API usa private-ranges-only: no requiere conector VPC ni Cloud NAT para esa comunicación. Verificar IAM autenticado, ausencia de allUsers y la regla efectiva antes de entrega.

## Publicación

Desde la raíz, tras pruebas y commit:

```powershell
./scripts/publish-images.ps1
```

El script publica agent/api con rev-COMMIT en el repositorio privado us-central1-docker.pkg.dev/zoom-app-dev/zoom-bot. Usa un Docker config temporal con ACL privada y helper gcloud; no imprime tokens ni cambia permanentemente las credenciales Docker del usuario. Devuelve digests en api/.state/published-images.json. Desplegar siempre por digest, sin latest.

## VM y recuperación

Preparar image.env con ZOOM_AGENT_IMAGE=.../agent@sha256:..., copiar archivos de deploy y agent.env.example a /tmp/zoom-bot-deploy-COMMIT, ejecutar install-agent.sh como root. El instalador exige ese directorio temporal verificado y rechaza actualizar un agente activo sin detención explícita. Instala solo en /opt/zoom-bot, /etc/zoom-bot, /var/lib/zoom-bot y unidades systemd de este bot.

Estado persistente en /var/lib/zoom-bot montado como /state. Su media se monta también en /sdk-media de solo lectura: el worker escribe caché y el SDK recibe la ruta de la misma copia por ese mount. No alojar medios en la imagen. Límites del contenedor: 2 CPU, 6 GiB RAM, shm256MiB; logs Docker locales hasta 3×10MiB. Esto prepara margen de memoria del host; el benchmark1080p sigue pendiente.

zoom-bot-agent.service inicia el contenedor, respeta 80s de parada y reinicia si falla. El watchdog revisa health cada30s y solicita reinicio si Docker confirma unhealthy. La sonda lee SQLite sin secretos; heartbeat obsoleto no libera capacidad. El contenedor no usa restart-policy autónoma: el host debe reconciliar antes de cada inicio.

host_reconcile.py toma el mismo flock y exige prueba de contenedor managed, ID/hostname y mount correcto, Runningfalse, PID0, exited/dead y ausencia de su namespace en /proc. Solo entonces elimina los directorios UUID de ejecución, sin borrar SQLite/caché/clave. Un nuevo boot también prueba ausencia de procesos anteriores. La nueva instancia cancela sesiones previas y libera solo después de esa comprobación; nunca reentra a Zoom.

Los comandos privados se publican en 10.128.0.2:8080 y localhost8080, no en la IP externa. Firewall limita el origen y el agente exige bearer/propietario. ADC usa metadata de la VM. pull_image.py obtiene un access token efímero de metadata, usa config Docker temporal privada y lo elimina tras descargar; no descarga claves de cuentas de servicio.

## Retención y operación

El worker depura cada hora hasta25 sesiones por transacción: solo ended/failed con recursos liberados, 30d sin finalización/evento reciente, sin operaciones pendientes ni claves idempotentes aún vigentes. Mantiene sesiones activas y reservas inciertas. Esta retención elimina historial lógico; no intenta reescribir SQLite durante una sesión.

Comprobaciones en VM:

```text
sudo systemctl status zoom-bot-agent.service
sudo docker inspect zoom-bot-agent
sudo journalctl -u zoom-bot-agent.service --no-pager -n 30
```

El log privado del SDK está en el directorio de ejecución y se elimina tras limpiar; no publicarlo sin revisión. Para parar el bot administrado: sudo systemctl stop zoom-bot-agent.service. Una actualización de imagen requiere detenerlo y comprobar liberación, instalar digest y reiniciar.

Referencias: [Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc), [Artifact Registry](https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling), [identidades de Compute Engine](https://docs.cloud.google.com/compute/docs/access/service-accounts).
