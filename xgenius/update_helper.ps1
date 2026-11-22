param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
# A restarted onefile EXE must not reuse the departing process's extraction directory.
$env:PYINSTALLER_RESET_ENVIRONMENT = '1'
$plan = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$target = [IO.Path]::GetFullPath([string]$plan.target)
$source = [IO.Path]::GetFullPath([string]$plan.source)
$next = $target + '.next'
$backup = $target + '.previous'
$replaced = $false
$parentExited = $false
$launched = $null
$health = if ($plan.health) { [IO.Path]::GetFullPath([string]$plan.health) } else { '' }
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
    if ($health) {
        $env:XANTY_UPDATE_HEALTH_FILE = $health
        $launched = Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) -WindowStyle Hidden -PassThru
        $deadline = [DateTime]::UtcNow.AddSeconds(120)
        $ready = $false
        while ([DateTime]::UtcNow -lt $deadline) {
            if ([IO.File]::Exists($health)) {
                $ack = Get-Content -LiteralPath $health -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($ack.version -eq $plan.version) { $ready = $true; break }
            }
            if ($launched.HasExited) { break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $ready) { throw 'The updated application did not finish starting; restoring the previous version' }
    } else {
        Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) -WindowStyle Hidden
    }
    @{ok=$true;version=$plan.version;time=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} | ConvertTo-Json | Set-Content -LiteralPath $plan.result -Encoding UTF8
} catch {
    $failure = $_.Exception.Message
    if ($launched -and -not $launched.HasExited) {
        # Only the process tree started by this helper belongs to this update.
        & "$env:SystemRoot\System32\taskkill.exe" /PID $launched.Id /T /F 2>$null | Out-Null
        $launched.WaitForExit(10000) | Out-Null
    }
    Remove-Item Env:XANTY_UPDATE_HEALTH_FILE -ErrorAction SilentlyContinue
    if ($replaced -and [IO.File]::Exists($backup)) {
        try { [IO.File]::Copy($backup, $target, $true) } catch { $failure += '; rollback: ' + $_.Exception.Message }
    }
    @{ok=$false;version=$plan.version;error=$failure;time=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} | ConvertTo-Json | Set-Content -LiteralPath $plan.result -Encoding UTF8
    if ($parentExited -and [IO.File]::Exists($target)) { Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) -WindowStyle Hidden }
} finally {
    if ($health -and [IO.File]::Exists($health)) { [IO.File]::Delete($health) }
    if ([IO.File]::Exists($next)) { [IO.File]::Delete($next) }
    if ([IO.File]::Exists($source)) { [IO.File]::Delete($source) }
    [IO.File]::Delete($Manifest)
    [IO.File]::Delete($PSCommandPath)
}
