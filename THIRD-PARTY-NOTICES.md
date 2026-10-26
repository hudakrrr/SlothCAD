# Third-party notices

SlothCAD itself is released under the GNU General Public License v3.0 (see `LICENSE`). It includes or uses the following
third-party work.

## Iconoir (tool icons)

About two thirds of the tool icons in `source/assets/icons/` are taken, unchanged except for their
stroke colour, from **Iconoir** (https://github.com/iconoir-icons/iconoir). The remaining icons in
that folder were drawn for SlothCAD in the same style and are part of SlothCAD (GPL v3).
`source/tools/build_icon_pack.py` rebuilds the folder and lists which icon comes from where.

```
MIT License

Copyright (c) 2021 Luca Burgio

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Libraries used at run time (not included in this repository)

| Library | License |
|---|---|
| Qt for Python (PySide6) | LGPL-3.0 |
| CadQuery | Apache-2.0 |
| OpenCASCADE Technology | LGPL-2.1 with exception |
| NumPy | BSD-3-Clause |

These are installed into the program's own Python environment by the installer and keep their own licenses.
