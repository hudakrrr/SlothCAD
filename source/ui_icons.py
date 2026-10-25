"""Theme-aware, original vector icons rendered at the actual display scale.

An optional icon pack can replace the built-in art: a folder of PNG files named after the tools
(``extrude.png`` for light interfaces, ``extrude-dark.png`` for dark ones; the plain file is used
when there is no dark one). The folder is, in this order, ``$SLOTHCAD_ICON_DIR``, the user's
``SlothCAD/icons`` data folder, or ``assets/icons`` next to the program. Without a pack, or for a
tool the pack does not have, the built-in vector art is used.
"""
import math
import os
from pathlib import Path
from functools import lru_cache
from PySide6.QtCore import Qt,QRectF,QSize
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette,QIcon,QIconEngine,QPixmap,QPainter
from PySide6.QtSvg import QSvgRenderer
from icon_art import ICON_KEYS,svg_source


class VectorIconEngine(QIconEngine):
    def __init__(self,source,name):
        super().__init__();self.source=source;self.name=name;self.renderer=QSvgRenderer(source)

    def clone(self):return VectorIconEngine(self.source,self.name)
    def key(self):return 'SlothCADVectorIcon'
    def iconName(self):return self.name
    def isNull(self):return not self.renderer.isValid()

    def paint(self,painter,rect,mode,state):
        painter.save()
        if mode==QIcon.Disabled:painter.setOpacity(painter.opacity()*.42)
        painter.setRenderHint(QPainter.Antialiasing)
        side=min(rect.width(),rect.height())
        self.renderer.render(painter,QRectF(rect.x()+(rect.width()-side)/2,rect.y()+(rect.height()-side)/2,side,side))
        painter.restore()

    def pixmap(self,size,mode,state):return self.scaledPixmap(size,mode,state,1.)

    def scaledPixmap(self,size,mode,state,scale):
        # Qt 6.8 supplies the requested size in logical pixels, not physical pixels.
        scale=max(.1,scale)
        pix=QPixmap(QSize(math.ceil(size.width()*scale),math.ceil(size.height()*scale)))
        pix.setDevicePixelRatio(scale);pix.fill(Qt.transparent)
        painter=QPainter(pix)
        try:self.paint(painter,QRectF(0,0,size.width(),size.height()),mode,state)
        finally:painter.end()
        return pix


def icon_colors():
    palette=QApplication.palette();dark=palette.color(QPalette.Window).lightness()<128
    return dict(ink=palette.color(QPalette.ButtonText).name(),panel=palette.color(QPalette.Base).name(),
                accent='#68d7bd' if dark else '#147f78',warm='#efb55d' if dark else '#b96c1a',
                muted='#91a6b4' if dark else '#7b8d97',red='#ef8b86' if dark else '#b64c45',
                green='#68d7a3' if dark else '#238956',blue='#7fbbed' if dark else '#367fb5',
                # Same hues as the viewport: bodies are blue, finished sketches purple.
                body='#6fb7dd' if dark else '#2f86b3',sketch='#c0a4ef' if dark else '#7a5aa6')


@lru_cache(maxsize=256)
def _cached_icon(kind,colors):
    return QIcon(VectorIconEngine(svg_source(kind,dict(colors)),kind))


def pack_folders():
    explicit=os.environ.get('SLOTHCAD_ICON_DIR')
    if explicit and explicit.lower() in ('none','off','0'):return []
    # Headless runs (tests, validation) always see the built-in art unless a folder is named.
    if not explicit and os.environ.get('QT_QPA_PLATFORM','') in ('offscreen','minimal'):return []
    folders=[]
    if explicit:folders.append(Path(explicit))
    base=os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or str(Path.home()/'.local'/'share')
    folders.append(Path(base)/'SlothCAD'/'icons')
    folders.append(Path(__file__).resolve().parent/'assets'/'icons')
    return [folder for folder in folders if folder.is_dir()]


@lru_cache(maxsize=512)
def _pack_icon(kind,dark,folders):
    names=(kind+'-dark.png',kind+'.png') if dark else (kind+'.png',)
    for folder in folders:
        for name in names:
            path=os.path.join(folder,name)
            if os.path.exists(path):
                pixmap=QPixmap(path)
                if not pixmap.isNull():return QIcon(pixmap)
    return None


def icon(kind):
    folders=tuple(str(folder) for folder in pack_folders())
    if folders:
        found=_pack_icon(kind,QApplication.palette().color(QPalette.Window).lightness()<128,folders)
        if found is not None:return found
    return QIcon(_cached_icon(kind,tuple(sorted(icon_colors().items()))))
