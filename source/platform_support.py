"""The few places where Linux and Windows differ, kept in one module.

Everything else in SlothCAD is plain Python, Qt and OpenCASCADE and runs the same
on both systems.
"""
import os
import sys
import time
from pathlib import Path

WINDOWS=sys.platform=='win32'
ROOT=Path(__file__).resolve().parent


def settings():
    """SlothCAD's preferences (theme, language).

    Linux keeps them in ~/.config/SlothCAD/SlothCAD.conf. On Windows Qt would use
    the registry; an .ini file in %APPDATA%\\SlothCAD is easier to inspect, back up
    or delete. SLOTHCAD_CONFIG_DIR redirects both (the test runner uses it so tests
    never touch your real settings).
    """
    from PySide6.QtCore import QSettings
    folder=os.environ.get('SLOTHCAD_CONFIG_DIR')
    if folder:
        Path(folder).mkdir(parents=True,exist_ok=True)
        return QSettings(str(Path(folder)/'SlothCAD.ini'),QSettings.IniFormat)
    if WINDOWS:return QSettings(QSettings.IniFormat,QSettings.UserScope,'SlothCAD','SlothCAD')
    return QSettings('SlothCAD','SlothCAD')


def replace_file(source,target,attempts=20):
    """os.replace that survives Windows' short-lived file locks.

    Antivirus scanners, search indexing and cloud-sync clients briefly open freshly
    written files on Windows; replacing a file during that moment fails with
    PermissionError. Retrying for up to about a second makes saving reliable.
    """
    for attempt in range(attempts):
        try:
            os.replace(source,target);return
        except PermissionError:
            if not WINDOWS or attempt==attempts-1:raise
            time.sleep(.05)


def set_mode(path,mode):
    """chmod where it means something; Windows only knows a read-only flag."""
    if WINDOWS:return
    os.chmod(path,mode)


def launch_command():
    """How a user starts SlothCAD from a terminal, for help texts."""
    return 'SlothCAD.bat' if WINDOWS else 'slothcad'


def software_launch_hint():
    if WINDOWS:return 'Fallback launch: set SLOTHCAD_RENDERER=software, then run SlothCAD.bat'
    return 'Fallback launch: SLOTHCAD_RENDERER=software slothcad'


def app_icon_path():
    path=ROOT/'assets'/'slothcad.png'
    return path if path.exists() else None


def prepare_process():
    """Process-wide setup before the QApplication exists."""
    if WINDOWS:
        try:
            import ctypes
            # Groups SlothCAD's windows under its own taskbar button and icon instead
            # of under python.exe.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SlothCAD.SlothCAD')
        except Exception:
            pass


def native_library_suffix():
    return '.dll' if WINDOWS else '.so'
