$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$name = "rag-knowledge-v1-test-pg"
$existing = docker ps -aq --filter "name=^/$name$"
if ($existing) { throw "A test container already exists. Inspect its ownership before reusing it." }
$testPassword = [Guid]::NewGuid().ToString("N")
$previousUrl = $env:TEST_POSTGRES_URL
try {
    docker run -d --rm --name $name --label project=rag-knowledge-v1-test -e POSTGRES_USER=rag_test -e "POSTGRES_PASSWORD=$testPassword" -e POSTGRES_DB=rag_test -p 127.0.0.1:55439:5432 postgres:16-alpine | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not start dedicated test database" }
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        docker exec $name pg_isready -U rag_test -d rag_test *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Test database readiness timed out" }
    $env:TEST_POSTGRES_URL = "postgresql+psycopg://rag_test:$testPassword@127.0.0.1:55439/rag_test"
    & .\.venv\Scripts\python.exe -m pytest -c backend\pytest.ini backend\tests\test_postgres.py -q
    $result = $LASTEXITCODE
} finally {
    $env:TEST_POSTGRES_URL = $previousUrl
    $label = docker inspect --format '{{index .Config.Labels "project"}}' $name 2>$null
    if ($label -eq "rag-knowledge-v1-test") { docker stop $name | Out-Null }
}
exit $result
