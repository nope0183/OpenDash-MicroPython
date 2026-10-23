param(
    [string]$Port = "COM5",
    [string]$Mpremote = "mpremote"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "opendash"

if (-not (Get-Command $Mpremote -ErrorAction SilentlyContinue)) {
    throw "mpremote not found. Install it with: python -m pip install mpremote"
}

# Creating an existing directory returns an error; it is safe to ignore.
try {
    & $Mpremote connect $Port fs mkdir ":opendash" 2>$null | Out-Null
} catch {
}

Get-ChildItem (Join-Path $source "*.py") | ForEach-Object {
    Write-Host "Uploading opendash/$($_.Name)"
    & $Mpremote connect $Port fs cp $_.FullName ":opendash/$($_.Name)"
    if ($LASTEXITCODE -ne 0) { throw "mpremote failed for $($_.Name)" }
}

foreach ($name in @("boot.py", "main.py")) {
    Write-Host "Uploading $name"
    & $Mpremote connect $Port fs cp (Join-Path $root $name) ":$name"
    if ($LASTEXITCODE -ne 0) { throw "mpremote failed for $name" }
}

Write-Host "Resetting board on $Port"
& $Mpremote connect $Port reset
