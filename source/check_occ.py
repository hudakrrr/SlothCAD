"""Checks that VTK and OCP's VTK bindings load, which CadQuery needs at import time.

OCP's IVtkOCC package hides the real error behind "VTK not installed", so this imports
the pieces one by one and prints the actual cause. Exit codes: 0 ok, 2 a Windows DLL
failed to load (usually a missing Visual C++ Redistributable), 1 anything else.
"""
import sys
import traceback


def main():
    try:
        import vtk  # noqa: F401
        import OCP  # noqa: F401
        from OCP.OCP.IVtkOCC import IVtkOCC_Shape  # noqa: F401  (the compiled module, unwrapped)
    except BaseException as error:
        text = traceback.format_exc()
        print(text, file=sys.stderr)
        return 2 if 'DLL load failed' in text or isinstance(error, OSError) else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
