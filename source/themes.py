"""SlothCAD's slate/ivory interface, independent of document display settings."""
import os
from platform_support import settings as app_settings
from PySide6.QtGui import QPalette,QColor

COLORS={
 'light':dict(ontick='#ffffff',shade='rgba(0,0,0,22)',bg='#f5f3ee',panel='#ffffff',bar='#e9e6df',text='#263538',muted='#67777a',border='#d2d9d5',accent='#147f78',hover='#e0efea',selected='#c3e6db',canvas='#edf2ee',grid='#ccd9d2',major='#b4c8bd',sketch='#7162a6',fill='#e7e1f0',active='#127d78',activefill='#d9eee6'),
 'dark':dict(ontick='#10161d',shade='rgba(0,0,0,95)',bg='#171e24',panel='#202b33',bar='#11191f',text='#e2eceb',muted='#9eafba',border='#354651',accent='#68d7bd',hover='#2b4147',selected='#305650',canvas='#141d25',grid='#293944',major='#3b505c',sketch='#c0a4ef',fill='#302d46',active='#6cdec8',activefill='#203c3b')}

def load_theme():
    settings=app_settings()
    value=settings.value('appearance/theme','dark')
    return value if value in COLORS else 'dark'

def save_theme(value):
    if value not in COLORS:raise ValueError('Unknown theme')
    settings=app_settings();settings.setValue('appearance/theme',value);settings.sync()

def check_image(color):
    """A small SVG tick in ``color`` (style sheets can only show indicators from image files)."""
    import tempfile
    folder=os.path.join(tempfile.gettempdir(),'slothcad-ui');os.makedirs(folder,exist_ok=True)
    path=os.path.join(folder,'check-'+color.lstrip('#')+'.svg')
    if not os.path.exists(path):
        with open(path,'w',encoding='utf-8') as handle:
            handle.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="'+color+'" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return path.replace(chr(92),'/')

def tab_close_image(color):
    """A thin x for the project tabs' close buttons, in ``color``."""
    import tempfile
    folder=os.path.join(tempfile.gettempdir(),'slothcad-ui');os.makedirs(folder,exist_ok=True)
    path=os.path.join(folder,'close-'+color.lstrip('#')+'.svg')
    if not os.path.exists(path):
        with open(path,'w',encoding='utf-8') as handle:
            handle.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4.6 4.6l6.8 6.8M11.4 4.6l-6.8 6.8" fill="none" stroke="'+color+'" stroke-width="1.6" stroke-linecap="round"/></svg>')
    return path.replace(chr(92),'/')


