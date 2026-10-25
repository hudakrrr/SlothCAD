@echo off
rem Starts SlothCAD with a console window, which shows messages that help when
rem something goes wrong. The Start menu shortcut starts it without a console.
rem Pass a project file to open it:  SlothCAD.bat "C:\path\to\part.fcad"
setlocal
set "HERE=%~dp0"
if not exist "%HERE%.venv\Scripts\python.exe" set "HERE=%LOCALAPPDATA%\Programs\SlothCAD\"
if not exist "%HERE%.venv\Scripts\python.exe" (
  echo SlothCAD is not installed yet. Double-click "Install SlothCAD.bat" first.
  pause
  exit /b 1
)
"%HERE%.venv\Scripts\python.exe" -X utf8 "%HERE%source\app.py" %*
