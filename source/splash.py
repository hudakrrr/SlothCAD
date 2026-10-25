"""Start-up loading screen.

SlothCAD needs a couple of seconds to import the CAD kernel and build the window.
The splash is created before any of that, so it is on screen immediately.

Put your own picture at assets/splash.png (any size, about 900x500 looks good);
without that file a plain drawn screen with the logo is used instead.
"""
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
STAGES=8
_splash=None


def wanted():
    if os.environ.get('SLOTHCAD_NO_SPLASH'):return False
    return os.environ.get('QT_QPA_PLATFORM','') not in ('offscreen','minimal')


def image_path():
    for name in ('splash.png','splash.jpg','splash.jpeg'):
        path=ROOT/'assets'/name
        if path.exists():return path
    return None


def make_pixmap(version):
    from PySide6.QtCore import Qt,QRectF
    from PySide6.QtGui import QPixmap,QPainter,QColor,QFont,QLinearGradient
    path=image_path()
    if path is not None:
        pixmap=QPixmap(str(path))
        if not pixmap.isNull():
            if pixmap.width()>960:pixmap=pixmap.scaledToWidth(960,Qt.SmoothTransformation)
            return pixmap
    pixmap=QPixmap(640,360);painter=QPainter(pixmap)
    gradient=QLinearGradient(0,0,0,360);gradient.setColorAt(0,QColor('#26323b'));gradient.setColorAt(1,QColor('#141a1f'))
    painter.fillRect(pixmap.rect(),gradient)
    logo=ROOT/'assets'/'slothcad.png'
    if logo.exists():
        icon=QPixmap(str(logo)).scaled(128,128,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        painter.drawPixmap(256,64,icon)
    painter.setPen(QColor('#f2f4f5'));font=QFont();font.setPointSize(26);font.setBold(True);painter.setFont(font)
    painter.drawText(QRectF(0,206,640,48),Qt.AlignCenter,'SlothCAD')
    font.setPointSize(11);font.setBold(False);painter.setFont(font);painter.setPen(QColor('#9fb0ba'))
    painter.drawText(QRectF(0,252,640,26),Qt.AlignCenter,'Version '+version)
    painter.end()
    return pixmap


def begin(version):
    """Create the application object and show the splash. Safe to call twice."""
    global _splash
    if _splash is not None or not wanted():return None
    from PySide6.QtCore import Qt,QRect,QRectF
    from PySide6.QtGui import QColor,QFont,QPainter,QLinearGradient
    from PySide6.QtWidgets import QApplication,QSplashScreen
    import platform_support
    platform_support.prepare_process()
    from PySide6.QtGui import QSurfaceFormat
    from gpu_renderer import surface_format
    QSurfaceFormat.setDefaultFormat(surface_format())
    app=QApplication.instance() or QApplication(sys.argv)

    class Splash(QSplashScreen):
        def __init__(self,pixmap):
            super().__init__(pixmap,Qt.WindowStaysOnTopHint|Qt.SplashScreen)
            self.stage=0;self.text='';self.version=version
        def drawContents(self,painter):
            width,height=self.width(),self.height()
            painter.setRenderHint(QPainter.Antialiasing)
            # A soft dark band at the bottom keeps the text and the bar readable on any picture.
            scrim=QLinearGradient(0,height-130,0,height)
            scrim.setColorAt(0,QColor(8,14,28,0));scrim.setColorAt(1,QColor(8,14,28,215))
            painter.fillRect(QRect(0,height-130,width,130),scrim)
            margin=max(24,int(width*.035))
            title=QFont();title.setPointSize(max(14,int(width/46)));title.setBold(True);painter.setFont(title)
            painter.setPen(QColor('#ffffff'))
            painter.drawText(QRect(margin,height-104,width-2*margin,36),Qt.AlignVCenter|Qt.AlignLeft,'SlothCAD')
            small=QFont();small.setPointSize(10);painter.setFont(small);painter.setPen(QColor('#c8d6ee'))
            painter.drawText(QRect(margin,height-104,width-2*margin,36),Qt.AlignVCenter|Qt.AlignRight,'Version '+self.version)
            painter.drawText(QRect(margin,height-68,width-2*margin,22),Qt.AlignVCenter|Qt.AlignLeft,self.text)
            fraction=max(0.,min(1.,self.stage/STAGES))
            bar=QRectF(margin,height-40,width-2*margin,12)
            painter.setPen(Qt.NoPen);painter.setBrush(QColor(255,255,255,50));painter.drawRoundedRect(bar,6,6)
            if fraction>0:
                fill=QRectF(bar.left(),bar.top(),max(12.,bar.width()*fraction),bar.height())
                gradient=QLinearGradient(fill.left(),0,fill.right(),0)
                gradient.setColorAt(0,QColor('#f6c66b'));gradient.setColorAt(1,QColor('#e08a2e'))
                painter.setBrush(gradient);painter.drawRoundedRect(fill,6,6)
            painter.setPen(QColor('#ffffff'));painter.setFont(small)
            painter.drawText(QRectF(margin,height-26,width-2*margin,20),Qt.AlignVCenter|Qt.AlignRight,f'{int(fraction*100)} %')

    _splash=Splash(make_pixmap(version))
    _splash.text='Starting…';_splash.show();app.processEvents()
    return _splash


def step(text):
    """Advance the progress bar and show what is being loaded."""
    if _splash is None:return
    from PySide6.QtWidgets import QApplication
    _splash.stage+=1;_splash.text=text;_splash.repaint()
    QApplication.processEvents()


def finish(window=None):
    global _splash
    if _splash is None:return
    splash,_splash=_splash,None
    if window is not None:splash.finish(window)
    else:splash.close()
