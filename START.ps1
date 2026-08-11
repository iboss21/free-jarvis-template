# Reges - one command launch.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Host "Python 3.11+ not found. Install from python.org and tick 'Add to PATH'."
    exit 1
}
& $py.Source run.py @args
