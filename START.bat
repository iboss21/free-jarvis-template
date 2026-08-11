@echo off
REM Reges - one click launch. Finds Python, starts the HUD, opens the browser.
setlocal
cd /d "%~dp0"

where py >nul 2>&1 && (py -3 run.py %* & goto :end)
where python >nul 2>&1 && (python run.py %* & goto :end)

echo Python 3.11+ not found.
echo Install it from https://www.python.org/downloads/ and tick "Add to PATH".
pause
:end
endlocal
