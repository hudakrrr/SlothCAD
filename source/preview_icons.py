"""Render the original icon family at 42 px and the actual 24 px menu size.

Usage: QT_QPA_PLATFORM=offscreen python preview_icons.py
"""
import argparse,math
from pathlib import Path
from PySide6.QtCore import QRectF,Qt
from PySide6.QtGui import QImage,QPainter,QFont,QColor
from PySide6.QtWidgets import QApplication
from icon_art import ICON_KEYS
from ui_icons import icon
from themes import COLORS,apply_theme


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('validation-results'));args=parser.parse_args()
    app=QApplication.instance() or QApplication([]);args.output.mkdir(parents=True,exist_ok=True)
    names=sorted(ICON_KEYS)
    for theme in ('light','dark'):
        apply_theme(app,theme);colors=COLORS[theme]
        sheet=QImage(1280,math.ceil(len(names)/10)*104,QImage.Format_ARGB32);sheet.fill(QColor(colors['panel']))
        painter=QPainter(sheet);painter.setFont(QFont('Sans',9))
        try:
            for i,name in enumerate(names):
                x=i%10*128;y=i//10*104
                painter.setPen(QColor(colors['border']));painter.drawRect(x,y,128,104)
                glyph=icon(name);glyph.paint(painter,x+15,y+7,42,42);glyph.paint(painter,x+85,y+17,24,24)
                painter.setPen(QColor(colors['text']));painter.drawText(QRectF(x+4,y+54,120,42),Qt.AlignCenter|Qt.TextWordWrap,name.replace('_',' '))
        finally:painter.end()
        target=args.output/f'icons-0.11.36-{theme}.png'
        if not sheet.save(str(target)):raise RuntimeError(f'Cannot save {target}')
        print(target)


if __name__=='__main__':main()
