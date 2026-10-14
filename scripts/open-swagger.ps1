param(
    [int]$Port = 8085,
    [string]$Gcloud = 'C:\Users\allan\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'INVALID_PORT' }
if (-not (Test-Path -LiteralPath $Gcloud)) { throw 'GCLOUD_NOT_FOUND' }
Write-Host "Swagger: http://localhost:$Port/docs"
Write-Host 'Mantén esta consola abierta. El proxy añade tu autenticación de gcloud.'
Write-Host 'Try it out ejecuta órdenes reales. Usa Ctrl+C para cerrar el proxy.'
& $Gcloud run services proxy zoom-bot-api --project zoom-app-dev --region us-central1 --port=$Port
if ($LASTEXITCODE -ne 0) { throw 'SWAGGER_PROXY_FAILED' }
