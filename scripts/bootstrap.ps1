[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$HermesHome,
    [string]$Profile = 'default',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($HermesHome -notmatch '^[A-Za-z]:[\\/]') {
    throw 'HermesHome must be an absolute path on a local Windows drive.'
}
if ($Profile -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$') {
    throw 'Profile must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$.'
}

$scriptRoot = [System.IO.Path]::GetDirectoryName($PSCommandPath)
$skillRoot = [System.IO.Directory]::GetParent($scriptRoot).FullName
$lockPath = Join-Path $skillRoot 'references\dependencies.lock.json'
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$resolvedHermes = [System.IO.Path]::GetFullPath($HermesHome)
$profilesRoot = [System.IO.Path]::GetFullPath((Join-Path $resolvedHermes 'skill-data\codex-desktop-control\profiles'))
$runtimeRoot = [System.IO.Path]::GetFullPath((Join-Path $profilesRoot $Profile))
$expectedPrefix = $profilesRoot + [System.IO.Path]::DirectorySeparatorChar
if (-not $runtimeRoot.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved profile path escaped the Hermes skill-data root.'
}

$toolsRoot = Join-Path $runtimeRoot 'tools'
$downloads = Join-Path $runtimeRoot 'downloads'
$staging = Join-Path $runtimeRoot ('.bootstrap-' + [Guid]::NewGuid().ToString('N'))
$manifestPath = Join-Path $toolsRoot 'install-manifest.json'
$bootstrapLockPath = Join-Path $runtimeRoot '.bootstrap.lock'
$bootstrapLockStream = $null

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-Hash([string]$Path, [string]$Expected) {
    $actual = Get-Sha256 $Path
    if ($actual -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Path. Expected $Expected, got $actual."
    }
}

function Fetch-Archive($Dependency) {
    $target = Join-Path $downloads $Dependency.archive
    if (-not (Test-Path -LiteralPath $target) -or $Force) {
        Invoke-WebRequest -Uri $Dependency.url -OutFile $target -UseBasicParsing
    }
    Assert-Hash $target $Dependency.archive_sha256
    return $target
}

function Extract-PinnedFile([string]$ArchivePath, [string]$FileName, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $matches = @($archive.Entries | Where-Object { $_.Name -ieq $FileName })
        if ($matches.Count -ne 1) {
            throw "Expected exactly one $FileName in $ArchivePath; found $($matches.Count)."
        }
        $destinationFull = [System.IO.Path]::GetFullPath($Destination)
        $parent = [System.IO.Path]::GetDirectoryName($destinationFull)
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        if (Test-Path -LiteralPath $destinationFull) {
            throw "Fresh staging file already exists: $destinationFull"
        }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($matches[0], $destinationFull, $false)
    }
    finally {
        $archive.Dispose()
    }
}

function Set-PrivateAcl([string]$Path) {
    $icacls = Join-Path ([System.Environment]::SystemDirectory) 'icacls.exe'
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & $icacls $Path '/reset' '/T' '/C' '/Q' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "icacls reset failed for private runtime $Path with exit code $LASTEXITCODE"
    }
    $arguments = @(
        $Path,
        '/inheritance:r',
        '/grant:r',
        "*$currentSid`:(OI)(CI)F",
        '*S-1-5-18:(OI)(CI)F',
        '*S-1-5-32-544:(OI)(CI)F'
    )
    & $icacls @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "icacls failed for private runtime $Path with exit code $LASTEXITCODE"
    }
    $allowed = @($currentSid, 'S-1-5-18', 'S-1-5-32-544')
    $unexpected = @((Get-Acl -LiteralPath $Path).Access | Where-Object {
        try {
            $sid = $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            $allowed -notcontains $sid
        }
        catch {
            $true
        }
    })
    if ($unexpected.Count -ne 0) {
        throw "Private runtime ACL contains unexpected principals: $($unexpected.IdentityReference -join ', ')"
    }
}

