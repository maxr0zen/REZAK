function Test-RezakMiniMax {
    $providerLine = docker compose config --environment | Where-Object { $_ -cmatch '^REZAK_LLM_PROVIDER=' }
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve Docker Compose model provider' }
    return $providerLine -ceq 'REZAK_LLM_PROVIDER=minimax'
}
