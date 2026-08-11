<#
    Reges bootstrap.

    Finds a usable Python, offers to install one if absent, then hands off to
    the wizard. Everything after this point is Python -- this file exists only
    to solve the chicken-and-egg problem of "you need Python to run the
    installer that installs things".

        irm https://<your-host>/bootstrap.ps1 | iex
        # or, from a clone:
        powershell -ExecutionPolicy Bypass -File install\bootstrap.ps1
#>

$ErrorActionPreference = 'Stop'
$MinPython = [version]'3.11'

function Say($msg, $color = 'Gray') { Write-Host "  $msg" -ForegroundColor $color }

Write-Host ''
Write-Host '  R.E.G.E.S' -ForegroundColor Cyan
Say 'speak. route. remember. repeat.'
Write-Host ''

# --- locate python -------------------------------------------------------- #
$python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    try {
        $raw = & $candidate -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $raw) {
            $ver = [version]($raw.Trim())
            if ($ver -ge $MinPython) {
                $python = $candidate
                Say "Python $ver via '$candidate'" 'Green'
                break
            }
            Say "Found Python $ver via '$candidate' -- need $MinPython+" 'Yellow'
        }
    } catch { }
}

if (-not $python) {
    Say 'No suitable Python found.' 'Yellow'
    Write-Host ''
    $answer = Read-Host '  Install Python 3.12 via winget now? (Y/n)'
    if ($answer -eq '' -or $answer -match '^[Yy]') {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            Say 'winget is not available on this machine.' 'Red'
            Say 'Install Python 3.11+ manually from python.org, then re-run this script.' 'Red'
            exit 1
        }
        Say 'Installing Python 3.12 (this takes a minute)...'
        winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        Say 'Installed. Close this window, open a NEW terminal, and re-run.' 'Green'
        Say 'The new terminal is required -- PATH changes do not apply to this one.' 'Yellow'
        exit 0
    }
    Say 'Cannot continue without Python.' 'Red'
    exit 1
}

# --- locate the wizard ---------------------------------------------------- #
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$wizard = Join-Path $root 'install\wizard.py'
if (-not (Test-Path $wizard)) {
    Say "wizard.py not found at $wizard" 'Red'
    Say 'Run this from inside the cloned repository.' 'Red'
    exit 1
}

# --- optional extras ------------------------------------------------------ #
Write-Host ''
Say 'Voice needs two extra packages (sounddevice, keyboard).'
Say 'Skip this if you only want the HUD and typed intents.'
Write-Host ''
$answer = Read-Host '  Install voice dependencies? (y/N)'
if ($answer -match '^[Yy]') {
    & $python -m pip install --quiet --upgrade pip
    & $python -m pip install --quiet sounddevice keyboard
    if ($LASTEXITCODE -eq 0) { Say 'Voice dependencies installed.' 'Green' }
    else { Say 'pip failed -- voice will be unavailable until you fix this.' 'Yellow' }
}

Write-Host ''
& $python $wizard @args
exit $LASTEXITCODE