function Assert-NoReparsePath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    $current = $root
    $relative = $full.Substring($root.Length)
    foreach ($part in $relative.Split([System.IO.Path]::DirectorySeparatorChar, [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $current = Join-Path $current $part
        if (-not (Test-Path -LiteralPath $current)) {
            break
        }
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse point is forbidden in bootstrap destination: $current"
        }
    }
}

Assert-NoReparsePath $resolvedHermes
Assert-NoReparsePath $profilesRoot
Assert-NoReparsePath $runtimeRoot

if (-not $PSCmdlet.ShouldProcess($runtimeRoot, 'Download and install pinned private dependencies')) {
    return
}

New-Item -ItemType Directory -Force -Path $runtimeRoot, $downloads, $staging | Out-Null
Assert-NoReparsePath $runtimeRoot
Assert-NoReparsePath $downloads
Assert-NoReparsePath $staging
Set-PrivateAcl $runtimeRoot
try {
    try {
        $bootstrapLockStream = [System.IO.File]::Open($bootstrapLockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    }
    catch {
        throw "Another bootstrap is active or left an unresolved lock: $bootstrapLockPath"
    }
    Get-ChildItem -LiteralPath $runtimeRoot -Directory -Filter '.bootstrap-*' | Where-Object {
        $_.FullName -ne $staging
    } | Remove-Item -Recurse -Force
    $nodeArchive = Fetch-Archive $lock.node
    $nodeSource = Join-Path $staging 'selected\node.exe'
    Extract-PinnedFile $nodeArchive 'node.exe' $nodeSource
    Assert-Hash $nodeSource $lock.node.executable_sha256

    $readyTools = Join-Path $staging 'tools-ready'
    $nodeTarget = Join-Path $readyTools 'node\node.exe'
    New-Item -ItemType Directory -Force -Path (Split-Path $nodeTarget) | Out-Null
    Copy-Item -LiteralPath $nodeSource -Destination $nodeTarget -Force

    $manifest = [ordered]@{
        format_version = 1
        installed_at_utc = [DateTime]::UtcNow.ToString('o')
        profile = $Profile
        lock_sha256 = Get-Sha256 $lockPath
        files = [ordered]@{
            'node/node.exe' = Get-Sha256 $nodeTarget
        }
        archives = [ordered]@{
            $lock.node.archive = $lock.node.archive_sha256
        }
    }
    $readyManifest = Join-Path $readyTools 'install-manifest.json'
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $readyManifest -Encoding utf8
    $previousTools = Join-Path $runtimeRoot ('.tools-previous-' + [Guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $toolsRoot) {
        Move-Item -LiteralPath $toolsRoot -Destination $previousTools
    }
    try {
        Move-Item -LiteralPath $readyTools -Destination $toolsRoot
    }
    catch {
        if ((Test-Path -LiteralPath $previousTools) -and -not (Test-Path -LiteralPath $toolsRoot)) {
            Move-Item -LiteralPath $previousTools -Destination $toolsRoot
        }
        throw
    }
    if (Test-Path -LiteralPath $previousTools) {
        Remove-Item -LiteralPath $previousTools -Recurse -Force
    }
    Get-ChildItem -LiteralPath $downloads -File | Where-Object {
        $_.Name -ne $lock.node.archive
    } | Remove-Item -Force
    foreach ($obsolete in @('deletion-plans', 'cua-instances', 'logs')) {
        $obsoletePath = Join-Path $runtimeRoot $obsolete
        if (Test-Path -LiteralPath $obsoletePath) {
            Remove-Item -LiteralPath $obsoletePath -Recurse -Force
        }
    }
    [pscustomobject]@{ status = 'installed'; profile = $Profile; runtime_root = $runtimeRoot; manifest = $manifestPath } | ConvertTo-Json -Compress
}
finally {
    if ($null -ne $bootstrapLockStream) {
        $bootstrapLockStream.Dispose()
        if (Test-Path -LiteralPath $bootstrapLockPath) {
            Remove-Item -LiteralPath $bootstrapLockPath -Force
        }
    }
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}
