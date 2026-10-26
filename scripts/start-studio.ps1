param([int]$Port=8765, [switch]$BrowserTab)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$pythonExe=Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run uv sync --locked in the project first.' }
$url="http://127.0.0.1:$Port"
$running=$false
try {
    $response=Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 2
    if ($response.application -ne 'rezak-studio') { throw 'Port is used by another application.' }
    $running=$true
} catch {
    if ($_.Exception.Message -eq 'Port is used by another application.') { throw }
}
if (-not $running) {
    $logDirectory=Join-Path $projectRoot 'data\app'
    New-Item -ItemType Directory -Force $logDirectory | Out-Null
    Start-Process -FilePath $pythonExe -ArgumentList @('-m','rezak.desktop','--port',"$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'server.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'server.stderr.log')
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $response=Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 2; if ($response.application -eq 'rezak-studio') { $running=$true; break } } catch { }
    }
    if (-not $running) { throw 'Studio failed to start. Check data/app/server.stderr.log.' }
}
$browserCandidates=@(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe"
)
$browserExe=$browserCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($browserExe -and -not $BrowserTab) {
    Start-Process -FilePath $browserExe -ArgumentList @("--app=$url",'--window-size=1440,960')
} else {
    Start-Process $url
}
Write-Output "Rezak Studio: $url"
