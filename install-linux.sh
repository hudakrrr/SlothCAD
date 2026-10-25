#!/usr/bin/env bash
# SlothCAD installer for 64-bit Linux (Fedora/RHEL, Debian/Ubuntu, Arch, openSUSE).
#
# This folder is only the installer. Run it with  ./install-linux.sh  and it
#   1. installs the system libraries Qt and OpenGL need (asks for sudo once),
#   2. copies SlothCAD to  ~/.local/share/slothcad  (own Python environment inside),
#   3. adds an application-menu entry with the SlothCAD icon, a  slothcad  command
#      in ~/.local/bin and the .fcad file type,
#   4. registers an uninstaller:  ~/.local/share/slothcad/uninstall-linux.sh
# No root rights are needed for the SlothCAD files themselves; once installed, this
# folder can be deleted. Running a newer installer updates SlothCAD in place: your
# projects and settings are kept, the Python packages are brought up to date.
#
# Environment:  SLOTHCAD_SKIP_TESTS=1 skips the quick check at the end,
#               SLOTHCAD_FULL_TESTS=1 runs the whole test suite instead.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SRC="$HERE/source"
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
TARGET="$DATA_HOME/slothcad"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$DATA_HOME/applications"

say() { printf '\033[36m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[[ $(uname -m) == x86_64 ]] || fail 'SlothCAD currently supports x86_64 only.'
[[ $(id -u) -ne 0 ]] || fail 'Run the installer as your normal user (it asks for sudo itself); SlothCAD is installed for one user.'
[[ -f "$SRC/app.py" ]] || fail "Run this from the SlothCAD installer folder (the one with the \"source\" folder)."

new_version=$(sed -n "s/^VERSION='\([^']*\)'.*/\1/p" "$SRC/app.py" | head -n1)
old_version=$(sed -n "s/^VERSION='\([^']*\)'.*/\1/p" "$TARGET/source/app.py" 2>/dev/null | head -n1 || true)
if [[ -n $old_version ]]; then
  say "Updating SlothCAD $old_version -> $new_version in $TARGET"
else
  say "Installing SlothCAD $new_version to $TARGET"
fi

# ------------------------------------------------------------ system libraries ----
# Qt/xcb and OpenGL runtime libraries, plus a C compiler for the fast viewport module.
install_system_packages() {
  if command -v dnf >/dev/null; then
    sudo dnf install -y gcc python3.12 python3-pip libxcb xcb-util-cursor xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil libX11-xcb libxkbcommon-x11 libglvnd-glx mesa-dri-drivers mesa-libEGL fontconfig
  elif command -v apt-get >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y gcc python3 python3-venv python3-pip libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 libxcb-shape0 libxcb-xkb1 libxkbcommon-x11-0 libgl1 libegl1 libglx-mesa0 mesa-utils fontconfig
  elif command -v pacman >/dev/null; then
    sudo pacman -S --needed --noconfirm gcc python python-pip libxcb xcb-util-cursor xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil libxkbcommon-x11 libglvnd mesa fontconfig
  elif command -v zypper >/dev/null; then
    sudo zypper install -y gcc python312 python312-pip libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 libxkbcommon-x11-0 libglvnd Mesa-libEGL1 fontconfig
  else
    echo 'Unknown package manager: install gcc, Python 3.12 (with venv) and the Qt xcb/OpenGL libraries yourself, then rerun.' >&2
  fi
}
say 'Installing system libraries (sudo)...'
install_system_packages

# --------------------------------------------------------------- program files ----
# The new program files are copied next to the old ones and swapped in, so an interrupted
# update never leaves a half-written program. The Python environment (.venv) is kept.
mkdir -p "$TARGET"
STAGE="$TARGET/.source-new"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a "$SRC/." "$STAGE/"
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$STAGE/.validation" "$STAGE/validation-results"
rm -rf "$TARGET/source.old"
[[ -d $TARGET/source ]] && mv "$TARGET/source" "$TARGET/source.old"
mv "$STAGE" "$TARGET/source"
rm -rf "$TARGET/source.old"
for name in LICENSE THIRD-PARTY-NOTICES.md README.md uninstall-linux.sh; do
  [[ -f "$HERE/$name" ]] && cp -f "$HERE/$name" "$TARGET/$name"
done
chmod +x "$TARGET/uninstall-linux.sh" 2>/dev/null || true

# ------------------------------------------------------------ python environment ----
# Runs pip with its output in a log and shows a single progress line instead:
# phase, bar, files written and elapsed time.
install_packages() {
  local log; log=$(mktemp)
  "$TARGET/.venv/bin/python" -m pip install --upgrade -r "$TARGET/source/requirements.txt" --disable-pip-version-check --prefer-binary --no-input --progress-bar off >"$log" 2>&1 &
  local pid=$! start=$SECONDS tick=0 spin='|/-\' files=0 written=0
  while kill -0 "$pid" 2>/dev/null; do
    tick=$((tick+1))
    if (( tick % 4 == 1 )); then
      # "|| true": with pipefail a command that finds nothing (yet) must not end the installer.
      files=$(find "$TARGET/.venv/lib" -type f 2>/dev/null | wc -l) || files=0
      written=$(du -sb "$TARGET/.venv/lib" 2>/dev/null | cut -f1) || written=0
    fi
    local wheel percent phase collected filled bar elapsed
    wheel=$(grep -E '^[[:space:]]*(Using cached|Downloading) [^ ]+\.whl \(' "$log" | grep -oE '\([0-9.]+ (kB|MB|GB)\)' |
            awk '{v=substr($1,2)+0; u=$2; if(u=="kB)")v*=1e3; else if(u=="MB)")v*=1e6; else if(u=="GB)")v*=1e9; s+=v} END{printf "%d", s}') || wheel=0
    if grep -q 'Installing collected packages' "$log" && (( ${wheel:-0} > 0 )); then
      percent=$(( 100 * ${written:-0} * 10 / (wheel * 26) ))
      (( percent < 1 )) && percent=1
      (( percent > 99 )) && percent=99
      phase='Unpacking packages'
    else
      collected=$(grep -c '^Collecting ' "$log" || true)
      percent=$(( collected > 30 ? 30 : collected ))
      phase="Resolving and fetching packages ($collected found)"
    fi
    filled=$(( 28 * percent / 100 ))
    bar=$(printf '%*s' "$filled" '' | tr ' ' '#')$(printf '%*s' $((28 - filled)) '' | tr ' ' '-')
    elapsed=$(( SECONDS - start ))
    printf '\r  [%s] %3d%%  %s  %d files  %02d:%02d %s   ' "$bar" "$percent" "$phase" "$files" $((elapsed/60)) $((elapsed%60)) "${spin:$((tick%4)):1}"
    sleep 0.5
  done
  local code=0 elapsed; wait "$pid" || code=$?
  elapsed=$(( SECONDS - start ))
  printf '\r  [%s] 100%%  Done in %02d:%02d                                              \n' "$(printf '%*s' 28 '' | tr ' ' '#')" $((elapsed/60)) $((elapsed%60))
  if (( code != 0 )); then
    echo 'Installing the Python packages failed. Last lines of pip output:' >&2
    tail -n 25 "$log" >&2
    rm -f "$log"; return "$code"
  fi
  rm -f "$log"
}

# CadQuery wheels target Python 3.12; fall back to whatever python3 is installed.
PY=$(command -v python3.12 || command -v python3)
if [[ ! -x $TARGET/.venv/bin/python ]] || ! "$TARGET/.venv/bin/python" -c 'import sys' >/dev/null 2>&1; then
  rm -rf "$TARGET/.venv"
  "$PY" -m venv "$TARGET/.venv"
fi
say 'Installing CadQuery, PySide6 and the other packages (about 400 MB the first time; an update only fetches what changed)...'
rm -f "$TARGET/.venv/.slothcad-installed"
install_packages
touch "$TARGET/.venv/.slothcad-installed"
"$TARGET/.venv/bin/python" "$TARGET/source/build_renderer.py" || echo 'Fast viewport module not built; using the built-in renderer.' >&2

# ------------------------------------------------------ command, menu entry, icon ----
say 'Adding the application-menu entry...'
mkdir -p "$BIN_DIR" "$APPS_DIR" "$DATA_HOME/mime/packages" \
         "$DATA_HOME/icons/hicolor/256x256/apps" "$DATA_HOME/icons/hicolor/512x512/apps" "$DATA_HOME/icons/hicolor/1024x1024/apps"

cat >"$TARGET/slothcad" <<LAUNCHER
#!/usr/bin/env bash
# Starts the installed SlothCAD. Pass a project file to open it.
ROOT="$TARGET"
if [[ ! -f \$ROOT/.venv/.slothcad-installed ]]; then
  echo 'The SlothCAD installation is incomplete. Run the installer again.' >&2
  exit 1
fi
exec "\$ROOT/.venv/bin/python" "\$ROOT/source/app.py" "\$@"
LAUNCHER
chmod +x "$TARGET/slothcad"
ln -sf "$TARGET/slothcad" "$BIN_DIR/slothcad"

cp -f "$SRC/assets/slothcad.png" "$DATA_HOME/icons/hicolor/256x256/apps/slothcad.png"
if [[ -f $SRC/assets/slothcad-1024.png ]]; then
  cp -f "$SRC/assets/slothcad-1024.png" "$DATA_HOME/icons/hicolor/1024x1024/apps/slothcad.png"
  rm -f "$DATA_HOME/icons/hicolor/512x512/apps/slothcad.png"
  rmdir "$DATA_HOME/icons/hicolor/512x512/apps" "$DATA_HOME/icons/hicolor/512x512" 2>/dev/null || true
fi

cat >"$APPS_DIR/slothcad.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=SlothCAD
GenericName=CAD modelling
Comment=Sketch and solid modelling
Exec=$TARGET/slothcad %F
Icon=slothcad
Terminal=false
Categories=Graphics;Engineering;3DGraphics;
MimeType=application/x-slothcad-project;
StartupNotify=true
StartupWMClass=slothcad
DESKTOP
chmod +x "$APPS_DIR/slothcad.desktop"

cat >"$DATA_HOME/mime/packages/slothcad.xml" <<'MIME'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-slothcad-project">
    <comment>SlothCAD project</comment>
    <glob pattern="*.fcad"/>
    <icon name="slothcad"/>
  </mime-type>
</mime-info>
MIME

command -v update-mime-database >/dev/null && update-mime-database "$DATA_HOME/mime" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t -f "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
command -v xdg-mime >/dev/null && xdg-mime default slothcad.desktop application/x-slothcad-project >/dev/null 2>&1 || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

# ------------------------------------------------------------------------ checks ----
# Quick check (a few seconds). SLOTHCAD_FULL_TESTS=1 runs the whole suite (several
# minutes, in parallel); SLOTHCAD_SKIP_TESTS=1 skips all checks.
if [[ ${SLOTHCAD_SKIP_TESTS:-0} != 1 ]]; then
  if [[ ${SLOTHCAD_FULL_TESTS:-0} == 1 ]]; then
    (cd "$TARGET/source" && "$TARGET/.venv/bin/python" validation_runner.py) || printf '\nWarning: some validation tests failed; see %s/source/.validation/ for the logs.\n' "$TARGET" >&2
  else
    "$TARGET/.venv/bin/python" "$TARGET/source/smoke_test.py" || printf '\nWarning: the quick check failed; run (cd %s/source && ../.venv/bin/python validation_runner.py) for details.\n' "$TARGET" >&2
  fi
fi

printf '\n'
if [[ -n $old_version ]]; then say "SlothCAD updated to $new_version. Restart it if it is running."; else say "SlothCAD $new_version is installed."; fi
echo 'Start it from the application menu, or run:  slothcad'
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "(Add $BIN_DIR to your PATH to use the 'slothcad' command; the menu entry works without it.)" ;; esac
echo 'This installer folder can be deleted now.'
