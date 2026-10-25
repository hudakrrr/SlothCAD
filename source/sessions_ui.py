"""Several projects open at once: a thin tab bar, a welcome page and copy/paste between projects.

The window shows one project at a time. Every other open project is kept as a *session*
(its document, file path, saved-state markers, selection); switching tabs stores the live
state into the session being left and loads the one being entered. With no project open a
welcome page replaces the workspace.
"""
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
from PySide6.QtCore import Qt,QSize,QStandardPaths
from PySide6.QtGui import QPixmap,QAction,QIcon
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QToolButton,QTabBar,
                               QStackedWidget,QMenu,QFrame,QListWidget,QListWidgetItem,QApplication,QSizePolicy)
from model import Document
from geometry import identifier
from i18n import tr
from ui_icons import icon
import platform_support

CLIPBOARD_MARK='slothcad-features'
STRUCTURE_ONLY=('sketch','construction_plane','construction_axis')


def thumbnail_path(project_path):
    """Where the preview picture of a project file is kept (outside the project, so files stay small)."""
    folder=os.environ.get('SLOTHCAD_THUMBNAIL_DIR') or str(Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))/'thumbnails')
    try:key=str(Path(project_path).resolve()).lower()
    except OSError:key=str(project_path).lower()
    return Path(folder)/(hashlib.sha1(key.encode('utf-8')).hexdigest()+'.png')


class StartCard(QFrame):
    """A big clickable card: icon, title and a one-line description."""
    def __init__(self,icon_name,title,description,handler):
        super().__init__();self.setObjectName('welcomeCard');self.handler=handler;self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(236,96)
        layout=QHBoxLayout(self);layout.setContentsMargins(12,10,10,10);layout.setSpacing(6)
        picture=QLabel();picture.setPixmap(icon(icon_name).pixmap(40,40));picture.setFixedSize(42,42);picture.setAttribute(Qt.WA_TransparentForMouseEvents)
        text=QVBoxLayout();text.setSpacing(2)
        head=QLabel(tr(title));head.setObjectName('welcomeCardTitle');head.setProperty('_i18n_text',title);head.setAttribute(Qt.WA_TransparentForMouseEvents)
        body=QLabel(tr(description));body.setObjectName('welcomeCardText');body.setWordWrap(True);body.setProperty('_i18n_text',description);body.setAttribute(Qt.WA_TransparentForMouseEvents)
        text.addStretch();text.addWidget(head);text.addWidget(body);text.addStretch()
        layout.addWidget(picture);layout.addLayout(text,1)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.rect().contains(event.position().toPoint()):self.handler()
        super().mouseReleaseEvent(event)


