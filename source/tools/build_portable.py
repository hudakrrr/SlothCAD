"""Builds the portable, offline SlothCAD for 64-bit Windows.

    python tools/build_portable.py [output folder]

The result (default: ``dist/SlothCAD-Portable`` next to the project, plus a .zip of it) holds its own Python, every
library and the program, so it runs, or is installed with ``Install SlothCAD (offline).bat``, with no internet.
Needs internet only while building (the embeddable Python is downloaded once) and the Python environment that
SlothCAD already runs in (its packages are copied, not downloaded again).
"""
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
PROJECT = SOURCE.parent
VERSION = '.'.join(map(str, sys.version_info[:3]))
EMBED_URL = f'https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip'
VC_DLLS = ('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll')
SKIP_PACKAGES = {'pip', 'setuptools', 'wheel', '_distutils_hack', 'pkg_resources'}
SKIP_SOURCE = {'tests', '__pycache__', '.validation', 'validation-results'}


def main():
    if os.name != 'nt':
        sys.exit('The portable build is for Windows.')
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else PROJECT.parent / 'dist' / 'SlothCAD-Portable'
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cache = out.parent / 'cache'
    cache.mkdir(exist_ok=True)
    archive = cache / Path(EMBED_URL).name
    if not archive.exists():
        print('Downloading', EMBED_URL)
        urllib.request.urlretrieve(EMBED_URL, archive)
    python = out / 'python'
    with zipfile.ZipFile(archive) as z:
        z.extractall(python)
    # Search path of the embedded interpreter: its own library zip, the packages, and "import site".
    pth = next(python.glob('python*._pth'))
    pth.write_text(f'{pth.stem}.zip\n.\nLib\\site-packages\n..\\source\nimport site\n', encoding='ascii')
    site = Path(sys.prefix) / 'Lib' / 'site-packages'
    print('Copying packages from', site)
    shutil.copytree(site, python / 'Lib' / 'site-packages',
                    ignore=lambda d, n: [x for x in n if x in SKIP_PACKAGES or x == '__pycache__' or x.endswith('.pyc')
                                         or re.match(r'(pip|setuptools|wheel)-.*\.dist-info', x)])
    system32 = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    for name in VC_DLLS:                  # app-local Visual C++ runtime: no redistributable to install first
        if (system32 / name).exists():
            shutil.copy2(system32 / name, python / name)
    print('Copying SlothCAD')
    shutil.copytree(SOURCE, out / 'source', ignore=lambda d, n: [x for x in n if x in SKIP_SOURCE or x.endswith('.pyc')])
    for name in ('LICENSE', 'THIRD-PARTY-NOTICES.md', 'README.md', 'slothcad_launcher.pyw', 'uninstall-windows.ps1'):
        shutil.copy2(PROJECT / name, out / name)
    for name in ('SlothCAD.vbs', 'SlothCAD (with console).bat', 'Install SlothCAD (offline).bat',
                 'install-offline.ps1', 'README-PORTABLE.txt'):
        shutil.copy2(PROJECT / 'portable' / name, out / name)
    (out / 'portable.flag').write_text('Remove this file to keep settings in the usual user folders instead of in data\\.\n')
    print('Zipping')
    zip_path = shutil.make_archive(str(out), 'zip', out.parent, out.name)
    size = sum(f.stat().st_size for f in out.rglob('*') if f.is_file()) / 1e6
    print(f'Done: {out} ({size:.0f} MB), {zip_path}')


if __name__ == '__main__':
    main()
