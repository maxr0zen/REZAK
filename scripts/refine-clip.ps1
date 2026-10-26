param([Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$JobId)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding $false
$OutputEncoding=[Console]::OutputEncoding
Push-Location (Split-Path $PSScriptRoot -Parent)
$pipelineLock=$null
$ownsPipeline=$false
$loadedModel=$false
try {
    $pipelineLock=[System.IO.File]::Open((Join-Path (Get-Location) '.tools/pipeline.lock'),'OpenOrCreate','ReadWrite','None')
    $ownsPipeline=$true
    function Event([string]$Stage,[object]$Progress,[string]$Message,[bool]$Owned=$false){
        Write-Output ('[REZAK_EVENT]'+(@{stage=$Stage;progress=$Progress;message=$Message;pipeline_owned=$Owned}|ConvertTo-Json -Compress))
    }
    function Compose([string[]]$Arguments){
        & docker compose @Arguments
        if($LASTEXITCODE -ne 0){throw "docker compose failed (exit $LASTEXITCODE)"}
    }
    Event 'prepare' 1 'Задание и план конкретной нарезки подготовлены' $true
    Event 'asr' 1 'Используется сохранённая расшифровка исходной записи'
    $request=Get-Content -LiteralPath "data/app/edits/$JobId.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $sourceId=$request.plan.source_id
    if($sourceId -notmatch '^[a-zA-Z0-9_-]{1,80}$'){throw 'Invalid source id'}
    & docker compose run --rm --entrypoint sh app -c "test -f /data/analysis/$sourceId/edit-$JobId/plan.json"
    $cachedPlan=$LASTEXITCODE -eq 0
    if(-not $cachedPlan){
        Event 'llm' $null 'Загрузка Bonsai2 для доработки по заданию'
        Compose -Arguments @('--profile','llm','up','-d','--wait','--wait-timeout','600','bonsai')
        $loadedModel=$true
    } else {
        Event 'llm' 1 'План доработки сохранён; повторная генерация не требуется'
    }
    $edits=(Join-Path (Get-Location) 'data/app/edits')
    $code=(Join-Path (Get-Location) 'rezak')
    Compose -Arguments @('run','--rm','--name',"rezak-refine-$JobId",'-v',"${edits}:/edits:ro",'-v',"${code}:/app/rezak:ro",'app','refine',"/edits/$JobId.json")
} finally {
    if($ownsPipeline -and $loadedModel){& docker compose --profile llm stop bonsai}
    if($pipelineLock){$pipelineLock.Dispose()}
    Pop-Location
}
