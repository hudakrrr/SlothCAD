"""Windows start-up wrapper used by the Start menu and desktop shortcuts.

The shortcuts start SlothCAD with pythonw.exe, which has no console window. That
also means an error during start-up would be invisible, so this wrapper writes it
to a log file and shows it in a message box.
"""
import os
import sys
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parent
# The program files live in the "source" folder next to this wrapper.
SOURCE=ROOT/'source' if (ROOT/'source'/'app.py').exists() else ROOT
sys.path.insert(0,str(SOURCE))


def report(text):
    folder=Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'SlothCAD'
    log=folder/'last-start-error.txt'
    try:
        folder.mkdir(parents=True,exist_ok=True);log.write_text(text,encoding='utf-8')
    except OSError:
        log=None
    message='SlothCAD could not start.\n\n'+text.strip().splitlines()[-1]
    if 'DLL load failed' in text or 'IVtkOCC' in text:
        message+=('\n\nA system library is missing. Installing the Microsoft Visual C++ '
                  'Redistributable (x64) usually fixes this:\nhttps://aka.ms/vs/17/release/vc_redist.x64.exe')
    if log is not None:message+=f'\n\nFull details: {log}'
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,message,'SlothCAD',0x10)
    except Exception:
        print(message,file=sys.stderr)


try:
    # Load VTK first: if it fails here the real error (e.g. "DLL load failed") is reported.
    # Inside CadQuery, OCP hides it and only "cannot import name 'IVtkOCC_Shape'" surfaces.
    import vtk  # noqa: F401
    import app
    app.main()
except SystemExit:
    raise
except BaseException:
    report(traceback.format_exc())
    sys.exit(1)
