param([string]$GcloudBin = 'C:\Users\allan\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin')
$ErrorActionPreference = 'Stop'
function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'DOCKER_OPERATION_FAILED' }
}
if (git status --porcelain) { throw 'COMMIT_CHANGES_BEFORE_PUBLISHING' }
$revision = (git rev-parse --short=12 HEAD).Trim()
$endpoint = (docker context inspect --format '{{.Endpoints.docker.Host}}').Trim()
if ($LASTEXITCODE -ne 0 -or -not $endpoint.StartsWith('npipe://')) { throw 'UNEXPECTED_DOCKER_ENDPOINT' }
$previousPath = $env:PATH
$previousConfig = $env:DOCKER_CONFIG
$previousHost = $env:DOCKER_HOST
$state = Join-Path $PWD 'api/.state'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$temporary = Join-Path $state ('publish-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    Set-Acl -LiteralPath $temporary -AclObject $acl
    [IO.File]::WriteAllText((Join-Path $temporary 'config.json'), '{"credHelpers":{"us-central1-docker.pkg.dev":"gcloud"}}')
    $env:PATH = $GcloudBin + ';' + $previousPath
    $env:DOCKER_CONFIG = $temporary
    $env:DOCKER_HOST = $endpoint
    # Builds use the already verified SDK base, without publishing local config/media.
    Invoke-Docker @('build','-t','zoom-agent:dev','-f','api/Dockerfile.agent','api')
    Invoke-Docker @('build','-t','zoom-api:dev','-f','api/Dockerfile','api')
    $images = @{}
    foreach ($component in @('agent','api')) {
        $repository = 'us-central1-docker.pkg.dev/zoom-app-dev/zoom-bot/' + $component
        $tag = $repository + ':rev-' + $revision
        Invoke-Docker @('tag', ('zoom-' + $component + ':dev'), $tag)
        Invoke-Docker @('push', $tag)
        $digests = docker image inspect $tag --format '{{json .RepoDigests}}' | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'IMAGE_DIGEST_LOOKUP_FAILED' }
        $pinned = @($digests | Where-Object { $_.StartsWith($repository + '@sha256:') })
        if ($pinned.Count -ne 1) { throw 'IMAGE_DIGEST_LOOKUP_FAILED' }
        $images[$component] = $pinned[0]
    }
    $result = @{revision=$revision; images=$images}
    $json = $result | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText((Join-Path $state 'published-images.json'), $json, [Text.UTF8Encoding]::new($false))
    Write-Output 'PINNED_IMAGES_PUBLISHED'
} finally {
    $env:PATH = $previousPath
    $env:DOCKER_CONFIG = $previousConfig
    $env:DOCKER_HOST = $previousHost
    $resolved = [IO.Path]::GetFullPath($temporary)
    if ([IO.Path]::GetDirectoryName($resolved) -eq [IO.Path]::GetFullPath($state) -and [IO.Path]::GetFileName($resolved).StartsWith('publish-')) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
