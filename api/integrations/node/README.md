# Cliente para el backend Node

Los módulos se prepararon en `D:\Proyects\zoom-media-app\backend`: servicio en `src/services/zoomBotService.ts`, router en `src/routes/zoomBot.ts`, montado bajo `/zoom-bot`. Compilación y lint del backend aprobados. El backend consumidor no se desplegó; el usuario configurará el resto de su aplicación.

Configurar `ZOOM_BOT_ALLOWED_UIDS` con una lista de UID de Firebase Auth separados por comas en el entorno del backend. Sin configuración las nuevas rutas devuelven 503; token ausente/inválido/revocado devuelve 401, y usuario fuera de lista devuelve 403. No se cambiaron las rutas Recall existentes.

Declarar `google-auth-library` como dependencia directa. El backend local usa 9.15.1, la versión ya instalada. En GCP, ADC obtiene el ID token con la identidad del servicio; esa identidad necesita `roles/run.invoker` en `zoom-bot-api`.

## Primera prueba

Desde tu frontend, con un usuario Firebase autorizado:

```javascript
const token = await currentUser.getIdToken();
const response = await fetch(
  "https://us-central1-zoom-app-dev.cloudfunctions.net/api/zoom-bot/capacity",
  {headers: {Authorization: `Bearer ${token}`}},
);
const capacity = await response.json();
```

La ruta se habilita cuando despliegues el backend preparado. Esta llamada comprueba Firebase Auth, lista de usuarios, ID token del backend y acceso IAM a la API del bot. No inicia una reunión. La llamada real desde el backend sigue pendiente.

## Rutas

El prefijo `/zoom-bot` reemplaza `/v1` en las rutas de la API del bot: `/bots`, `/bots/:bot_id`, `/bots/:bot_id/play`, `/pause`, `/resume`, `/stop`, `/bots/:bot_id/events`, `/operations/:operation_id` y `/capacity`. Métodos y cuerpos corresponden al [contrato](../../../docs/api-propuesta.md).

Toda orden POST/DELETE exige `Idempotency-Key` de 16 a 128 caracteres alfanuméricos, guion o guion bajo. El cliente debe conservar la clave para reintentar la misma orden si pierde la respuesta. El backend no genera claves por petición ni repite órdenes automáticamente. 202 implica aceptación; consultar la operación hasta completarse.

El token Firebase solo autentica al usuario ante el backend. El backend obtiene su propio ID token IAM para Cloud Run. No reenviar tokens Google al navegador ni registrar errores completos de Google/Gaxios: pueden contener cuerpos o credenciales.

Referencias: [autenticación entre servicios Cloud Run](https://docs.cloud.google.com/run/docs/authenticating/service-to-service), [Google Auth Node](https://github.com/googleapis/google-auth-library-nodejs).
