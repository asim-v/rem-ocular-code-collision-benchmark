[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "../data/raw")
)

$ErrorActionPreference = "Stop"

$articleId = 21388722
$fileId = 41037542
$expectedBytes = 2173512831
$expectedMd5 = "7ae6b141f7ecbf29a8b51f75bcdb9b65"
$archiveName = "Dream Database from Donders.rar"

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null

$metadataPath = Join-Path $destinationPath "figshare-article-21388722.json"
$archivePath = Join-Path $destinationPath $archiveName

$metadata = Invoke-RestMethod -Uri "https://api.figshare.com/v2/articles/$articleId"
$metadata | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 $metadataPath

$alreadyVerified = $false
if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    $existingBytes = (Get-Item -LiteralPath $archivePath).Length
    if ($existingBytes -eq $expectedBytes) {
        $existingMd5 = (Get-FileHash -Algorithm MD5 -LiteralPath $archivePath).Hash.ToLowerInvariant()
        $alreadyVerified = $existingMd5 -eq $expectedMd5
    }
}

if (-not $alreadyVerified) {
    Write-Host "Downloading Figshare file $fileId to $archivePath"
    $curlArguments = @(
        "--fail",
        "--location",
        "--retry", "5",
        "--retry-delay", "3",
        "--continue-at", "-",
        "--output", $archivePath,
        "https://ndownloader.figshare.com/files/$fileId"
    )
    & curl.exe @curlArguments
    if ($LASTEXITCODE -ne 0) {
        throw "curl failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "Using existing verified archive at $archivePath"
}

$actualBytes = (Get-Item -LiteralPath $archivePath).Length
if ($actualBytes -ne $expectedBytes) {
    throw "Size mismatch: expected $expectedBytes bytes, found $actualBytes"
}

$actualMd5 = (Get-FileHash -Algorithm MD5 -LiteralPath $archivePath).Hash.ToLowerInvariant()
if ($actualMd5 -ne $expectedMd5) {
    throw "MD5 mismatch: expected $expectedMd5, found $actualMd5"
}

Write-Host "Verified archive: $actualBytes bytes, MD5 $actualMd5"
