param(
    [string]$Project = 'zoom-app-dev',
    [string]$ServiceAccount = '722146628233-compute@developer.gserviceaccount.com',
    [string]$ConfigPath = 'config/local.json',
    [string]$Gcloud = 'C:\Users\allan\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd',
    [switch]$AgentTokenOnly
)
$ErrorActionPreference = 'Stop'
# Bootstrap only. Never silently rotate a durable encryption key.
function Invoke-Cloud([string[]]$Arguments) {
    $result = & $Gcloud @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'GCLOUD_OPERATION_FAILED' }
    return $result
}
$existing = @(Invoke-Cloud @('secrets', 'list', '--project', $Project, '--format=value(name)'))
$secretNames = if ($AgentTokenOnly) { @('zoom-bot-agent-token') } else { @('zoom-bot-sdk', 'zoom-bot-master-key') }
foreach ($name in $secretNames) {
    if ($existing -match ('/secrets/' + [regex]::Escape($name) + '$') -or $existing -contains $name) {
        throw 'BOT_SECRET_ALREADY_EXISTS_USE_EXPLICIT_MIGRATION'
    }
}
if (-not $AgentTokenOnly) {
    $settings = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($settings.clientId) -or [string]::IsNullOrWhiteSpace($settings.clientSecret)) {
        throw 'INVALID_LOCAL_SDK_CREDENTIALS'
    }
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('zoom-bot-secrets-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    Set-Acl -LiteralPath $temporary -AclObject $acl
    $sdkFile = Join-Path $temporary 'sdk.json'
    $keyFile = Join-Path $temporary 'master-key.txt'
    if (-not $AgentTokenOnly) {
        $sdk = @{clientId=$settings.clientId; clientSecret=$settings.clientSecret} | ConvertTo-Json -Compress
        [IO.File]::WriteAllText($sdkFile, $sdk, [Text.UTF8Encoding]::new($false))
    }
    $key = [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    [IO.File]::WriteAllText($keyFile, [Convert]::ToBase64String($key), [Text.UTF8Encoding]::new($false))
    $entries = if ($AgentTokenOnly) { @(@{Name='zoom-bot-agent-token'; File=$keyFile}) } else { @(@{Name='zoom-bot-sdk'; File=$sdkFile}, @{Name='zoom-bot-master-key'; File=$keyFile}) }
    foreach ($entry in $entries) {
        Invoke-Cloud @('secrets', 'create', $entry.Name, '--project', $Project, '--replication-policy=automatic', '--quiet') | Out-Null
        Invoke-Cloud @('secrets', 'versions', 'add', $entry.Name, '--project', $Project, '--data-file', $entry.File, '--quiet') | Out-Null
        Invoke-Cloud @('secrets', 'add-iam-policy-binding', $entry.Name, '--project', $Project,
            ('--member=serviceAccount:' + $ServiceAccount), '--role=roles/secretmanager.secretAccessor', '--quiet', '--format=none') | Out-Null
    }
    Write-Output 'BOT_SECRETS_CREATED_VERSION_1'
} finally {
    # Delete only the exact temporary directory created by this invocation.
    $resolved = [IO.Path]::GetFullPath($temporary)
    $parent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($resolved) -eq $parent -and [IO.Path]::GetFileName($resolved).StartsWith('zoom-bot-secrets-')) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    if ($key) { [Array]::Clear($key, 0, $key.Length) }
}
