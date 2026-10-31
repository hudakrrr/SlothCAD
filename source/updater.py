"""In-app updates from the GitHub repository.

The check reads only the ``VERSION`` line of ``source/app.py`` on the main branch. Installing
downloads the branch archive, compares it with the installed files and replaces the new and
changed ones (the Python environment and local files are left alone). Changed package
requirements are installed first, so a failed pip run leaves the program untouched.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPOSITORY = 'hudakrrr/SlothCAD'
BRANCH = 'main'
VERSION_URL = f'https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}/source/app.py'
ARCHIVE_URL = f'https://codeload.github.com/{REPOSITORY}/zip/refs/heads/{BRANCH}'
SOURCE = Path(__file__).resolve().parent
ROOT_FILES = ('LICENSE', 'README.md', 'THIRD-PARTY-NOTICES.md')
SKIP_PARTS = {'__pycache__', '.native'}


def parse_version(text):
    """'0.15.1' -> (0, 15, 1); anything unparsable sorts lowest."""
    try:
        return tuple(int(part) for part in str(text).strip().split('.'))
    except ValueError:
        return ()


def enabled():
    # A git checkout is a development copy: never offer to overwrite it.
    return not os.environ.get('SLOTHCAD_NO_UPDATE_CHECK') and not (SOURCE.parent / '.git').exists()


def _get(url, timeout, limit=None):
    request = urllib.request.Request(url, headers={'User-Agent': 'SlothCAD-updater', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(limit) if limit else response.read()


def latest_version(timeout=6.):
    """The version string on GitHub, or None when it cannot be read."""
    text = _get(VERSION_URL, timeout, limit=4096).decode('utf-8', 'replace')
    match = re.search(r"^VERSION\s*=\s*['\"]([0-9.]+)['\"]", text, re.MULTILINE)
    return match.group(1) if match else None


def newer_version(current, timeout=6.):
    """The GitHub version when it is newer than ``current``, else None (also when offline)."""
    try:
        latest = latest_version(timeout)
    except Exception:
        return None
    return latest if latest and parse_version(latest) > parse_version(current) else None


def _plan(archive):
    """[(installed path, new bytes)] for every file that is new or different."""
    names = archive.namelist()
    if not names:
        raise RuntimeError('The downloaded update is empty.')
    prefix = names[0].split('/')[0] + '/'
    if prefix + 'source/app.py' not in names:
        raise RuntimeError('The downloaded update does not contain SlothCAD.')
    changes = []
    for name in names:
        if name.endswith('/') or not name.startswith(prefix):
            continue
        relative = name[len(prefix):]
        parts = relative.split('/')
        if parts[0] == 'source' and len(parts) > 1 and not SKIP_PARTS.intersection(parts):
            target = SOURCE.joinpath(*parts[1:])
        elif len(parts) == 1 and relative in ROOT_FILES:
            target = SOURCE.parent / relative
        else:
            continue
        data = archive.read(name)
        try:
            if target.read_bytes() == data:
                continue
        except OSError:
            pass
        changes.append((target, data))
    return changes


def _install_requirements(data):
    """pip install the new requirements into this environment before any file is replaced."""
    handle, path = tempfile.mkstemp(suffix='.txt', prefix='slothcad-requirements-')
    with os.fdopen(handle, 'wb') as stream:
        stream.write(data)
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        python = sys.executable
        if os.path.basename(python).lower() == 'pythonw.exe':
            python = os.path.join(os.path.dirname(python), 'python.exe')
        done = subprocess.run([python, '-m', 'pip', 'install', '--upgrade', '-r', path, '--disable-pip-version-check',
                               '--prefer-binary', '--no-input'], capture_output=True, text=True, creationflags=flags)
        if done.returncode != 0:
            tail = '\n'.join((done.stdout + done.stderr).strip().splitlines()[-6:])
            raise RuntimeError('Installing the new Python packages failed; nothing was changed.\n\n' + tail)
    finally:
        os.remove(path)


def install(progress=None):
    """Download and apply the update. Returns the number of files replaced or added."""
    def report(done, total, text):
        if progress is not None:
            progress(done, total, text)
    report(0, 0, 'Downloading update…')
    archive = zipfile.ZipFile(io.BytesIO(_get(ARCHIVE_URL, 60.)))
    report(0, 0, 'Comparing files…')
    changes = _plan(archive)
    if not changes:
        return 0
    requirements = next((data for target, data in changes if target == SOURCE / 'requirements.txt'), None)
    if requirements is not None:
        report(0, 0, 'Installing new Python packages…')
        _install_requirements(requirements)
    # Each file is written next to its target and swapped in; replaced files are kept until
    # every swap succeeded, so a failure part way restores the previous program.
    backup = Path(tempfile.mkdtemp(prefix='slothcad-update-backup-'))
    done = []
    try:
        for index, (target, data) in enumerate(changes):
            report(index, len(changes), 'Installing update…')
            target.parent.mkdir(parents=True, exist_ok=True)
            saved = None
            if target.exists():
                saved = backup / str(index)
                shutil.copy2(target, saved)
            staged = target.with_name(target.name + '.update-new')
            try:
                staged.write_bytes(data)
                os.replace(staged, target)
            except Exception:
                staged.unlink(missing_ok=True)
                raise
            done.append((target, saved))
    except Exception:
        for target, saved in reversed(done):
            try:
                if saved is None:
                    target.unlink()
                else:
                    os.replace(saved, target)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
    report(len(changes), len(changes), 'Update installed.')
    return len(changes)


def restart(project=None):
    """Start SlothCAD again the way it was started, reopening ``project`` when given."""
    arguments = [sys.executable, sys.argv[0]] + ([str(project)] if project else [])
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    subprocess.Popen(arguments, close_fds=True, creationflags=flags, start_new_session=os.name != 'nt')
