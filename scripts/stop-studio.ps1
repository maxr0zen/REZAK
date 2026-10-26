param([int]$Port=8765)
$ErrorActionPreference='Stop'
$url="http://127.0.0.1:$Port"
$status=Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 3
if ($status.application -ne 'rezak-studio') { throw 'This is not a Rezak service.' }
Invoke-RestMethod -Method Post -Uri "$url/api/shutdown" -Headers @{'X-Rezak-Client'='1'} | Out-Null
Write-Output 'Rezak Studio is shutting down. Saved media are retained.'