class WelcomePage(QWidget):
    """Shown when no project is open: start something new, or go back to a recent project."""
    PANEL_WIDTH=1060

    def __init__(self,window):
        super().__init__();self.window=window;self.setObjectName('welcomePage')
        outer=QVBoxLayout(self);outer.setContentsMargins(24,26,24,24);outer.setSpacing(16)
        # Title and question stay together at the top.
        words=QVBoxLayout();words.setSpacing(2);words.setContentsMargins(24,0,0,6)
        title=QLabel(tr('Welcome to SlothCAD'));title.setObjectName('welcomeTitle');title.setProperty('_i18n_text','Welcome to SlothCAD')
        subtitle=QLabel(tr('What do you want to do?'));subtitle.setObjectName('welcomeSubtitle');subtitle.setProperty('_i18n_text','What do you want to do?')
        for label in (title,subtitle):label.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed)
        words.addWidget(title);words.addWidget(subtitle);outer.addLayout(words)

        def panel(heading):
            frame=QFrame();frame.setObjectName('welcomePanel');frame.setMaximumWidth(self.PANEL_WIDTH)
            box=QVBoxLayout(frame);box.setContentsMargins(24,16,24,20);box.setSpacing(12);box.addWidget(self.section(heading));return frame,box

        top,top_layout=panel('New project')
        top.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed)
        cards=QHBoxLayout();cards.setSpacing(14)
        self.cards={}
        for key,icon_name,label,description,handler in (
            ('new','new','New project','Start with an empty project',window.blank),
            ('open','open','Open project…','Open an existing .fcad file',window.open),
            ('import','import_step','Import a file…','Bring in a STEP solid or a DXF drawing',self.import_menu),
            ('example','component','Example part','Open the example part and explore',window.example)):
            card=StartCard(icon_name,label,description,lambda h=handler:h());cards.addWidget(card);self.cards[key]=card
        cards.addStretch(1);top_layout.addLayout(cards);outer.addWidget(top)

        bottom,bottom_layout=panel('Recent projects')
        self.recent=QListWidget();self.recent.setObjectName('recentProjects');self.recent.setViewMode(QListWidget.IconMode)
        self.recent.setIconSize(QSize(64,64));self.recent.setGridSize(QSize(176,128));self.recent.setResizeMode(QListWidget.Adjust)
        self.recent.setMovement(QListWidget.Static);self.recent.setWordWrap(True);self.recent.setSpacing(6);self.recent.setFrameShape(QFrame.NoFrame)
        self.recent.itemClicked.connect(self.open_recent);self.recent.itemActivated.connect(self.open_recent)
        bottom_layout.addWidget(self.recent,1)
        self.empty=QLabel(tr('Projects you open or save will show up here.'));self.empty.setObjectName('welcomeSubtitle')
        self.empty.setProperty('_i18n_text','Projects you open or save will show up here.');bottom_layout.addWidget(self.empty)
        bottom_layout.addStretch(0)
        outer.addWidget(bottom,1)
        self.buttons=self.cards

    def section(self,text):
        label=QLabel(tr(text));label.setObjectName('welcomeSection');label.setProperty('_i18n_text',text);return label

    def import_menu(self):
        menu=QMenu(self)
        menu.addAction(tr('STEP solid (*.step *.stp)')).triggered.connect(lambda:self.window.import_step_file())
        menu.addAction(tr('DXF drawing (*.dxf)')).triggered.connect(lambda:self.window.import_dxf_file())
        card=self.cards['import'];menu.exec(card.mapToGlobal(card.rect().bottomLeft()))

    def refresh_recent(self):
        import time
        self.recent.clear()
        for path in self.window.recent_files():
            try:
                info=Path(path).stat();size=info.st_size/1024
                detail=(f'{size/1024:.1f} MB' if size>=1024 else f'{size:.1f} kB')+' · '+time.strftime('%Y-%m-%d',time.localtime(info.st_mtime))
            except OSError:detail=''
            picture=thumbnail_path(path);preview=QIcon(QPixmap(str(picture))) if picture.exists() else None
            item=QListWidgetItem(preview if preview is not None and not preview.isNull() else icon('body'),Path(path).stem+'\n'+detail);item.setData(Qt.UserRole,path);item.setToolTip(str(path))
            item.setTextAlignment(Qt.AlignHCenter|Qt.AlignTop);self.recent.addItem(item)
        has=self.recent.count()>0;self.recent.setVisible(has);self.empty.setVisible(not has)

    def open_recent(self,item):
        path=item.data(Qt.UserRole)
        if path:self.window.load(path)


