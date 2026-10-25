#!/usr/bin/env bash
# Removes SlothCAD: program files, Python environment, menu entry, icon, the 'slothcad'
# command and the .fcad file type. Your projects (.fcad files) are never touched.
# Settings and autosaves are removed only if you say so.
set -uo pipefail
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
TARGET="$DATA_HOME/slothcad"

if pgrep -f "$TARGET/.venv/bin/python" >/dev/null 2>&1; then
  echo 'Close SlothCAD first, then uninstall again.' >&2
  exit 1
fi
read -r -p 'Remove SlothCAD from this computer? Your projects are kept. [y/N] ' answer
[[ $answer == [yY]* ]] || exit 0

rm -f "$DATA_HOME/applications/slothcad.desktop" "$DATA_HOME/mime/packages/slothcad.xml"
rm -f "$DATA_HOME/icons/hicolor/256x256/apps/slothcad.png" "$DATA_HOME/icons/hicolor/512x512/apps/slothcad.png" "$DATA_HOME/icons/hicolor/1024x1024/apps/slothcad.png"
[[ -L $HOME/.local/bin/slothcad ]] && rm -f "$HOME/.local/bin/slothcad"
command -v update-mime-database >/dev/null && update-mime-database "$DATA_HOME/mime" >/dev/null 2>&1
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t -f "$DATA_HOME/icons/hicolor" >/dev/null 2>&1

read -r -p "Also delete SlothCAD's settings and autosaves? (theme, language, recovery files) [y/N] " answer
if [[ $answer == [yY]* ]]; then
  rm -rf "$CONFIG_HOME/SlothCAD" "$CONFIG_HOME/slothcad" "$DATA_HOME/SlothCAD"
fi

cd "$HOME" || exit 1
rm -rf "$TARGET"
echo 'SlothCAD was removed.'
