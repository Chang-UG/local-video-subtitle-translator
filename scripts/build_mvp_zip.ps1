param(
    [string]$Name = "Transcripting-MVP",
    [switch]$IncludeModel
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$staging = Join-Path $root "_dist\$Name"
$zipPath = Join-Path $root "_dist\$Name.zip"

if (Test-Path $staging) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
New-Item -ItemType Directory -Path $staging | Out-Null

$files = @(
    "main.py",
    "README.md",
    "DISTRIBUTION_MVP.md",
    "environment.yml",
    "requirements.txt",
    "install_env.bat",
    "run_gui.bat"
)

foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $root $file) -Destination $staging
}

New-Item -ItemType Directory -Path (Join-Path $staging "scripts") | Out-Null
$scriptFiles = @(
    "process_bilingual_subs.py",
    "transcribe.py",
    "translate.py",
    "make_srt.py",
    "render_video.py",
    "clean_recording.py"
)

foreach ($file in $scriptFiles) {
    Copy-Item -LiteralPath (Join-Path $root "scripts\$file") -Destination (Join-Path $staging "scripts")
}

foreach ($dir in @("input", "output", "transcript", "audio", "dub", "models")) {
    New-Item -ItemType Directory -Path (Join-Path $staging $dir) | Out-Null
}

if ($IncludeModel) {
    Get-ChildItem -LiteralPath (Join-Path $root "models") -Filter "*.gguf" -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $staging "models")
    }
}

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $staging -DestinationPath $zipPath

Write-Host "Wrote $zipPath"