class SessionsUI:
    def init_sessions(self):
        """Create the project tabs inside the existing menu bar (File / Edit / Settings / Help) and the welcome page."""
        self.sessions=[];self.session_id=None;self._ids=itertools.count(1);self._untitled=itertools.count(1)
        bar_height=self.menu_bar.sizeHint().height()
        row=QWidget();row.setObjectName('tabRow');row_layout=QHBoxLayout(row);row_layout.setContentsMargins(6,0,4,0);row_layout.setSpacing(2)
        self.tabs=QTabBar();self.tabs.setObjectName('projectTabs');self.tabs.setTabsClosable(True);self.tabs.setMovable(True);self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False);self.tabs.setElideMode(Qt.ElideMiddle);self.tabs.setUsesScrollButtons(True);self.tabs.setFocusPolicy(Qt.NoFocus)
        self.tabs.setIconSize(QSize(14,14))
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.currentChanged.connect(self.tab_changed);self.tabs.tabCloseRequested.connect(self.tab_close_requested)
        self.tabs.customContextMenuRequested.connect(self.tab_menu)
        self.new_tab_button=QToolButton();self.new_tab_button.setObjectName('newTab');self.new_tab_button.setText('+');self.new_tab_button.setToolTip(tr('New project'));self.new_tab_button.setFocusPolicy(Qt.NoFocus)
        self.new_tab_button.clicked.connect(lambda:self.blank())
        row_layout.addWidget(self.tabs);row_layout.addWidget(self.new_tab_button);row_layout.addStretch(1)
        # Exactly as tall as the menu bar, so the bar does not grow.
        self.tabs.setFixedHeight(bar_height);self.new_tab_button.setFixedSize(bar_height,bar_height)
        row.setFixedHeight(bar_height);self.tab_row=row
        row.setParent(self.menu_bar);row.show()
        self.menu_bar.installEventFilter(self)
        self.welcome=WelcomePage(self);self.feature_clipboard=None
        self.fit_tab_row()

    def fit_tab_row(self):
        """Let the tabs use the space right of the menus (File, Edit, Settings, Help)."""
        actions=self.menu_bar.actions()
        used=self.menu_bar.actionGeometry(actions[-1]).right() if actions else 0
        width=max(160,self.menu_bar.width()-used-24)
        self.tab_row.setGeometry(used+30,1,max(160,width-16),self.menu_bar.height()-2);self.tab_row.raise_()

    # ---- bookkeeping -------------------------------------------------------------
    def current_session(self):
        return next((s for s in self.sessions if s['id']==self.session_id),None)

    def session_title(self,session):
        return session['path'].name if session.get('path') else session['title']

    def store_session(self,session):
        session.update(doc=self.doc,path=self.path,saved_features=self.saved_features,saved_display=self.saved_display,selected=self.selected,
                       component_stack=getattr(self,'component_stack',[]),history_preview_index=self.history_preview_index,dirty=self.dirty())

    def apply_session(self,session):
        self.doc=session['doc'];self.path=session['path'];self.saved_features=session['saved_features'];self.saved_display=session['saved_display']
        self.selected=session['selected'];self.component_stack=session['component_stack'];self.history_preview_index=session['history_preview_index']
        self.draft=None;self.draft_index=None;self.session_id=session['id']
        self.stack.setCurrentWidget(self.workspace);self.set_project_chrome(True)
        self.workspace.set_mode('model');self.refresh(True);self.show_editor()

    def set_project_chrome(self,on):
        """With no project open the toolbar stays visible but greyed out; the timeline is hidden."""
        ribbon=getattr(self,'ribbon_container',None)
        if ribbon is not None:ribbon.setVisible(True);ribbon.setEnabled(on)
        history=getattr(self,'history_container',None)
        if history is not None:history.setVisible(on)

    def register_session(self,title=None):
        """Register the live document as a new session (and tab) and make it current."""
        session=dict(id=next(self._ids),doc=self.doc,path=self.path,title=title or f"{tr('Untitled')} {next(self._untitled)}",saved_features=self.saved_features,
                     saved_display=self.saved_display,selected=self.selected,component_stack=getattr(self,'component_stack',[]),history_preview_index=None,dirty=False)
        self.sessions.append(session)
        index=self.tabs.addTab(icon('body'),self.session_title(session));self.tabs.setTabData(index,session['id']);self.session_id=session['id']
        self.tabs.blockSignals(True);self.tabs.setCurrentIndex(index);self.tabs.blockSignals(False)
        return session

    def tab_index(self,session_id):
        return next((i for i in range(self.tabs.count()) if self.tabs.tabData(i)==session_id),-1)

    def sync_tab_title(self):
        session=self.current_session()
        if session is None:return
        session['path']=self.path
        index=self.tab_index(session['id'])
        if index>=0:self.tabs.setTabText(index,self.session_title(session)+('  ●' if self.dirty() else ''))
        self.tabs.setTabToolTip(index,str(self.path) if self.path else self.session_title(session))

    def pristine(self):
        """A blank, untouched, never-saved project that a new project may simply replace."""
        session=self.current_session()
        return session is not None and self.path is None and not self.doc.features and not getattr(self,'component_stack',[]) and self.draft is None

    # ---- opening / switching / closing -----------------------------------------------
    def begin_new_project(self,replace_pristine=True):
        """Prepare the live state for a new project: returns False when the user cancels."""
        session=self.current_session()
        if session is None:
            self.doc=Document();self.path=None;self.saved_features=[];self.saved_display={};self.selected=None;self.component_stack=[];self.history_preview_index=None
            self.register_session();return True
        if replace_pristine and self.pristine():return True
        if not self.abandon():return False
        self.store_session(session)
        self.doc=Document();self.path=None;self.saved_features=[];self.saved_display={};self.selected=None;self.component_stack=[];self.history_preview_index=None
        self.register_session();return True

    def ensure_session(self):
        if self.current_session() is None:
            self.begin_new_project();self.stack.setCurrentWidget(self.workspace);self.set_project_chrome(True)
            self.workspace.set_mode('support');self.refresh(True);self.show_editor()

    def tab_changed(self,index):
        if index<0:return
        sid=self.tabs.tabData(index)
        if sid is None or sid==self.session_id:return
        self.switch_to(sid)

    def switch_to(self,sid):
        target=next((s for s in self.sessions if s['id']==sid),None)
        if target is None:return False
        current=self.current_session()
        if current is not None:
            if not self.abandon():
                self.tabs.blockSignals(True);self.tabs.setCurrentIndex(self.tab_index(current['id']));self.tabs.blockSignals(False);return False
            self.store_session(current)
        self.apply_session(target);self.sync_tab_title();return True

    def tab_close_requested(self,index):
        sid=self.tabs.tabData(index)
        if sid is not None:self.close_session(sid)

    def close_session(self,sid):
        if self.loading:return False
        if sid!=self.session_id and not self.switch_to(sid):return False
        if not self.safe_to_leave():return False
        position=self.tab_index(sid)
        self.sessions=[s for s in self.sessions if s['id']!=sid]
        from model import release_kernel_caches
        release_kernel_caches()        # the closed project's shapes are not needed any more
        self.tabs.blockSignals(True);self.tabs.removeTab(position);self.tabs.blockSignals(False)
        if not self.sessions:
            self.session_id=None;self.doc=Document();self.path=None;self.saved_features=[];self.saved_display={};self.selected=None;self.component_stack=[]
            self.show_welcome();return True
        neighbour=self.sessions[min(position,len(self.sessions)-1)]
        self.session_id=None
        self.tabs.blockSignals(True);self.tabs.setCurrentIndex(self.tab_index(neighbour['id']));self.tabs.blockSignals(False)
        self.apply_session(neighbour);self.sync_tab_title();return True

    def show_welcome(self):
        self.workspace.set_mode('model');self.draft=None;self.draft_index=None
        self.welcome.refresh_recent();self.stack.setCurrentWidget(self.welcome);self.set_project_chrome(False)
        self.update_title()

    def confirm_close_all(self):
        """Ask about every unsaved project before the window closes."""
        for session in list(self.sessions):
            if session['id']!=self.session_id and not self.switch_to(session['id']):return False
            if not self.safe_to_leave():return False
        return True

    def tab_menu(self,position):
        index=self.tabs.tabAt(position)
        if index<0:return
        sid=self.tabs.tabData(index);menu=QMenu(self)
        menu.addAction(tr('Close')).triggered.connect(lambda:self.close_session(sid))
        menu.addAction(tr('Close other projects')).triggered.connect(lambda:[self.close_session(s['id']) for s in list(self.sessions) if s['id']!=sid])
        paste=menu.addAction(tr('Paste copied features here'));paste.setEnabled(self.clipboard_features() is not None)
        paste.triggered.connect(lambda:(self.switch_to(sid),self.paste_features()))
        menu.exec(self.tabs.mapToGlobal(position))

    def save_thumbnail(self,path):
        """A small picture of the current view next to the recent-projects entry. Never an error."""
        try:
            workspace=self.workspace
            if workspace.width()<40 or workspace.height()<40 or not workspace.isVisible():return
            image=workspace.grab().toImage().scaledToWidth(220,Qt.SmoothTransformation)
            target=thumbnail_path(path);target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_suffix('.tmp.png')
            if image.save(str(temporary),'PNG'):os.replace(temporary,target)
        except Exception:pass

    # ---- recent files ------------------------------------------------------------------
    def recent_files(self):
        try:
            value=platform_support.settings().value('recent/files',[])
        except Exception:value=[]
        if isinstance(value,str):value=[value]
        return [p for p in (value or []) if Path(p).exists()][:8]

    def remember_recent(self,path):
        try:
            files=[str(path)]+[p for p in self.recent_files() if str(p)!=str(path)]
            settings=platform_support.settings();settings.setValue('recent/files',files[:8]);settings.sync()
        except Exception:pass

    # ---- copy / paste between projects --------------------------------------------------
    def selected_closure(self):
        """The selected feature plus every earlier feature it (directly or indirectly) refers to."""
        index=self.selected
        features=self.doc.features
        if index is None or not 0<=index<len(features):return None
        wanted={index};changed=True
        while changed:
            changed=False
            for i in sorted(wanted):
                text=json.dumps(features[i],default=str)
                for j in range(i):
                    fid=features[j].get('id')
                    if j not in wanted and fid and fid in text:wanted.add(j);changed=True
        return [copy.deepcopy(features[i]) for i in sorted(wanted)]

    def copy_features(self):
        chosen=self.selected_closure()
        if not chosen:
            self.show_status(tr('Select a feature in the history first, then copy it.'));return False
        self.feature_clipboard=chosen
        self.feature_clipboard_parameters=copy.deepcopy(self.doc.parameters)
        try:QApplication.clipboard().setText(json.dumps({CLIPBOARD_MARK:chosen,'parameters':self.doc.parameters},default=str))
        except Exception:pass
        names=', '.join(f.get('name','?') for f in chosen)
        self.show_status(tr('Copied:')+' '+names+' · '+tr('open another project and paste with Ctrl+V.'));return True

    def clipboard_features(self):
        if self.feature_clipboard:return self.feature_clipboard
        try:
            data=json.loads(QApplication.clipboard().text())
            if isinstance(data,dict) and isinstance(data.get(CLIPBOARD_MARK),list):return data[CLIPBOARD_MARK]
        except Exception:pass
        return None

    def paste_features(self):
        source=self.clipboard_features()
        if not source:
            self.show_status(tr('Nothing to paste: copy a feature first (Ctrl+C).'));return False
        if self.current_session() is None:self.ensure_session()
        if not self.abandon():return False
        text=json.dumps(source,default=str)
        for feature in source:
            old=feature.get('id')
            if old:text=text.replace(old,identifier())
        pasted=json.loads(text)
        existing=self.doc.features
        # Parameters the pasted features use come along; a name the project already has keeps its own value.
        carried=getattr(self,'feature_clipboard_parameters',None) or {}
        try:
            data=json.loads(QApplication.clipboard().text())
            if isinstance(data,dict) and isinstance(data.get('parameters'),dict) and data.get(CLIPBOARD_MARK):carried=data['parameters']
        except Exception:pass
        merged=dict(carried);merged.update(self.doc.parameters)
        try:
            self.run_busy('Pasting features…',lambda report:self.doc.commit(existing+pasted,progress=report,parameters=merged))
        except Exception as error:
            self.error(error);return False
        self.selected=len(self.doc.features)-1;self.workspace.set_mode('model');self.refresh(True)
        self.show_status(tr('Pasted features:')+' '+', '.join(f.get('name','?') for f in pasted));return True
