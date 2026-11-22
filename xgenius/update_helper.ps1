param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$plan = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$target = [IO.Path]::GetFullPath([string]$plan.target)
$source = [IO.Path]::GetFullPath([string]$plan.source)
$next = $target + '.next'
$backup = $target + '.previous'
$replaced = $false
$parentExited = $false
try {
    if ([IO.Path]::GetExtension($target) -ne '.exe' -or $source -eq $target) { throw 'Invalid update destination' }
    $running = Get-Process -Id ([int]$plan.pid) -ErrorAction SilentlyContinue
    if ($running) { Wait-Process -Id ([int]$plan.pid) -Timeout 120 -ErrorAction Stop }
    $parentExited = $true
    $hasher = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($source)
    try { $digest = ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '') }
    finally { $stream.Dispose(); $hasher.Dispose() }
    if ($digest -ne $plan.sha256) { throw 'Update checksum mismatch' }
    # All paths are resolved absolute file paths; no recursive operations or command interpolation.
    [IO.File]::Copy($source, $next, $true)
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            [IO.File]::Replace($next, $target, $backup, $true)
            $replaced = $true
            break
        } catch {
            if ($attempt -eq 29) { throw }
            Start-Sleep -Milliseconds 1000
        }
    }
    @{ok=$true;version=$plan.version;time=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} | ConvertTo-Json | Set-Content -LiteralPath $plan.result -Encoding UTF8
    Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) -WindowStyle Hidden
} catch {
    $failure = $_.Exception.Message
    if ($replaced -and [IO.File]::Exists($backup)) {
        try { [IO.File]::Copy($backup, $target, $true) } catch { $failure += '; rollback: ' + $_.Exception.Message }
    }
    @{ok=$false;version=$plan.version;error=$failure;time=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} | ConvertTo-Json | Set-Content -LiteralPath $plan.result -Encoding UTF8
    if ($parentExited -and [IO.File]::Exists($target)) { Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) -WindowStyle Hidden }
} finally {
    if ([IO.File]::Exists($next)) { [IO.File]::Delete($next) }
    if ([IO.File]::Exists($source)) { [IO.File]::Delete($source) }
    [IO.File]::Delete($Manifest)
    [IO.File]::Delete($PSCommandPath)
}