def apply_theme(app,name):
    c=COLORS[name];palette=QPalette()
    for role,key in [(QPalette.Window,'bg'),(QPalette.Base,'panel'),(QPalette.AlternateBase,'bg'),(QPalette.Button,'bar'),(QPalette.WindowText,'text'),(QPalette.Text,'text'),(QPalette.ButtonText,'text'),(QPalette.Highlight,'selected'),(QPalette.HighlightedText,'text'),(QPalette.ToolTipBase,'panel'),(QPalette.ToolTipText,'text')]:palette.setColor(role,QColor(c[key]))
    palette.setColor(QPalette.Disabled,QPalette.Text,QColor(c['muted']));app.setPalette(palette)
    app.setStyleSheet('''
QWidget {{ background: {bg}; color: {text}; font-size: 13px; }}
QMainWindow, QMenuBar, QToolBar, QStatusBar {{ background: {bar}; }}
QLabel {{ background: transparent; }}
QWidget#contextBar, QWidget#toolGroup {{ background: {panel}; }}
QMenu {{ background: {panel}; border: 1px solid {border}; padding: 6px; }}
QMenu::item {{ padding: 7px 22px; }} QMenu::item:selected {{ background: {hover}; }}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QListWidget, QTreeWidget {{ background: {panel}; border: 1px solid {border}; border-radius: 7px; padding: 6px; selection-background-color: {selected}; }}
QPushButton {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; padding: 9px 14px; }}
QPushButton:hover, QToolButton:hover {{ background: {hover}; border-color: {accent}; }}
QPushButton:checked, QToolButton:checked {{ background: {selected}; border-color: {accent}; }}
QPushButton:checked {{ font-weight: 600; }}
QPushButton#primary {{ background: {accent}; color: {bar}; border: none; font-weight: 600; }}
QWidget#featureActions QPushButton {{ padding: 7px 8px; min-height: 20px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 9px; padding: 6px 9px; }}
QToolButton:disabled, QPushButton:disabled {{ color: {muted}; }}
QListWidget::item, QTreeWidget::item {{ padding: 6px; border-radius: 5px; }}
QTreeWidget#objectBrowser {{ border: none; padding: 2px; border-radius: 6px; }}
QTreeWidget#objectBrowser::item {{ padding: 3px 2px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {selected}; color: {text}; }}
QGroupBox {{ background: {panel}; border: 1px solid {border}; border-radius: 9px; margin-top: 16px; padding: 15px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; color: {accent}; }}
QLabel#groupTitle, QLabel#subtle {{ color: {muted}; font-size: 10px; padding: 0; margin: 0; }}
QToolButton#groupMenuButton {{ color: {muted}; font-size: 11px; padding: 1px 10px; border: none; border-radius: 5px; }}
QToolButton#groupMenuButton:hover, QToolButton#groupMenuButton::menu-indicator {{ background: {hover}; color: {accent}; }}
QPushButton#drawMenuButton {{ background: {selected}; color: {text}; border: 1px solid {border}; border-radius: 5px; padding: 1px 10px; font-size: 12px; }}
QPushButton#drawMenuButton:hover {{ border-color: {accent}; }}
QFrame#drawPalette {{ background: {panel}; border: 1px solid {accent}; border-radius: 10px; }}
QFrame#drawPalette QToolButton {{ background: {panel}; text-align: left; }}
QFrame#drawPalette QToolButton:hover, QFrame#drawPalette QToolButton:focus {{ background: {selected}; border-color: {accent}; }}
QFrame#drawPalette QToolButton#paletteClose, QFrame#drawPalette QToolButton#paletteBack {{ background: transparent; border: none; padding: 0; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; text-align: center; border-radius: 14px; font-size: 18px; }}
QFrame#drawPalette QToolButton#paletteClose:hover, QFrame#drawPalette QToolButton#paletteBack:hover {{ background: {hover}; border: none; }}
QFrame#modeBadgeFrame {{ background: transparent; border: none; border-left: 3px solid {accent}; border-radius: 0px; }}
QLabel#modeBadgeCaption {{ color: {muted}; font-size: 10px; font-weight: 600; background: transparent; }}
QLabel#modeBadgeValue {{ color: {text}; font-size: 15px; font-weight: 700; background: transparent; }}
QStackedWidget#ribbon {{ background: {panel}; border-bottom: 1px solid {border}; }}
QFrame#viewportTools {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
QProgressBar {{ background: {panel}; border: 1px solid {border}; border-radius: 5px; min-height: 8px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
QWidget#timeline, QWidget#historyBar {{ background: {bar}; }}
QWidget#historyBar QToolButton {{ padding: 4px; border-radius: 6px; }}
QToolBar {{ spacing: 6px; padding: 5px 10px; border: none; }}
QSplitter::handle {{ background: {border}; width: 1px; }}
QWidget#tabRow {{ background: {shade}; border-radius: 8px; }}
QTabBar#projectTabs {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar#projectTabs::tab {{ background: transparent; color: {text}; border: none; border-radius: 7px; padding: 0px 8px 0px 12px; margin: 2px 2px 2px 0; min-width: 112px; max-width: 230px; font-size: 12px; }}
QTabBar#projectTabs::tab:hover:!selected {{ background: {hover}; color: {text}; }}
QTabBar#projectTabs::tab:selected {{ background: {panel}; color: {text}; font-weight: 600; border-bottom: 2px solid {accent}; }}
QTabBar#projectTabs::close-button {{ image: url({tabx}); subcontrol-position: right; margin: 0 0 0 6px; border-radius: 4px; padding: 3px; }}
QTabBar#projectTabs::close-button:hover {{ image: url({tabx_hover}); background: {border}; }}
QToolButton#newTab {{ background: transparent; color: {muted}; border: none; padding: 0; font-size: 17px; border-radius: 7px; margin: 3px 0; }}
QToolButton#newTab:hover {{ background: {hover}; color: {text}; }}
QWidget#welcomePage {{ background: {bg}; }}
QLabel#welcomeTitle {{ font-size: 26px; font-weight: 700; }}
QLabel#welcomeSubtitle {{ color: {muted}; font-size: 14px; }}
QLabel#welcomeSection {{ font-size: 18px; font-weight: 700; background: transparent; }}
QFrame#welcomePanel {{ background: {shade}; border: none; border-radius: 14px; }}
QFrame#welcomePanel QLabel#welcomeSubtitle {{ background: transparent; }}
QFrame#welcomeCard {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
QFrame#welcomeCard:hover {{ border-color: {accent}; background: {hover}; }}
QLabel#welcomeCardTitle {{ font-size: 14px; font-weight: 700; background: transparent; }}
QLabel#welcomeCardText {{ color: {muted}; font-size: 12px; background: transparent; }}
QListWidget#recentProjects {{ background: transparent; border: none; }}
QListWidget#recentProjects::item {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; padding: 8px; margin: 4px; }}
QListWidget#recentProjects::item:hover {{ border-color: {accent}; background: {hover}; }}
QListWidget#recentProjects::item:selected {{ background: {selected}; color: {text}; }}
QFrame#floatPanel {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}
QFrame#browserPanel {{ background: transparent; border: none; }}
QFrame#browserHeader {{ background: {bar}; border: 1px solid {border}; border-radius: 4px; }}
QFrame#browserHeader QLabel {{ background: transparent; }}
QToolButton#browserCollapse {{ background: transparent; border: none; padding: 0; min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; font-size: 16px; }}
QToolButton#browserCollapse:hover {{ background: {hover}; border-radius: 4px; }}
QFrame#browserPanel QTreeWidget {{ background: transparent; border: none; }}
QFrame#browserPanel QTreeWidget::item {{ padding: 2px 0px; }}
QFrame#browserPanel QTreeWidget::item:hover {{ background: {hover}; border-radius: 4px; }}
QFrame#floatPanel QScrollArea {{ border: none; }}
QScrollArea {{ border: none; }}
QScrollArea#ribbonScroll QScrollBar:horizontal {{ height: 8px; background: {panel}; }}
QScrollArea#ribbonScroll QScrollBar::handle:horizontal {{ background: {border}; min-width: 40px; border-radius: 4px; }}
QScrollArea#ribbonScroll QScrollBar::add-line:horizontal, QScrollArea#ribbonScroll QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar:vertical {{ width: 10px; background: {bg}; }} QScrollBar::handle:vertical {{ background: {border}; min-height: 25px; border-radius: 5px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QFrame#ribbonDivider {{ background: {border}; margin: 10px 0px 22px 0px; }}
QWidget#toolGroup QToolButton {{ border-radius: 7px; padding: 3px 8px 2px 8px; }}
QScrollArea#ribbonScroll QScrollBar:horizontal {{ height: 6px; margin: 0; }}
QScrollArea#ribbonScroll QScrollBar::handle:horizontal {{ border-radius: 3px; min-width: 40px; }}
QWidget#toolGroup QToolButton:pressed {{ background: {selected}; }}
QLabel#groupTitle {{ font-weight: 600; }}
QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 6px 8px; }}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QPushButton#primary:hover {{ background: {active}; }}
QPushButton#primary:disabled {{ background: {border}; color: {muted}; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 5px; background: transparent; }}
QMenuBar::item:selected {{ background: {hover}; }}
QMenu {{ border-radius: 8px; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 5px 10px; }}
QStatusBar {{ border-top: 1px solid {border}; color: {muted}; }}
QWidget#historyBar {{ border-top: 1px solid {border}; }}
QWidget#timeline QToolButton {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; padding: 3px 9px; }}
QWidget#timeline QToolButton:hover {{ border-color: {accent}; background: {hover}; }}
QWidget#timeline QToolButton:checked {{ background: {selected}; border: 1px solid {accent}; font-weight: 600; }}
QTreeWidget#objectBrowser {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
QTreeWidget#objectBrowser::item:hover {{ background: {hover}; }}
QFrame#viewportTools QToolButton {{ border-radius: 7px; }}
QFrame#viewportTools QToolButton:checked {{ background: {selected}; border: 1px solid {accent}; }}
QTreeWidget::indicator, QListWidget::indicator, QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {muted}; border-radius: 4px; background: {panel}; }}
QTreeWidget::indicator:hover, QListWidget::indicator:hover, QCheckBox::indicator:hover {{ border-color: {accent}; }}
QTreeWidget::indicator:checked, QListWidget::indicator:checked, QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: url({tick}); }}
QTreeWidget::indicator:disabled, QListWidget::indicator:disabled, QCheckBox::indicator:disabled {{ border-color: {border}; background: {bg}; }}
'''.format(tick=check_image(c.get('ontick','#ffffff')),tabx=tab_close_image(c['muted']),tabx_hover=tab_close_image(c['text']),**c))
