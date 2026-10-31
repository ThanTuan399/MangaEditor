@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-HyMT2.ps1" %*
echo.
echo Press any key to close this window...
pause >nul
