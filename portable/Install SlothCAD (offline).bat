@echo off
rem Installs SlothCAD for the current user (Start menu, desktop shortcut, .fcad files). No internet needed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-offline.ps1"
pause
