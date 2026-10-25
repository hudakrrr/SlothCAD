"""Ribbon action lists inside the window, without native popup menu grabs."""
from PySide6.QtCore import Qt,QEvent,QPoint,QSize
from PySide6.QtWidgets import (QApplication,QFrame,QVBoxLayout,QHBoxLayout,QLabel,
                              QToolButton,QScrollArea,QWidget,QSizePolicy)
from i18n import tr
from ui_icons import icon

class ToolPalette(QFrame):
    def __init__(self,window,anchor,menu,title):
        super().__init__(window.centralWidget())
        self.window=window;self.anchor=anchor;self.menu=menu;self.title=title
        self.arrow=QLabel('▾',anchor);self.arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.arrow.setStyleSheet('background: transparent; font-size: 10px;');self.arrow.resize(12,12)
        anchor.installEventFilter(self)
        self.setObjectName('drawPalette');self.hide();self.buttons=[];self.menu_stack=[];self.current_menu=menu
        layout=QVBoxLayout(self);layout.setContentsMargins(12,10,12,10)
        header=QHBoxLayout();self.header=header;self.back=QToolButton();self.back.setObjectName('paletteBack');self.back.setText('‹');self.back.setFocusPolicy(Qt.NoFocus);self.back.setToolTip(tr('Back'));self.back.clicked.connect(self.go_back);self.back.hide();header.addWidget(self.back);self.heading=QLabel();header.addWidget(self.heading);header.addStretch()
        close=QToolButton();close.setObjectName('paletteClose');close.setProperty('_icon_name','cancel');close.setIcon(icon('cancel'));close.setIconSize(QSize(14,14));close.setFocusPolicy(Qt.NoFocus);close.setToolTip(tr('Close'));close.clicked.connect(self.dismiss);header.addWidget(close);layout.addLayout(header)
        scroll=QScrollArea();self.scroll=scroll;scroll.setFrameShape(QFrame.NoFrame);scroll.setWidgetResizable(True);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);layout.addWidget(scroll)
        content=QWidget();rows=QVBoxLayout(content);rows.setContentsMargins(2,2,6,2);rows.setSpacing(5);scroll.setWidget(content)
        self.rows=rows
        self.build_rows(menu)

    def build_rows(self,menu):
        while self.rows.count():
            item=self.rows.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.buttons=[];self.current_menu=menu
        self.back.setVisible(bool(self.menu_stack))
        self.heading.setText(tr(self.title) if menu is self.menu else menu.title())
        for action in menu.actions():
            if action.isSeparator():continue
            button=QToolButton();button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);button.setMinimumHeight(38)
            button.setIconSize(QSize(24,24));button.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            button.setProperty('_action',action);button.setProperty('_icon_name',action.property('_icon_name') or action.data() or 'construct');button.clicked.connect(lambda checked=False,a=action:self.activate(a))
            button.setText(action.text()+(' ›' if action.menu() else ''));button.setIcon(action.icon() if action.menu() else icon(button.property('_icon_name')));button.setEnabled(action.isEnabled())
            fit_row(button)
            self.rows.addWidget(button);self.buttons.append(button)
            # Rows added while the palette is already visible start hidden, and a layout
            # ignores hidden widgets: the list was measured as empty (a tiny window).
            button.show()
        self.rows.addStretch()

    def go_back(self):
        if self.menu_stack:self.build_rows(self.menu_stack.pop());self.place()

    def activate(self,action):
        if action.menu() and action.isEnabled():
            self.menu_stack.append(self.current_menu);self.build_rows(action.menu());self.place();return
        self.dismiss()
        if not self.window.loading and action.isEnabled():action.trigger()

    def toggle(self):
        if self.isVisible():self.dismiss();return
        if self.window.loading:return
        for palette in self.window.tool_palettes.values():palette.dismiss()
        self.window.draw_palette.dismiss()
        self.menu_stack=[];self.build_rows(self.menu);self.place()
        self.show();self.raise_()
        if self.buttons:self.buttons[0].setFocus(Qt.PopupFocusReason)

    def place(self):
        parent=self.parentWidget();width=min(max(300,max((b.sizeHint().width() for b in self.buttons),default=0)+44),parent.width()-16)
        at=self.anchor.mapTo(parent,QPoint(0,self.anchor.height()+4));x=max(8,min(at.x(),parent.width()-width-8))
        # Measure the real rows instead of assuming a fixed row height: with a larger
        # font or display scale the old estimate made the list scroll and clipped a row.
        height=min(needed_height(self,self.header,self.scroll),max(100,parent.height()-at.y()-8))
        self.setGeometry(x,at.y(),width,height);self.layout().activate()

    def dismiss(self):
        if self.isVisible():
            self.hide();self.window.workspace.setFocus()

    def showEvent(self,event):
        QApplication.instance().installEventFilter(self);super().showEvent(event)

    def hideEvent(self,event):
        QApplication.instance().removeEventFilter(self);super().hideEvent(event)

    def eventFilter(self,obj,event):
        if obj is self.anchor and event.type()==QEvent.Resize:
            self.arrow.move(self.anchor.width()-15,self.anchor.height()-14)
        if self.isVisible():
            if event.type()==QEvent.ShortcutOverride and event.key()==Qt.Key_Escape:event.accept();return True
            if event.type()==QEvent.KeyPress and event.key()==Qt.Key_Escape:self.dismiss();return True
            if event.type()==QEvent.MouseButtonPress:
                point=event.globalPosition().toPoint()
                # A press on one of the list's own rows is always inside, even when the row
                # is partly scrolled out of view at that moment.
                own=isinstance(obj,QWidget) and (obj is self or self.isAncestorOf(obj))
                if not own and not self.rect().contains(self.mapFromGlobal(point)) and not self.anchor.rect().contains(self.anchor.mapFromGlobal(point)):
                    # Let another ribbon button open its own list on this click;
                    # consume workspace clicks so dismissal never edits a model.
                    on_ribbon=self.window.toolbar_contains(point)
                    self.dismiss();return not on_ribbon
            # A window resize (a panel opening, a longer label) keeps the list open and
            # moves it with its button; only leaving the window closes it.
            if obj is self.window and event.type()==QEvent.Resize:self.place()
            elif obj is self.window and event.type()==QEvent.WindowDeactivate:self.hide()
        return super().eventFilter(obj,event)

def fit_row(button,minimum=40):
    """Give a list row a fixed height that always fits its icon and text."""
    button.ensurePolished()
    text=button.fontMetrics().height()+18
    button.setFixedHeight(max(minimum,button.sizeHint().height()+4,text,button.iconSize().height()+16))


def needed_height(frame,header,scroll):
    """Full height of a palette: margins, header and every row, without scrolling."""
    frame.layout().activate();content=scroll.widget();content.layout().activate()
    margins=frame.layout().contentsMargins()
    return (margins.top()+margins.bottom()+frame.layout().spacing()+header.sizeHint().height()
            +content.layout().sizeHint().height()+2*scroll.frameWidth()+2*frame.frameWidth()+8)


def bind_dropdown(window,key,button,menu):
    if not hasattr(window,'tool_palettes'):window.tool_palettes={}
    palette=ToolPalette(window,button,menu,button.property('_i18n_text'))
    window.tool_palettes[key]=palette
    button.setMenu(None);button.setPopupMode(QToolButton.DelayedPopup)
    button.clicked.connect(palette.toggle)
