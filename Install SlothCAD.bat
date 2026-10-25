@echo off
rem Double-click to install SlothCAD. No administrator rights are needed.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1" %*
echo.
pause
