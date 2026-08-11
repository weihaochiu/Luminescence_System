$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backupDir = Join-Path $repoRoot "backup"

Set-Location $repoRoot

Write-Host "Fetching latest origin/main..."

git fetch origin main

if ($LASTEXITCODE -ne 0) {
    throw "git fetch origin main failed. Backup and push aborted."
}

if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMddHHmm"
$backupFile = Join-Path $backupDir "backup_$timestamp.zip"

Write-Host "Creating backup from origin/main..."

git archive --format=zip --output="$backupFile" origin/main

if ($LASTEXITCODE -ne 0) {
    throw "git archive failed. Backup and push aborted."
}

if (-not (Test-Path $backupFile)) {
    throw "Backup file was not created. Push aborted."
}

$size = (Get-Item $backupFile).Length

if ($size -le 0) {
    throw "Backup file is empty. Push aborted."
}

$backupFiles = @(Get-ChildItem -Path $backupDir -Filter "backup_*.zip" -File |
    Sort-Object LastWriteTime -Descending)

$oldBackups = @($backupFiles | Select-Object -Skip 10)

foreach ($oldBackup in $oldBackups) {
    Write-Host "Removing old backup: $($oldBackup.FullName)"
    Remove-Item -LiteralPath $oldBackup.FullName -Force
}

$remainingBackups = @(Get-ChildItem -Path $backupDir -Filter "backup_*.zip" -File)

if ($remainingBackups.Count -gt 10) {
    throw "Backup rotation failed: more than 10 backup files remain."
}

Write-Host ""
Write-Host "Backup completed successfully."
Write-Host "Backup file: $backupFile"
Write-Host "Size: $size bytes"
Write-Host "Backup files retained: $($remainingBackups.Count)"
