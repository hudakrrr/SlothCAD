"""Build (or find) the small native viewport module.

Linux builds it with the system C compiler during installation. Windows ships a
prebuilt DLL in .native/ (cross-compiled from the same source, see
build_windows_dll.sh); if that file is missing, a compiler on PATH (gcc, clang or
MSVC's cl) is used. Without either, SlothCAD falls back to the slower NumPy
rasterizer, so this module is an accelerator, never a requirement.
"""
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
WINDOWS=sys.platform=='win32'


def source_digest():
    # Normalise line endings so a Windows checkout (CRLF) finds the prebuilt DLL.
    return hashlib.sha256((ROOT/'native_raster.c').read_bytes().replace(b'\r\n',b'\n')).hexdigest()[:12]


def machine():
    name=platform.machine().lower()
    return {'amd64':'x86_64','x64':'x86_64','arm64':'aarch64'}.get(name,name)


def library_path():
    return ROOT/'.native'/f'raster-{machine()}-{source_digest()}{".dll" if WINDOWS else ".so"}'


def _compile_windows(path,temp):
    source=str(ROOT/'native_raster.c')
    for name in ('gcc','clang'):
        compiler=shutil.which(name)
        if compiler:
            subprocess.run([compiler,'-O3','-std=c99','-shared',source,'-o',str(temp)],check=True,capture_output=True,text=True,timeout=60)
            return
    compiler=shutil.which('cl')
    if compiler:
        subprocess.run([compiler,'/nologo','/O2','/LD',source,'/Fe:'+str(temp),'/Fo:'+str(temp.with_suffix('.obj'))],check=True,capture_output=True,text=True,timeout=60,cwd=str(path.parent))
        return
    raise RuntimeError('The fast viewport module is not available and no C compiler was found; '
                       'SlothCAD uses its slower built-in renderer instead.')


def build():
    path=library_path()
    if path.exists():return path
    path.parent.mkdir(exist_ok=True)
    temp=path.with_name(path.stem+'.tmp'+path.suffix)
    try:
        if WINDOWS:
            _compile_windows(path,temp)
        else:
            compiler=shutil.which('cc') or shutil.which('gcc')
            if not compiler:raise RuntimeError('A C compiler is needed. On Fedora, install gcc and rerun the installer.')
            subprocess.run([compiler,'-O3','-std=c99','-shared','-fPIC',str(ROOT/'native_raster.c'),'-lm','-o',str(temp)],check=True,capture_output=True,text=True,timeout=30)
        temp.replace(path)
    finally:
        for leftover in (temp,temp.with_suffix('.obj'),temp.with_suffix('.lib'),temp.with_suffix('.exp')):
            if leftover.exists():leftover.unlink()
    return path


if __name__=='__main__':
    try:print('Native viewport ready:',build().name)
    except Exception as e:print(str(e),file=sys.stderr);sys.exit(1)
