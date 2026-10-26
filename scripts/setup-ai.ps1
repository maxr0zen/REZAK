param([string]$ModelDirectory='C:/AI/Bonsai/models', [string]$ModelFile='Ternary-Bonsai-2-27B-PTQ1_0.gguf')
$ErrorActionPreference='Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $path=Join-Path $ModelDirectory $ModelFile
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing Bonsai weights: $path" }
    $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $env:BONSAI_MODEL_DIR=$ModelDirectory
    $env:BONSAI_MODEL_FILE=$ModelFile
    $env:BONSAI_MODEL_REVISION="sha256:$hash/runtime:prism-b10787-73bfe6c/context:4096"
    # No secrets: only model location, content hash and runtime version.
    @("BONSAI_MODEL_DIR=$ModelDirectory","BONSAI_MODEL_FILE=$ModelFile","BONSAI_MODEL_SHA256=$hash","BONSAI_MODEL_REVISION=$env:BONSAI_MODEL_REVISION") | Set-Content -Encoding utf8 .env
    & docker compose --profile asr --profile llm config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Invalid compose config' }
    foreach ($serviceName in @('bonsai','asr','app')) {
        & docker compose --profile asr --profile llm build $serviceName
        if ($LASTEXITCODE -ne 0) { throw "Image build failed: $serviceName" }
    }
    $installerId = (& docker compose --profile llm run --rm -d --entrypoint sleep model-init infinity | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0) { throw 'Bonsai installer container failed' }
    try {
        & docker exec $installerId sh -ec '[ -f /models/model.gguf ] && [ -f /models/model.sha256 ] && [ "$(cat /models/model.sha256)" = "$MODEL_SHA256" ]'
        if ($LASTEXITCODE -ne 0) {
            & docker cp $path "${installerId}:/models/model.gguf.part"
            if ($LASTEXITCODE -ne 0) { throw 'Bonsai model copy failed' }
        }
        & docker exec -e MODEL_PRECOPIED=1 $installerId sh /seed-model.sh
        if ($LASTEXITCODE -ne 0) { throw 'Bonsai model verification failed' }
    } finally {
        & docker stop $installerId | Out-Null
    }
    & docker compose --profile asr run --rm asr download
    if ($LASTEXITCODE -ne 0) { throw 'ASR model download failed' }
} finally { Pop-Location }
