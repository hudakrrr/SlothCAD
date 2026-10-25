@echo off
rem Starts SlothCAD with a console window that shows messages when something goes wrong.
setlocal
set "HERE=%~dp0"
if exist "%HERE%portable.flag" (
  set "SLOTHCAD_CONFIG_DIR=%HERE%data\settings"
  set "SLOTHCAD_RECOVERY_DIR=%HERE%data\recovery"
)
"%HERE%python\python.exe" -X utf8 "%HERE%slothcad_launcher.pyw" %*
if errorlevel 1 pause
