"""Quick install check (a few seconds): dependencies import, the kernel builds and
saves a part, and the viewport rasterizer works. The full suite is
validation_runner.py (several minutes)."""
import os,sys,tempfile,time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('SLOTHCAD_RENDERER','software')
sys.path.insert(0,str(Path(__file__).resolve().parent))
start=time.monotonic()
checks=[]

def check(name,function):
    try:
        function();checks.append((name,None))
    except Exception as error:
        checks.append((name,f'{type(error).__name__}: {error}'))

def imports():
    import cadquery,numpy,scipy,ezdxf  # noqa: F401
    from PySide6 import QtCore,QtGui,QtWidgets  # noqa: F401

def kernel():
    import copy
    from model import Document,new_feature
    box=new_feature();box.update(width=40,height=30,depth=10)
    hole=new_feature();hole.update(profile='circle',radius=3,depth=12,z=-1,operation='cut')
    document=Document([box,hole])
    expected=12000-90*3.141592653589793
    assert abs(document.solid.val().Volume()-expected)<1e-4,'unexpected volume'
    changed=copy.deepcopy(document.features);changed[0]['width']=50;document.commit(changed)
    assert document.undo(),'undo failed'
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'smoke.fcad';document.save(path)
        loaded=Document.load(path)
        assert abs(loaded.solid.val().Volume()-expected)<1e-4,'save/load changed the part'
        document.export_step(Path(folder)/'smoke.step') if hasattr(document,'export_step') else None

def rasterizer():
    from render_backend import Rasterizer
    raster=Rasterizer()
    if raster.native is None:
        print('  note: fast viewport module unavailable, using the built-in renderer'+(f' ({raster.error})' if raster.error else ''))

def application_modules():
    import app  # noqa: F401  (catches syntax/import errors in the UI code)

check('dependencies import',imports)
check('model build, edit, undo, save/load',kernel)
check('viewport rasterizer',rasterizer)
check('application modules import',application_modules)
failed=[(n,e) for n,e in checks if e]
for name,error in checks:print(('FAIL  ' if error else 'ok    ')+name+(f' -- {error}' if error else ''))
print(f'{len(checks)-len(failed)}/{len(checks)} checks passed in {time.monotonic()-start:.1f}s')
sys.exit(1 if failed else 0)
