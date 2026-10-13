# Acceso a la API y costos

Arquitectura confirmada el 2026-10-13. Pendiente de implementación y despliegue.

## Acceso sin dominio

Cloud Run alojará FastAPI y asignará una URL HTTPS run.app. No se necesita comprar un dominio, usar DuckDNS, instalar Caddy ni agregar un balanceador.

Ejemplos ilustrativos, no endpoints desplegados:

```text
https://SERVICIO-ASIGNADO.run.app/v1/bots
https://SERVICIO-ASIGNADO.run.app/v1/bots/{bot_id}/play
https://SERVICIO-ASIGNADO.run.app/v1/bots/{bot_id}/pause
```

El cliente llama a Cloud Run por HTTPS. Cloud Run usa Direct VPC egress hacia el agente por la IP interna de zoom-bot-vm, en us-central1. El firewall limita el puerto del agente al origen configurado de Cloud Run y el agente exige una credencial independiente.

La API entrega órdenes breves. Descarga y reproducción se ejecutan en la VM; cerrar una petición o escalar Cloud Run a cero no termina la reunión. El agente guarda sesiones, operaciones, eventos e idempotencia en SQLite persistente. Confirma persistencia antes del 202; si no responde, la API informa indisponibilidad y permite reconciliar mediante idempotencia. No se requiere inicialmente Firestore, Cloud SQL ni cola administrada.

## Autenticación

Falta definir qué backend consumirá la API. Para un backend con identidad Google se recomienda IAM Invoker e ID token. El contrato actual también describe Bearer de aplicación: Cloud Run permite invocación pública y FastAPI valida obligatoriamente ese token. Son alternativas que deben cerrarse antes de publicar; un token de backend no se distribuye en una web pública.

## Costos

| Recurso | Impacto |
|---|---|
| Cloud Run | Costo adicional según CPU/memoria, solicitudes y configuración. Proponer facturación por solicitud y mínimo cero; las cuotas gratuitas no garantizan factura cero. |
| VM GCE | Se mantiene e2-standard-2 para agente, SDK y FFmpeg; sigue facturándose mientras esté encendida aunque la API escale a cero. |
| Conectividad | Direct VPC egress evita contratar un conector Serverless VPC Access; la transferencia puede generar cargos según ruta y región. |
| Dominio / proxy / balanceador | No se agregan. HTTPS y run.app vienen con Cloud Run. |
| Storage / red / IPv4 de VM | Almacenamiento, operaciones, descarga y tráfico de Zoom según uso. La IPv4 externa de la VM tiene su propia tarifa. |
| Artifact Registry / Secret Manager / logs | Cargos según uso, retención y cuotas aplicables. |
| SQLite / caché | Disco de la VM existente; ampliar el disco cambia el costo. |

No se estimó un total mensual: faltan minutos de reuniones, tráfico API, tamaños/región de medios y retención. Configurar alertas de presupuesto y medir una prueba real antes de estimar producción.

## Referencias

- [Cloud Run: URL HTTPS e invocación](https://docs.cloud.google.com/run/docs/triggering/https-request)
- [Cloud Run: Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Precios de Cloud Run](https://cloud.google.com/run/pricing)
- [Precios de red e IP externas](https://cloud.google.com/vpc/network-pricing)
