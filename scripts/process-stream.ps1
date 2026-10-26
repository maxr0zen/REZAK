param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9_-]{1,80}$')][string]$SourceId,
    [switch]$NoRender,
    [switch]$ReselectShorts,
    [string]$CurateRequest='',
    [ValidateSet('both','vertical','horizontal')][string]$OutputProfile='both'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = [Console]::OutputEncoding
Push-Location (Split-Path $PSScriptRoot -Parent)
$pipelineLock = $null
$ownsPipeline = $false
try {
    $lockPath = Join-Path (Get-Location) '.tools/pipeline.lock'
    New-Item -ItemType Directory -Force .tools | Out-Null
    # Exclusive host lock prevents two runs from loading both models concurrently.
    $pipelineLock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
    $ownsPipeline = $true
    function Write-ProgressEvent {
        param([string]$Stage, [object]$Progress, [string]$Message, [bool]$Owned=$false)
        if ($env:REZAK_PROGRESS -eq '1') {
            Write-Output ('[REZAK_EVENT]'+(@{stage=$Stage;progress=$Progress;message=$Message;pipeline_owned=$Owned} | ConvertTo-Json -Compress))
        }
    }
    Write-ProgressEvent 'prepare' 0.9 'Управление GPU-пайплайном получено' $true
    function Invoke-Compose {
        param([string[]]$ComposeArgs)
        & docker compose @ComposeArgs
        if ($LASTEXITCODE -eq 137) { throw 'Контейнер остановлен с кодом 137: возможна нехватка памяти. Сохранённые части ASR будут использованы при повторном запуске.' }
        if ($LASTEXITCODE -ne 0) { throw "docker compose failed (exit $LASTEXITCODE)" }
    }
    if (-not (Test-Path "data/sources/$SourceId.mp4")) { throw 'Put the MP4 into data/sources first' }
    Invoke-Compose -ComposeArgs @('--profile','llm','stop','bonsai')
    $setupName = @(); $asrName = @()
    if ($env:REZAK_JOB_ID) {
        $setupName = @('--name',"rezak-asr-setup-$env:REZAK_JOB_ID")
        $asrName = @('--name',"rezak-asr-$env:REZAK_JOB_ID")
    }
    if (-not $ReselectShorts -and -not $CurateRequest) {
    Invoke-Compose -ComposeArgs (@('--profile','asr','run','--rm')+$setupName+@('asr','download'))
    Write-ProgressEvent 'prepare' 1 'Источник и модель распознавания готовы'
    Write-ProgressEvent 'asr' 0 'Запуск распознавания в отдельном GPU-контейнере'
    Invoke-Compose -ComposeArgs (@('--profile','asr','run','--rm')+$asrName+@('asr','transcribe',$SourceId))
    Write-ProgressEvent 'asr' 1 'Распознавание завершено; память GPU освобождена'
    } else { Write-ProgressEvent 'asr' 1 'Используется готовая расшифровка; Whisper не запускается' }
    Write-ProgressEvent 'llm' $null 'Загрузка Bonsai2. Точный процент загрузки неизвестен.'
    Invoke-Compose -ComposeArgs @('--profile','llm','up','-d','--wait','--wait-timeout','600','bonsai')
    $codePath = Join-Path (Get-Location) 'rezak'
    $analysisArgs = @('run','--rm','-v',"${codePath}:/app/rezak:ro",'app','analyze',$SourceId)
    if ($env:REZAK_JOB_ID) {
        $analysisArgs = @('run','--rm','--name',"rezak-analysis-$env:REZAK_JOB_ID",'-v',"${codePath}:/app/rezak:ro",'app','analyze',$SourceId)
    }
    if ($ReselectShorts) { $analysisArgs[$analysisArgs.Count-2]='shorts' }
    if ($CurateRequest) {
        $editsPath=Join-Path (Get-Location) 'data/app/edits'
        $analysisArgs=@('run','--rm','--name',"rezak-analysis-$env:REZAK_JOB_ID",'-v',"${codePath}:/app/rezak:ro",'-v',"${editsPath}:/edits:ro",'app','curate',"/edits/$CurateRequest.json")
    }
    $analysisArgs += @('--profile',$OutputProfile)
    if (-not $NoRender) { $analysisArgs += '--render' }
    try {
        Invoke-Compose -ComposeArgs $analysisArgs
    } catch {
        $modelId = & docker compose --profile llm ps -aq bonsai
        if ($modelId) {
            $modelState = & docker inspect --format '{{json .State}}' $modelId
            if ($LASTEXITCODE -eq 0) {
                $state = $modelState | ConvertFrom-Json
                if ($state.OOMKilled) { throw 'Bonsai2 остановлена из-за превышения лимита RAM. Расшифровка и проверенные окна сохранены; повтор продолжит анализ с них.' }
            }
        }
        throw
    }
} finally {
    # Leave GPU free after either success or failure. No volumes are deleted.
    if ($ownsPipeline) { & docker compose --profile llm stop bonsai }
    if ($pipelineLock) { $pipelineLock.Dispose() }
    Pop-Location
}
