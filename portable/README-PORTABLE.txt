SlothCAD - portable, offline package (64-bit Windows 10 / 11)
=============================================================

Everything SlothCAD needs (Python and all libraries) is in this folder. No internet, no installer,
no administrator rights.

RUN IT WITHOUT INSTALLING
  Extract the zip anywhere (a short path such as C:\SlothCAD is best; a USB stick works) and
  double-click  SlothCAD.vbs.
  Settings and autosaves stay in the "data" folder next to it, so the folder can be moved or copied.
  If it does not start, use "SlothCAD (with console).bat": it shows the error message.

INSTALL IT (still offline)
  Double-click  "Install SlothCAD (offline).bat". It copies SlothCAD to
  %LOCALAPPDATA%\Programs\SlothCAD, adds Start menu and desktop shortcuts, opens .fcad files with
  SlothCAD and lists it in Settings > Apps (Uninstall there).

If Windows reports a missing DLL, install the Microsoft Visual C++ Redistributable (x64) once.
License: see LICENSE and THIRD-PARTY-NOTICES.md.
