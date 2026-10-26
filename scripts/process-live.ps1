param([Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9_-]{1,80}$')][string]$SourceId,
      [Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9_-]+\.json$')][string]$RequestFile)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = [Console]::OutputEncoding
Push-Location (Split-Path $PSScriptRoot -Parent)
$pipelineLock=$null
try {
    New-Item -ItemType Directory -Force .tools | Out-Null
    $pipelineLock=[System.IO.File]::Open((Join-Path (Get-Location) '.tools/pipeline.lock'),'OpenOrCreate','ReadWrite','None')
    function Invoke-LiveCompose { param([string[]]$Values)
        & docker compose @Values
        if ($LASTEXITCODE -ne 0) { throw "LIVE docker compose failed (exit $LASTEXITCODE)" }
    }
    # CPU ASR can coexist with Bonsai; never unload the model for each live window.
    Invoke-LiveCompose -Values @('--profile','asr','run','--rm','--name',"rezak-asr-setup-$env:REZAK_JOB_ID",'asr-live','download')
    Invoke-LiveCompose -Values @('--profile','asr','run','--rm','--name',"rezak-asr-$env:REZAK_JOB_ID",'asr-live','transcribe',$SourceId)
    Write-Output ('[REZAK_EVENT]'+(@{stage='llm';progress=$null;message='LIVE: загрузка или подключение Bonsai; точный процент неизвестен';pipeline_owned=$true}|ConvertTo-Json -Compress))
    Invoke-LiveCompose -Values @('--profile','llm','up','-d','--wait','--wait-timeout','600','bonsai')
    $codePath=Join-Path (Get-Location) 'rezak'
    $livePath=Join-Path (Get-Location) 'data/live'
    Invoke-LiveCompose -Values @('run','--rm','--name',"rezak-analysis-$env:REZAK_JOB_ID",'-v',"${codePath}:/app/rezak:ro",'-v',"${livePath}:/data/live",'app','live-shorts',"/data/live/requests/$RequestFile",'--render')
} finally {
    if ($pipelineLock) { $pipelineLock.Dispose() }
    Pop-Location
}
