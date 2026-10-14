param(
    [switch]$PrintToken,
    [string]$Gcloud = 'C:\Users\allan\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Gcloud)) { throw 'GCLOUD_NOT_FOUND' }
$result = & $Gcloud auth print-identity-token
if ($LASTEXITCODE -ne 0) { throw 'IDENTITY_TOKEN_FAILED' }
$token = ($result -join "`n").Trim()
if ($token -notmatch '^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$') {
    throw 'INVALID_IDENTITY_TOKEN'
}
if ($PrintToken) {
    Write-Output $token
} else {
    Set-Clipboard -Value $token
    Write-Host 'Token copiado al portapapeles. Pégalo en Authorize de Swagger.'
    Write-Host 'Para HTTP utiliza: Authorization: Bearer <token>'
}
