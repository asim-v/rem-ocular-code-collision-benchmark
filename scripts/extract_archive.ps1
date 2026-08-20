[CmdletBinding()]
param(
    [string]$Archive = (Join-Path $PSScriptRoot "../data/raw/Dream Database from Donders.rar"),
    [string]$Destination = (Join-Path $PSScriptRoot "../data/extracted")
)

$ErrorActionPreference = "Stop"

$archivePath = [System.IO.Path]::GetFullPath($Archive)
$destinationPath = [System.IO.Path]::GetFullPath($Destination)

if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw "Archive not found: $archivePath"
}

New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null

Write-Host "Testing archive before extraction"
& tar.exe -tf $archivePath | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The installed tar/libarchive could not read the RAR archive"
}

Write-Host "Extracting into $destinationPath"
& tar.exe -xf $archivePath -C $destinationPath
if ($LASTEXITCODE -ne 0) {
    throw "Archive extraction failed with exit code $LASTEXITCODE"
}

Write-Host "Extraction complete"
