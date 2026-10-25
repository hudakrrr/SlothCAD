# SlothCAD

A parametric CAD program for Windows and Linux, built with Python, Qt (PySide6) and
the OpenCASCADE geometry kernel (through CadQuery).

Draw a constrained 2D sketch, turn it into a solid, and keep editing: every feature
stays in a history you can go back to. SlothCAD is meant to feel familiar if you know
Fusion or FreeCAD, but lighter and quicker to learn.

## What it can do

- **Sketching:** lines, arcs, circles, ellipses, splines, text, constraints (arcs and circles
  included: tangent, equal, concentric, radius/diameter) and dimensions, mirror and pattern tools,
  box selection. Fully constrained geometry is drawn in green; conflicts name the contradicting
  constraints.
- **Parameters:** named values for the whole project. Every number box of a feature, and every
  sketch dimension, accepts expressions such as `plate_width / 2 + 1`.
- **Solids:** extrude (one side, two sides, symmetric, thin wall), revolve, sweep (with guide
  curve), loft, hole (metric standard sizes, holes at sketch points), shell, fillet (constant or
  variable), chamfer (equal, two distances, distance and angle), draft, press/pull, patterns,
  threads, coils, ribs and more.
- **Surfaces, assemblies and body tools:** patch, stitch, thicken, joints and face-to-face mates,
  parts inserted from other project files, combine, split.
- **Inspect:** measure, mass properties with material densities, interference check, bill of
  materials, section view, perspective camera, saved camera views, see-through bodies.
- **Several projects at once** in tabs, with copy and paste of features between them.
- **Exchange:** STEP (names and colours), IGES, STL/OBJ/3MF meshes, DXF; export to STEP, STL, 3MF,
  glTF, DXF and drawing sheets (DXF/SVG with hidden-line views); native `.fcad` project files.
- **English and Hungarian** interface, light and dark themes.

## Download

Get the latest version from the [Releases page](../../releases/latest) or from
[komoj.hu/slothcad](https://komoj.hu/slothcad/), unzip it, then install as below.

## Install and run

| | Windows 10/11 (x86_64) | Linux (x86_64) |
|---|---|---|
| Install | double-click `Install SlothCAD.bat` | `./install-linux.sh` |
| Run | `SlothCAD.bat` or the Start menu entry | application menu entry, or `slothcad` |
| Update | run the newer installer again | run the newer installer again |
| Uninstall | Settings > Apps | `~/.local/share/slothcad/uninstall-linux.sh` |

The folder is only an installer: it copies SlothCAD to its own folder (Windows: `%LOCALAPPDATA%\Programs\SlothCAD`,
Linux: `~/.local/share/slothcad`), adds an application-menu entry with the icon and sets up its own Python
environment; nothing else needs to be installed. Running a newer installer updates the installed copy and keeps
your projects and settings.
More detail: [source/README.md](source/README.md).

## Project layout

```
Install SlothCAD.bat, install-*.ps1/sh, uninstall-*   installers and uninstallers
source/                                               the program (Python), examples, assets
source/tests/                                         automated tests
portable/                                             files for the offline Windows build (source/tools/build_portable.py)
```

To run the tests: `cd source` then `python validation_runner.py`
(or `python -m unittest discover -s tests`).

## License

[MIT](LICENSE). SlothCAD is free and open-source software. It is built on Qt for
Python (LGPL), CadQuery (Apache-2.0) and OpenCASCADE (LGPL), which keep their own licenses.
The tool icons are based on [Iconoir](https://github.com/iconoir-icons/iconoir) (MIT); see
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
