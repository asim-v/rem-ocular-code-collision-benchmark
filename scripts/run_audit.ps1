[CmdletBinding()]
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

Push-Location $repositoryRoot
try {
    & (Join-Path $PSScriptRoot "fetch_figshare.ps1")
    $extractionSentinel = Join-Path $repositoryRoot "data/extracted/Records.csv"
    if (-not (Test-Path -LiteralPath $extractionSentinel -PathType Leaf)) {
        & (Join-Path $PSScriptRoot "extract_archive.ps1")
    } else {
        Write-Host "Using existing extraction at data/extracted"
    }
    & $Python (Join-Path $PSScriptRoot "audit_dataset.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Dataset audit failed with exit code $LASTEXITCODE"
    }
    & $Python (Join-Path $PSScriptRoot "audit_release_metadata.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Metadata audit failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
