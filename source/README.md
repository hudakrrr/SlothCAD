# SlothCAD

Parametric CAD on CadQuery/OpenCASCADE and Qt (PySide6). One source tree for
64-bit **Windows 10/11** and **Linux** (x86_64).

## Folder layout

```
SlothCAD/                      the folder you download
  Install SlothCAD.bat         Windows: double-click to install
  install-windows.ps1          Windows installer (started by the .bat)
  uninstall-windows.ps1        Windows uninstaller (also in Settings > Apps)
  SlothCAD.bat                 Windows: start with a console window
  slothcad_launcher.pyw        Windows: start-up wrapper used by the Start menu shortcut
  install-linux.sh             Linux installer (installs to ~/.local/share/slothcad, also updates)
  uninstall-linux.sh           Linux uninstaller (copied to the install folder)
  source/                      all program files: this README, the code, tests, examples, assets
```

| | Windows | Linux |
|---|---|---|
| Install | `Install SlothCAD.bat` | `./install-linux.sh` |
| Run | `SlothCAD.bat` or the Start menu | `slothcad` (or the application menu) |
| Tests | `cd source` then `..\.venv\Scripts\python.exe validation_runner.py` | `cd ~/.local/share/slothcad/source && ../.venv/bin/python validation_runner.py` |
| Fast viewport | prebuilt DLL in `source/.native/` | compiled during install (needs gcc) |

All CAD/UI code is shared. OS differences live in `platform_support.py`,
`build_renderer.py`, `recovery.py` and the install/launch scripts.
The software renderer is used automatically if the native module is unavailable
(`SLOTHCAD_RENDERER=software` forces it).


## License

SlothCAD is free and open-source software, released under the [GNU General Public License v3.0](LICENSE):
you may use, study, change and share it. If you share it or a changed version, you must
share the source code too, under the same license, so it can't be made closed source.

It is built on other open-source projects: Qt for Python (PySide6, LGPL), CadQuery
(Apache-2.0) and OpenCASCADE (LGPL). They are installed as separate libraries and
keep their own licenses.


## Icons

The tool icons are in `assets/icons/` (PNG, one light and one `-dark` file per tool). Most come from
[Iconoir](https://github.com/iconoir-icons/iconoir) (MIT) and the rest are drawn in the same style;
see `THIRD-PARTY-NOTICES.md`. `tools/build_icon_pack.py` rebuilds the folder.

To use your own icons, put PNG files named after the tools (for example `extrude.png` and
`extrude-dark.png`) into the `SlothCAD/icons` folder of your user data directory
(`%LOCALAPPDATA%\SlothCAD\icons` on Windows, `~/.local/share/SlothCAD/icons` on Linux), or point
`SLOTHCAD_ICON_DIR` at a folder. Those files win over the built-in ones; tools without a file keep
the built-in icon. Set `SLOTHCAD_ICON_DIR=none` to use only the built-in vector icons.
