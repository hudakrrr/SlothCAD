"""SlothCAD 0.15.5: main window, toolbars and feature editors."""
import copy
import os
import sys
VERSION='0.15.5'
# The maximum fillet/chamfer size is searched by worker processes without blocking the window.
LIMIT_ASYNC=os.environ.get('QT_QPA_PLATFORM','') not in ('offscreen','minimal') and os.environ.get('SLOTHCAD_SYNC_LIMITS','')!='1'
DEFAULT_EXTRUDE_DEPTH=0.      # a new extrusion starts flat; the depth is set with the arrow or by typing
import splash
splash.begin(VERSION)
splash.step('Loading interface…')
import time
import html
import threading
import math
import numpy as np
from pathlib import Path
from PySide6.QtCore import Qt,Signal,QSize,QEventLoop,QEvent,QPoint,QTimer,QObject,QLocale
from PySide6.QtGui import QAction,QKeySequence,QColor,QActionGroup,QKeyEvent
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QFormLayout,QSplitter,QListWidget,QLabel,QPushButton,QComboBox,QDoubleSpinBox,
    QLineEdit,QCheckBox,QSpinBox,QDialog,QDialogButtonBox,QAbstractItemView,QFileDialog,QMessageBox,QScrollArea,QGroupBox,
    QStackedWidget,QToolButton,QFrame,QSizePolicy,QStyleOptionViewItem,QStyle,QTreeWidget,QTreeWidgetItem,QListWidgetItem,QColorDialog,QProgressBar,QMenu,QInputDialog,QGridLayout)
splash.step('Loading the modelling engine…')
from model import Document,ModelError,new_feature,edge_reference,extrusion_sources,edge_options
from limit_search import maximum_edge_size,warm_up as warm_up_limit_search
from geometry import (new_sketch,base_frame,frame_on_face,sketch_frame,regions,entity,
                      identifier,validate_entity,snap,axes,region_points,sample,profile_regions,regular_polygon,snap_intersections,mirror_entities,circular_entities,rectangular_entities,text_polygons)
splash.step('Loading themes and languages…')
from themes import load_theme,save_theme,apply_theme
from i18n import load_language,save_language,set_language,tr,localize_tree
splash.step('Loading the 3D viewport…')
from workspace import Workspace,prepare_scene_mesh
splash.step('Loading the tools…')
from text_ui import TextUI
from parameters_ui import ParametersUI
from section_ui import SectionUI
from sketch_modify_ui import SketchModifyUI
from pick_slots import SlotUI
from spacemouse_ui import SpaceMouseUI
import auto_constraints
from analysis_ui import AnalysisUI
from expression_spin import ExpressionSpinBox
from option_labels import option_label
from requirements import missing_inputs
from tool_steps import STEPS
from sessions_ui import SessionsUI
import tool_help
import platform_support
from ui_icons import icon
from tool_palette import fit_row,needed_height
from trim import trim_entities
from measure import calculate_measurement
splash.step('Loading CAD kernel…')
import cadquery as cq


class _BusySignals(QObject):
    """Carries progress of a ``run_busy`` job from its worker thread to the interface thread.

    Each signal is connected straight to a C++ slot (QLabel.setText, QProgressBar.setRange /
    setValue, QEventLoop.quit), so delivering it runs no Python on the interface thread.
    """
    text=Signal(str)
    bounds=Signal(int,int)
    value=Signal(int)
    finished=Signal()


class _LimitSignals(QObject):
    """Carries a finished size-limit search from its worker thread to the interface thread."""
    done=Signal(object)


class DrawPalette(QFrame):
    """In-app tool dropdown: no native popup windows or platform menu grabs."""
    def __init__(self,window):
        super().__init__(window.centralWidget());self.window=window;self.setObjectName('drawPalette');self.hide()
        layout=QVBoxLayout(self);layout.setContentsMargins(12,10,12,10);layout.setSpacing(8)
        header=QHBoxLayout();self.header=header;title=QLabel(tr('Draw tools'));title.setProperty('_i18n_text','Draw tools');header.addWidget(title);header.addStretch()
        close=QToolButton();close.setObjectName('paletteClose');close.setProperty('_icon_name','cancel');close.setIcon(icon('cancel'));close.setIconSize(QSize(14,14));close.setFocusPolicy(Qt.NoFocus);close.setToolTip(tr('Close'));close.clicked.connect(self.dismiss);header.addWidget(close);layout.addLayout(header)
        self.scroll=QScrollArea();self.scroll.setFrameShape(QFrame.NoFrame);self.scroll.setWidgetResizable(True);self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);layout.addWidget(self.scroll)
        content=QWidget();self.grid=QGridLayout(content);self.grid.setContentsMargins(2,2,8,2);self.grid.setSpacing(6);self.scroll.setWidget(content)
        self.buttons=[];self.row=0

    def showEvent(self,event):
        QApplication.instance().installEventFilter(self);super().showEvent(event)

    def hideEvent(self,event):
        QApplication.instance().removeEventFilter(self);super().hideEvent(event)

    def section(self,title,tools):
        label=QLabel(tr(title));label.setObjectName('groupTitle');label.setProperty('_i18n_text',title);self.grid.addWidget(label,self.row,0,1,2);self.row+=1
        for i,(label,tool,handler) in enumerate(tools):
            button=QToolButton();button.setText(tr(label));button.setProperty('_i18n_text',label);button.setProperty('_icon_name',tool);button.setProperty('_tool',tool)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);button.setIcon(icon(tool));button.setIconSize(QSize(24,24));button.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed);fit_row(button)
            def activate(checked=False,callback=handler):
                self.dismiss();callback()
            button.clicked.connect(activate);self.grid.addWidget(button,self.row+i//2,i%2);self.buttons.append(button)
        self.row+=(len(tools)+1)//2

    def open(self,anchor):
        parent=self.parentWidget();width=min(600,parent.width()-16)
        point=anchor.mapTo(parent,QPoint(0,anchor.height()+4))
        x=max(8,min(point.x(),parent.width()-width-8));y=point.y()
        height=min(needed_height(self,self.header,self.scroll),parent.height()-y-8)
        self.setGeometry(x,y,width,max(100,height));self.show();self.raise_()
        if self.buttons:self.buttons[0].setFocus(Qt.PopupFocusReason)

    def dismiss(self):
        self.hide()
        if hasattr(self.window,'workspace'):self.window.workspace.setFocus()

    def eventFilter(self,obj,event):
        if self.isVisible():
            if event.type()==QEvent.ShortcutOverride and event.key()==Qt.Key_Escape:
                event.accept();return True
            if event.type()==QEvent.KeyPress and event.key()==Qt.Key_Escape:
                self.dismiss();return True
            if event.type()==QEvent.MouseButtonPress:
                point=event.globalPosition().toPoint()
                own=isinstance(obj,QWidget) and (obj is self or self.isAncestorOf(obj))
                inside=own or self.rect().contains(self.mapFromGlobal(point));anchor=self.window.draw_menu_button
                if not inside and not anchor.rect().contains(anchor.mapFromGlobal(point)):
                    on_ribbon=self.window.toolbar_contains(point)
                    self.dismiss();return not on_ribbon
            if obj is self.window and event.type() in (QEvent.Resize,QEvent.WindowDeactivate):self.hide()
        return super().eventFilter(obj,event)

class CollapsibleSection(QWidget):
    """Disclosure arrow: expanding details is separate from enabling a feature."""
    def __init__(self,title,content,expanded,changed,parent=None):
        super().__init__(parent);self._title=title
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(4)
        self.header=QToolButton();self.header.setText(title);self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);self.header.setCheckable(True);self.header.setChecked(expanded)
        self.header.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed);self.header.setStyleSheet('text-align: left;');layout.addWidget(self.header);layout.addWidget(content)
        def toggle(on):
            self.header.setArrowType(Qt.DownArrow if on else Qt.RightArrow);content.setVisible(on);changed(on)
        self.header.toggled.connect(toggle);toggle(expanded)
    def title(self):return self._title
    def isChecked(self):return self.header.isChecked()

class TimelineButton(QToolButton):
    double_clicked=Signal()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:self.double_clicked.emit();event.accept();return
        super().mouseDoubleClickEvent(event)

class VisibilityTree(QTreeWidget):
    """Double-clicking an eye/checkbox never activates sketch editing."""
    def checkbox_at(self,position):
        index=self.indexAt(position)
        if not index.isValid():return False
        option=QStyleOptionViewItem();self.initViewItemOption(option)
        self.itemDelegate().initStyleOption(option,index);option.rect=self.visualRect(index)
        if not option.features & QStyleOptionViewItem.HasCheckIndicator:return False
        rect=self.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator,option,self)
        return rect.contains(position)
    def mouseDoubleClickEvent(self,event):
        if self.checkbox_at(event.position().toPoint()):event.accept();return
        super().mouseDoubleClickEvent(event)

from body_ui import BodyUI
from body_tools import BODY_TOOLS,LABELS as BODY_LABELS
from solid_ui import SolidUI
from solid_tools import CONSTRUCTIONS,SOLID_TOOLS
from constraint_ui import ConstraintUI
from constraints import edit_entity,retain_constraints

from exchange_ui import ExchangeUI
from recovery import RecoveryUI,Autosave

from gizmo_ui import GizmoUI
from projection_ui import ProjectionUI
from advanced_ui import AdvancedUI,ADVANCED_TOOLS
from assembly_ui import AssemblyUI
from assemblies import ASSEMBLY_TOOLS
from spatial_ui import SpatialUI
from spatial_sketch import SPATIAL_TOOLS

def is_number_box(obj):
    from PySide6.QtWidgets import QAbstractSpinBox
    if isinstance(obj,QAbstractSpinBox):return True
    return isinstance(obj,QWidget) and isinstance(obj.parent(),QAbstractSpinBox)


def use_decimal_point_locale():
    """CAD values are typed with a decimal point everywhere.

    Qt otherwise follows the system locale, so on a Hungarian (or German, French...)
    system "7.5" was read as 75. Commas are converted to points while typing
    (see EscapeFilter), so both work.
    """
    locale=QLocale(QLocale.English,QLocale.UnitedStates)
    locale.setNumberOptions(QLocale.OmitGroupSeparator|QLocale.RejectGroupSeparator)
    QLocale.setDefault(locale)


class ToolHelpFilter(QObject):
    """Right-click on any tool button (ribbon, drop-down list, draw palette) opens its description."""
    def __init__(self,window):
        super().__init__(window);self.window=window
    def eventFilter(self,obj,event):
        kind=event.type()
        if kind not in (QEvent.MouseButtonPress,QEvent.MouseButtonRelease) or not isinstance(obj,QWidget):return False
        if event.button()!=Qt.RightButton:return False
        widget=obj
        while widget is not None:
            key=widget.property('_icon_name') or widget.property('_tool')
            if key and tool_help.help_for(key) is not None and hasattr(widget,'text'):
                if kind==QEvent.MouseButtonPress:
                    title=widget.property('_i18n_text');title=tr(title) if title else widget.text().replace('&','').replace(' ›','').strip()
                    action=widget.property('_action')
                    if action is not None and not title:title=action.text()
                    QTimer.singleShot(0,lambda k=key,t=title:tool_help.show_tool_help(self.window,k,t))
                return True
            widget=widget.parentWidget()
        return False


class LayoutWatcher(QObject):
    """Re-fits the floating panels whenever the tool settings content changes size."""
    def __init__(self,window):
        super().__init__(window);self.window=window
    def eventFilter(self,obj,event):
        if event.type() in (QEvent.LayoutRequest,QEvent.Resize,QEvent.ChildAdded,QEvent.ChildRemoved):self.window.schedule_float_layout()
        return False


class EscapeFilter(QObject):
    """Esc leaves whatever tool is active, wherever the keyboard focus is in the window."""
    def __init__(self,window):
        super().__init__(window);self.window=window
    def eventFilter(self,obj,event):
        # Installed on the whole application, so every mouse move and paint passes through
        # here; only key presses matter, and the common case must cost one comparison.
        if event.type()!=QEvent.KeyPress:return False
        if event.type()==QEvent.KeyPress and event.text()==',' and is_number_box(obj):
            # Number boxes use a decimal point; a comma (Hungarian keyboards, the numpad
            # decimal key on many layouts) types one too instead of being ignored.
            QApplication.sendEvent(obj,QKeyEvent(QEvent.KeyPress,Qt.Key_Period,event.modifiers(),'.'));return True
        if event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Return,Qt.Key_Enter) and not (event.modifiers()&~Qt.KeypadModifier):
            try:
                widget=obj if isinstance(obj,QWidget) else None
                if widget is not None and widget.window() is self.window and QApplication.activeModalWidget() is None:
                    if self.window.enter_pressed(widget):return True
            except RuntimeError:
                return False
        if event.type()==QEvent.KeyPress and event.key()==Qt.Key_Escape and not event.modifiers():
            try:
                widget=obj if isinstance(obj,QWidget) else None
                if widget is not None and widget.window() is self.window and QApplication.activeModalWidget() is None:
                    if self.window.escape_pressed():return True
            except RuntimeError:
                # A closed test/secondary window whose Qt object is already gone.
                return False
        return False


class Window(SpaceMouseUI,SlotUI,SketchModifyUI,AnalysisUI,SectionUI,ParametersUI,SessionsUI,SpatialUI,AssemblyUI,AdvancedUI,ProjectionUI,GizmoUI,ExchangeUI,RecoveryUI,BodyUI,SolidUI,ConstraintUI,TextUI,QMainWindow):
    def __init__(self,start_with_project=True):
        use_decimal_point_locale()
        if os.environ.get('QT_QPA_PLATFORM','') in ('offscreen','minimal'):
            # Headless runs (tests, validation) have no event loop, so Qt never executes the
            # deleteLater() of earlier windows: each stayed alive with its application-wide
            # event filter and every further window was slower than the last (quadratic).
            import gc
            QApplication.sendPostedEvents(None,QEvent.DeferredDelete);gc.collect()
        super().__init__()
        self.language=load_language();set_language(self.language)
        self.theme=load_theme();apply_theme(QApplication.instance(),self.theme)
        self.pattern_axis=None;self.pattern_center=None;self.pattern_copies=5;self.pattern_columns=3;self.pattern_rows=2;self.pattern_spacing_x=10.;self.pattern_spacing_y=10.;self.expanded_sections={};self.preview_active=False;self.extrude_hits=[];self.object_tree_signature=None;self.timeline_signature=None;self.history_preview_index=None
        self.edge_size_limit=None;self.edge_size_limit_bounded=True;self.edge_limit_cache={};self.edge_limit_pending=None;self.edge_limit_provisional=None;self._limit_signals=_LimitSignals(self);self._limit_signals.done.connect(self.edge_limit_ready)
        self.component_stack=[];self.doc=Document();self.path=None;self.saved_features=[];self.saved_display={};self.selected=None
        self.draft=None;self.draft_index=None;self.loading=False;self.widgets={}
        self.entity_index=None;self.sketch_undo=[];self.sketch_redo=[];self.precise_draft=None;self.precise_baseline=None;self.precise_redo=None
        self.saved_display={};self.resize(1440,940);self.make_actions()
        container=QWidget();outer=QVBoxLayout(container);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0);self.setCentralWidget(container)
        self.ribbon=QStackedWidget();self.ribbon.setObjectName('ribbon');self.ribbon.setFixedHeight(80)
        self.body_bar=QWidget();self.body_bar.setObjectName('contextBar');body_layout=QHBoxLayout(self.body_bar);body_layout.setContentsMargins(14,3,14,3);body_layout.setSpacing(12)
        self.body_buttons={}
        self.ribbon_group(body_layout,'CREATE',[('Create sketch','sketch',self.start_sketch),('Extrude','extrude',self.start_extrude),('Solid tools','solid_tools',lambda:None),('Body patterns','body_patterns',lambda:None)],self.body_buttons)
        self.ribbon_group(body_layout,'MODIFY',[('Fillet','fillet',lambda:self.new_edge('fillet')),('Chamfer','chamfer',lambda:self.new_edge('chamfer')),('More modify','solid_modify',lambda:None),('Body tools','body_tools',lambda:None)],self.body_buttons)
        self.ribbon_group(body_layout,'CONSTRUCT',[('Construct','construct',lambda:None)],self.body_buttons)
        body_layout.addStretch()
        self.sketch_bar=QWidget();self.sketch_bar.setObjectName('contextBar');sketch_layout=QHBoxLayout(self.sketch_bar);sketch_layout.setContentsMargins(14,3,14,3);sketch_layout.setSpacing(8);self.tool_buttons={}
        self.draw_palette=self.make_draw_palette()
        self.ribbon_group(sketch_layout,'CREATE',[('Select','select',lambda:self.set_tool('select')),('Line','line',lambda:self.set_tool('line')),('Arc','arc',lambda:self.set_tool('arc')),('Rectangle','rectangle',lambda:self.set_tool('rectangle')),('Circle','circle',lambda:self.set_tool('circle')),('Project / Include','project',self.start_projection),('Mirror','mirror',lambda:self.start_pattern('mirror')),('Circular','circular',lambda:self.start_pattern('circular'))],self.tool_buttons,True,self.draw_palette)
        self.ribbon_group(sketch_layout,'MODIFY',[('Fillet','fillet',lambda:self.set_tool('fillet')),('Chamfer','chamfer',lambda:self.set_tool('chamfer')),('Trim','trim',lambda:self.set_tool('trim')),('Extend','extend',lambda:self.set_tool('extend')),('Offset','offset',lambda:self.start_pattern('offset')),('Move','sketch_move',self.start_sketch_move)],self.tool_buttons,True)
        self.ribbon_group(sketch_layout,'CONSTRAINTS',[('Constraints','constraint',lambda:None)],self.tool_buttons,True)
        self.ribbon_group(sketch_layout,'CONSTRUCT',[('Guide','construction',self.toggle_construction)],self.tool_buttons,True)
        sketch_layout.addStretch()
        self.ribbon.addWidget(self.body_bar);self.ribbon.addWidget(self.sketch_bar)
        top=QWidget();self.tool_bar=top;top.setObjectName('contextBar');top_layout=QHBoxLayout(top);top_layout.setContentsMargins(0,0,10,0);top_layout.setSpacing(0)
        # Scrolling part: the mode's tools, then the less frequent Inspect tools.
        row=QWidget();row.setObjectName('contextBar');row_layout=QHBoxLayout(row);row_layout.setContentsMargins(0,0,0,0);row_layout.setSpacing(12)
        row_layout.addWidget(self.ribbon,0,Qt.AlignTop)
        measure_group={}
        measure_panel=self.ribbon_group(row_layout,'INSPECT',[('Measure','measure',self.toggle_measure),('Repair','repair',self.open_reference_recovery)],measure_group,True)
        self.inspect_buttons=measure_group;self.measure_button=measure_group['measure'];measure_group['repair'].setCheckable(False)
        # Match the mode ribbon's 3 px top inset so Inspect actions share the
        # exact same top baseline as sketch and solid tools.
        measure_panel.layout().setContentsMargins(4,3,4,0)
        measure_panel.setFixedHeight(80);row_layout.setAlignment(measure_panel,Qt.AlignTop);row_layout.addStretch(1)
        self.ribbon_scroll=QScrollArea();self.ribbon_scroll.setObjectName('ribbonScroll');self.ribbon_scroll.setWidgetResizable(True);self.ribbon_scroll.setFrameShape(QFrame.NoFrame);self.ribbon_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);self.ribbon_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.ribbon_scroll.setWidget(row);self.ribbon_scroll.setFixedHeight(88);top_layout.addWidget(self.ribbon_scroll,1)
        # Fixed right side: what mode you are in, and Finish/Cancel when a sketch is open.
        fixed=QWidget();fixed.setObjectName('contextBar');self.mode_area=fixed;fixed_layout=QHBoxLayout(fixed);fixed_layout.setContentsMargins(8,3,4,0);fixed_layout.setSpacing(10)
        self.body_mode_badge,self.body_mode_label=self.mode_badge('MODE','SOLID')
        self.sketch_mode_badge,self.sketch_mode_label=self.mode_badge('MODE','SKETCH');self.sketch_mode_badge.setMinimumWidth(110);self.sketch_mode_label.setMinimumWidth(70)
        for badge in (self.body_mode_badge,self.sketch_mode_badge):fixed_layout.addWidget(badge,0,Qt.AlignVCenter)
        self.sketch_actions={}
        self.sketch_action_group=self.ribbon_group(fixed_layout,'SKETCH',[('Finish','finish',self.finish_sketch),('Cancel','cancel',self.cancel)],self.sketch_actions)
        self.sketch_actions['finish'].setToolTip(tr('Finish sketch'));self.sketch_actions['cancel'].setToolTip(tr('Cancel sketch'))
        self.sketch_action_group.setFixedHeight(80);fixed_layout.setAlignment(self.sketch_action_group,Qt.AlignTop)
        self.sketch_mode_badge.hide();self.sketch_action_group.hide()
        fixed.setFixedHeight(88);top_layout.addWidget(fixed,0)
        self.measure_action=QAction(icon('measure'),tr('Measure'),self);self.measure_action.setProperty('_icon_name','measure');self.measure_action.setShortcut('M');self.measure_action.triggered.connect(self.toggle_measure);self.addAction(self.measure_action);self.actions['Measure']=self.measure_action
        self.measure_button.setToolTip(tr('Measure · M'))
        outer.addWidget(top);self.ribbon_container=top
        # The workspace spans the whole width; the browser (left) and the tool settings (right)
        # float over it as compact panels, like Fusion, instead of two full-height bars.
        # The browser is not a window: a slim header strip with the tree sitting straight on the
        # canvas (transparent), like Fusion's BROWSER.
        left=QFrame();left.setObjectName('browserPanel');layout=QVBoxLayout(left);layout.setContentsMargins(0,0,0,0);layout.setSpacing(2)
        header_bar=QFrame();header_bar.setObjectName('browserHeader');header=QHBoxLayout(header_bar);header.setContentsMargins(10,3,4,3)
        title=QLabel(tr('BROWSER'));title.setObjectName('groupTitle');header.addWidget(title,1)
        self.collapse_browser=QToolButton();self.collapse_browser.setObjectName('browserCollapse');self.collapse_browser.setText('–');self.collapse_browser.setToolTip(tr('Collapse / expand'));self.collapse_browser.setFocusPolicy(Qt.NoFocus)
        header.addWidget(self.collapse_browser);layout.addWidget(header_bar)
        self.objects=VisibilityTree();self.objects.setObjectName('objectBrowser');self.objects.setHeaderHidden(True);self.objects.setColumnCount(1);self.objects.setIconSize(QSize(18,18));self.objects.setIndentation(16);self.objects.setUniformRowHeights(True)
        self.objects.itemChanged.connect(self.visibility_changed);self.objects.itemClicked.connect(self.object_clicked);self.objects.itemDoubleClicked.connect(self.object_edit);layout.addWidget(self.objects,1)
        hint=QLabel(tr('Check to show · Double-click sketch to edit'));hint.setWordWrap(True);hint.setObjectName('subtle');layout.addWidget(hint)
        self.browser_parts=[self.objects];self.float_left=left
        self.objects.setFrameShape(QFrame.NoFrame);self.objects.viewport().setAutoFillBackground(False);hint.hide();self.objects.setToolTip(tr('Check to show · Double-click sketch to edit'))
        self.workspace=Workspace();self.workspace.support_picked.connect(self.support_picked)
        self.workspace.measure_picked.connect(self.measure_picked);self.workspace.box_selected.connect(self.box_selected);self.workspace.extrusion_picked.connect(self.extrusion_picked);self.workspace.entity_created.connect(self.add_entity)
        self.workspace.tool_requested.connect(self.set_tool);self.workspace.construction_requested.connect(self.toggle_construction);self.workspace.delete_requested.connect(self.delete_entity);self.workspace.trim_requested.connect(self.trim_entity);self.workspace.corner_requested.connect(self.toggle_sketch_corner);self.workspace.entity_picked.connect(self.select_entity);self.workspace.pattern_selection_changed.connect(self.pattern_selection_changed);self.workspace.mirror_axis_picked.connect(self.set_mirror_axis);self.workspace.pattern_center_picked.connect(self.set_pattern_center);self.workspace.edge_selection_changed.connect(self.edge_selection_changed);self.workspace.message.connect(self.show_status)
        self.init_slots();self.init_spacemouse();self.init_constraints();self.init_solid_tools();self.init_body_tools();self.init_projection();self.init_advanced_tools();self.init_assemblies();self.init_spatial()
        self.init_sessions()
        self.stack=QStackedWidget();self.stack.addWidget(self.workspace);self.stack.addWidget(self.welcome);outer.addWidget(self.stack,1)
        left.setParent(self.workspace);left.show()
        self.float_timer=QTimer(self);self.float_timer.setSingleShot(True);self.float_timer.setInterval(0);self.float_timer.timeout.connect(self.position_float_panels)
        self.collapse_browser.clicked.connect(self.toggle_browser)
        self.objects.itemExpanded.connect(lambda *_:self.schedule_float_layout());self.objects.itemCollapsed.connect(lambda *_:self.schedule_float_layout())
        self.viewport_tools=QFrame(self.workspace);self.viewport_tools.setObjectName('viewportTools');controls=QHBoxLayout(self.viewport_tools);controls.setContentsMargins(6,4,6,4);controls.setSpacing(3)
        self.view_selector=QComboBox();self.view_selector.setSizeAdjustPolicy(QComboBox.AdjustToContents);self.view_selector.setToolTip(tr('Camera orientation · saved views'))
        self.populate_view_selector();self.view_selector.currentIndexChanged.connect(self.view_selected);controls.addWidget(self.view_selector)
        for name,label in [('fit','Fit'),('perspective','Perspective view'),('section','Section view'),('grid','Grid'),('axes','Axes'),('aa','Smooth edges')]:
            b=QToolButton();b.setProperty('_icon_name',name);b.setIcon(icon(name));b.setIconSize(QSize(22,22));b.setText(tr(label));b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            tips={'aa':tr('Smooth edges · GPU supersampling (16× on small viewports, 4× otherwise); falls back to MSAA when needed'),'fit':tr('Fit all visible objects · Z: zoom to the selection'),
                  'perspective':tr('Perspective camera (sketches always use the orthographic view)'),'section':tr('Section view: cut the model with a movable plane')}
            b.setToolTip(tips.get(name,tr(label)+' '+tr('display')))
            if name=='fit':b.clicked.connect(lambda:self.workspace.fit())
            elif name=='perspective':b.setCheckable(True);b.setChecked(False);b.toggled.connect(self.set_perspective);setattr(self,name+'_button',b)
            elif name=='section':b.setCheckable(True);b.setChecked(False);b.toggled.connect(self.toggle_section);setattr(self,name+'_button',b)
            else:b.setCheckable(True);b.setChecked(True);b.toggled.connect(lambda v,k=name:self.viewport_setting(k,v));setattr(self,name+'_button',b)
            controls.addWidget(b)
        self.init_section()
        self.viewport_tools.adjustSize();self.workspace.resized.connect(self.position_viewport_tools)
        self.graphics_warning=QToolButton(self.workspace);self.graphics_warning.setObjectName('graphicsWarning')
        self.graphics_warning.setProperty('_icon_name','warning');self.graphics_warning.setIcon(icon('warning'));self.graphics_warning.setIconSize(QSize(24,24));self.graphics_warning.setFixedSize(34,34)
        self.graphics_warning.setToolTip(tr('Graphics issue · Click to view details'));self.graphics_warning.setAccessibleName(tr('Graphics issues'))
        self.graphics_warning.clicked.connect(self.show_graphics_issues);self.graphics_warning.hide()
        self.workspace.graphics_issue.connect(self.update_graphics_warning)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(260);self.editor=QWidget();self.editor_layout=QVBoxLayout(self.editor);self.editor_layout.setContentsMargins(10,10,10,10);self.editor_layout.setSpacing(8);scroll.setWidget(self.editor);scroll.setFrameShape(QFrame.NoFrame)
        right=QFrame(self.workspace);right.setObjectName('floatPanel');right_layout=QVBoxLayout(right);right_layout.setContentsMargins(1,1,1,1);right_layout.addWidget(scroll);self.float_right=right;right.show()
        self.layout_watcher=LayoutWatcher(self);self.editor.installEventFilter(self.layout_watcher)
        self.workspace.resized.connect(self.schedule_float_layout)
        self.timeline=QWidget();self.timeline.setObjectName('timeline');self.timeline_layout=QHBoxLayout(self.timeline);self.timeline_layout.setContentsMargins(6,4,10,4);self.timeline_layout.setSpacing(5)
        # Give checked timeline buttons enough vertical room for their rounded outline.  The old
        # 38 px viewport clipped the lower border directly against the status bar on Fedora.
        self.timeline_scroll=QScrollArea();self.timeline_scroll.setObjectName('timelineScroll');self.timeline_scroll.setWidgetResizable(True);self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.timeline_scroll.setFixedHeight(44);self.timeline_scroll.setWidget(self.timeline)
        history_bar=QWidget();history_bar.setObjectName('historyBar');history_layout=QHBoxLayout(history_bar);history_layout.setContentsMargins(6,1,0,1);history_layout.setSpacing(3)
        self.undo_button=QToolButton();self.undo_button.setObjectName('historyUndo');self.undo_button.setDefaultAction(self.undo_action);self.undo_button.setProperty('_icon_name','undo');self.undo_button.setIcon(icon('undo'));self.undo_button.setIconSize(QSize(20,20));self.undo_button.setToolButtonStyle(Qt.ToolButtonIconOnly);self.undo_button.setToolTip(tr('Undo · Ctrl+Z'));history_layout.addWidget(self.undo_button)
        self.redo_button=QToolButton();self.redo_button.setObjectName('historyRedo');self.redo_button.setDefaultAction(self.redo_action);self.redo_button.setProperty('_icon_name','redo');self.redo_button.setIcon(icon('redo'));self.redo_button.setIconSize(QSize(20,20));self.redo_button.setToolButtonStyle(Qt.ToolButtonIconOnly);self.redo_button.setToolTip(tr('Redo · Ctrl+Shift+Z'));history_layout.addWidget(self.redo_button)
        history_layout.addWidget(self.timeline_scroll,1);outer.addWidget(history_bar);self.history_container=history_bar
        self.busy_label=QLabel('');self.busy_label.setObjectName('subtle');self.busy_label.hide()
        self.busy_progress=QProgressBar();self.busy_progress.setTextVisible(False);self.busy_progress.setFixedWidth(220);self.busy_progress.setFixedHeight(12);self.busy_progress.hide()
        self.statusBar().addPermanentWidget(self.busy_label);self.statusBar().addPermanentWidget(self.busy_progress)
        self.busy_signals=_BusySignals(self);self.busy_signals.text.connect(self.busy_label.setText)
        self.busy_signals.bounds.connect(self.busy_progress.setRange);self.busy_signals.value.connect(self.busy_progress.setValue)
        # One event loop for every busy job, connected once. A per-job local loop crashed: a
        # finished signal still queued when the job returned was later delivered to the deleted loop.
        # A stale quit reaching this loop is harmless (run_busy re-enters it until its job is done).
        self.busy_loop=QEventLoop(self);self.busy_signals.finished.connect(self.busy_loop.quit)
        self.refresh(fit=True);self.workspace.set_mode('support');self.show_editor();localize_tree(self.centralWidget());self.autosave=Autosave(self)
        self.escape_filter=EscapeFilter(self);QApplication.instance().installEventFilter(self.escape_filter)
        self.help_filter=ToolHelpFilter(self);QApplication.instance().installEventFilter(self.help_filter)
        if start_with_project:self.register_session()
        else:self.show_welcome()
        self.fit_ribbon_buttons();QTimer.singleShot(0,self.fit_ribbon_buttons)
        # Load the CAD kernel in the background process used for exports and analysis ahead of time.
        from kernel_process import KERNEL;QTimer.singleShot(4000,KERNEL.warm_up)

    def show_status(self,text,*args):
        self.statusBar().showMessage(tr(text),*args)

    def run_busy(self,label,operation):
        """Run CAD/OCC work off the GUI thread without ever freezing the window.

        The CAD kernel keeps Python's GIL for the whole of a kernel call, which can last
        seconds. Any Python the interface thread wants to run meanwhile (a paint event, an
        event filter, this function's own polling loop) has to wait for that call to end, and
        if that adds up to a few seconds the desktop reports the window as not responding.
        So after a short grace period the interface thread waits in a plain Qt event loop:
        progress arrives as signals wired to C++ slots, the worker ends the loop with a signal,
        the viewport (painted in Python) keeps its last frame and the application-wide Python
        event filters are paused. Window-manager pings, the status bar and the progress bar
        are all handled in C++ and keep working however long a single kernel call takes.
        """
        if self.loading:
            return operation(lambda *_:None)
        self.loading=True;central=self.centralWidget();signals=self.busy_signals
        state={'done':0,'total':0,'text':label,'finished':False,'result':None,'error':None,'shown':False,'sent':(None,None,None),'sent_at':0.}
        def publish(force=False):
            # Runs on the worker thread; only changes are sent, at most ~30 times a second.
            total=state['total'];done=state['done'];text=tr(state['text'])
            bounds=(0,total) if total>1 else (0,0);value=max(0,min(total,done)) if total>1 else 0
            now=time.monotonic()
            if not force and now-state['sent_at']<.033:return
            last_text,last_bounds,last_value=state['sent']
            if text!=last_text:signals.text.emit(text)
            if bounds!=last_bounds:signals.bounds.emit(*bounds)
            if value!=last_value:signals.value.emit(value)
            state['sent']=(text,bounds,value);state['sent_at']=now
        def report(done,total,text=''):
            state['done']=int(done);state['total']=max(0,int(total));state['text']=text or label
            if state['shown']:publish()
        def worker():
            try:
                from mesh_cache import KERNEL_LOCK
                with KERNEL_LOCK:state['result']=operation(report)
            except BaseException as err:state['error']=err
            finally:
                state['finished']=True
                try:signals.finished.emit()
                except RuntimeError:pass       # window already destroyed
        loop=self.busy_loop
        thread=threading.Thread(target=worker,name='SlothCAD-CAD-worker',daemon=True)
        # Most jobs take a few milliseconds; greying out and re-enabling the whole widget tree
        # costs ~20 ms each time, so the busy state is only shown for jobs that really last.
        started=time.monotonic();thread.start()
        while not state['finished'] and time.monotonic()-started<.15:
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents,20);thread.join(.01)
        paused=[]
        try:
            if not state['finished']:
                application=QApplication.instance()
                for name in ('escape_filter','help_filter'):
                    watcher=getattr(self,name,None)
                    if watcher is not None:application.removeEventFilter(watcher);paused.append(watcher)
                central.setUpdatesEnabled(False);central.setEnabled(False);self.setCursor(Qt.WaitCursor)
                self.busy_label.setText(tr(label));self.busy_progress.setRange(0,0);self.busy_label.show();self.busy_progress.show()
                state['shown']=True;publish(True)
                # Safety net in case the finished signal were ever lost: a rare check, not polling.
                guard=QTimer();guard.setInterval(1000);guard.timeout.connect(lambda:state['finished'] and loop.quit());guard.start()
                while not state['finished']:loop.exec(QEventLoop.ExcludeUserInputEvents)
                guard.stop()
            thread.join()
        finally:
            if state['shown']:
                self.busy_progress.hide();self.busy_label.hide();central.setEnabled(True);central.setUpdatesEnabled(True);self.unsetCursor()
            for watcher in paused:QApplication.instance().installEventFilter(watcher)
            self.loading=False
        if state['error'] is not None:raise state['error']
        return state['result']

    def prepare_sketch_data(self,sketches,report,profiles=False):
        display={};faces={};snaps={}
        for index,sketch in enumerate(sketches):
            key=repr(sketch['entities']);id_=sketch['id'];cached=self.workspace.sketch_cache.get(id_)
            if cached and cached[0]==key:display[id_]=cached
            else:
                loops=regions(sketch)
                display[id_]=(key,[(ids,region_points(sketch,ids)) for ids in loops],[(i,e,sample(e)) for i,e in enumerate(sketch['entities'])],{entity_id for ids in loops for entity_id in ids})
            if profiles:
                cached=self.workspace.profile_cache.get(id_)
                faces[id_]=cached if cached and cached[0]==key else (key,profile_regions(sketch))
            if self.workspace.mode=='sketch' and self.workspace.active and id_==self.workspace.active['id']:
                snaps[id_]=(key,self.workspace.snap_cache_intersections if self.workspace.snap_cache_key==key else snap_intersections(sketch['entities']))
            report(index+1,len(sketches),'Preparing sketch regions…')
        return display,faces,snaps

    def install_sketch_data(self,data):
        display,faces,snaps=data;self.workspace.sketch_cache.update(display);self.workspace.profile_cache.update(faces)
        if self.workspace.active and self.workspace.active['id'] in snaps:
            self.workspace.snap_cache_key,self.workspace.snap_cache_intersections=snaps[self.workspace.active['id']]

    def prepare_active_sketch(self):
        w=self.workspace
        if w.mode!='sketch' or not w.active:return
        entry=w.sketch_cache.get(w.active['id']);key=repr(w.active['entities'])
        if entry and entry[0]==key:return
        snapshot=copy.deepcopy(w.active);w.preparing_sketches=True
        try:data=self.run_busy('Preparing sketch…',lambda report:self.prepare_sketch_data([snapshot],report))
        finally:w.preparing_sketches=False
        self.install_sketch_data(data)

    def set_scene_responsive(self,solid,sketches,fit=False,materials=None,draft=False,volume_of=None):
        """Show ``solid``; ``draft`` uses the coarse live-preview mesh (the final mesh replaces it later).

        ``volume_of``: a CadQuery workplane whose volume is also computed in the background job and
        returned (a kernel call that takes long for big imported meshes, so never on this thread)."""
        materials=self.body_materials() if materials is None else materials
        needs_mesh=not self.workspace.geometry_matches(solid,draft)
        snapshots=[copy.deepcopy(sketch) for sketch,frame in sketches if not frame.get("spatial")]
        profiles=self.workspace.mode=='extrude' or self.workspace.extrude_selecting
        cached=getattr(self,'_volume_cache',(None,0.))
        def prepare(report):
            mesh=prepare_scene_mesh(solid,report,draft) if needs_mesh else None
            volume=None
            if volume_of is not None:
                volume=cached[1] if cached[0] is volume_of else volume_of.val().Volume()
            return mesh,self.prepare_sketch_data(snapshots,report,profiles),volume
        self.workspace.preparing_sketches=True
        try:mesh,data,volume=self.run_busy('Preparing viewport…',prepare)
        finally:self.workspace.preparing_sketches=False
        if volume_of is not None:self._volume_cache=(volume_of,volume)
        self.workspace.set_scene(solid,sketches,fit,materials=materials,prepared=mesh,draft=draft);self.install_sketch_data(data)
        return volume

    def mode_badge(self,caption,text):
        frame=QFrame();frame.setObjectName('modeBadgeFrame')
        # Long states such as SELECT PLANE / EXTRUDE SELECT must never be clipped.
        # Let the label drive the size while keeping the indicator compact.
        frame.setMinimumWidth(124);frame.setMaximumWidth(200);frame.setSizePolicy(QSizePolicy.Minimum,QSizePolicy.Fixed)
        layout=QVBoxLayout(frame);layout.setContentsMargins(10,2,10,2);layout.setSpacing(0);layout.setAlignment(Qt.AlignVCenter);frame.setFixedHeight(46)
        head=QLabel(tr(caption));head.setObjectName('modeBadgeCaption');head.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        value=QLabel(tr(text));value.setObjectName('modeBadgeValue');value.setAlignment(Qt.AlignLeft|Qt.AlignVCenter);value.setMinimumWidth(100);value.setSizePolicy(QSizePolicy.Minimum,QSizePolicy.Preferred)
        layout.addWidget(head);layout.addWidget(value)
        return frame,value

    def ribbon_group(self,parent,title,tools,registry,checkable=False,caption_menu=None):
        group=QWidget();group.setObjectName('toolGroup');layout=QVBoxLayout(group);layout.setContentsMargins(4,0,4,0);layout.setSpacing(0);row=QHBoxLayout();row.setSpacing(6)
        for label,key,fn in tools:
            glyph='sketch_'+key if registry is getattr(self,'tool_buttons',None) and key in ('fillet','chamfer') else key
            b=QToolButton();b.setText(tr(label));b.setProperty('_i18n_text',label);b.setProperty('_icon_name',glyph);b.setIcon(icon(glyph));b.setIconSize(QSize(26,26));b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);b.ensurePolished();b.setMinimumWidth(max(64,b.sizeHint().width()));b.setMinimumHeight(54);b.setCheckable(checkable)
            b.setToolTip(tr({'finish':'Finish sketch','cancel':'Cancel sketch','circular':'Circular pattern'}.get(key,label)));b.clicked.connect(fn);row.addWidget(b);registry[key]=b
        layout.addLayout(row)
        if caption_menu is None:
            caption=QLabel(tr(title));caption.setObjectName('groupTitle');caption.setAlignment(Qt.AlignCenter);caption.setFixedHeight(15)
        else:
            caption=QPushButton();caption.setObjectName('drawMenuButton');caption.setText(tr('Draw tools')+'  ▾');caption.setMinimumHeight(18);caption.setFixedHeight(20);caption.setFocusPolicy(Qt.StrongFocus);caption.setToolTip(tr('More sketch drawing tools'))
            self.draw_menu_button=caption;caption.clicked.connect(self.show_draw_menu)
        layout.addWidget(caption)
        if parent.count():
            # Thin divider between ribbon groups, like CAD ribbons, so groups read as units.
            divider=QFrame();divider.setObjectName('ribbonDivider');divider.setFixedWidth(1);divider.setFrameShape(QFrame.NoFrame);parent.addWidget(divider)
        parent.addWidget(group);return group

    def toolbar_contains(self,point):
        return any(widget.rect().contains(widget.mapFromGlobal(point)) for widget in (self.tool_bar,self.menuBar()))

    def show_draw_menu(self):
        if self.workspace.mode!='sketch' or self.loading:return
        for palette in getattr(self,'tool_palettes',{}).values():palette.dismiss()
        if self.draw_palette.isVisible():self.draw_palette.dismiss()
        else:self.draw_palette.open(self.draw_menu_button)

    def make_draw_palette(self):
        palette=DrawPalette(self)
        def tool(label,name,handler=None):return (label,name,handler or (lambda t=name:self.set_tool(t)))
        palette.section('Line',[tool('Line','line')])
        palette.section('Rectangle',[tool('Corner rectangle','rectangle'),tool('Center rectangle','center_rectangle'),tool('3-point rectangle','rectangle_3p')])
        palette.section('Circle',[tool('Center-radius circle','circle'),tool('3-point circle','circle_3p')])
        palette.section('Arc',[tool('3-point arc','arc'),tool('Center arc','center_arc')])
        palette.section('More sketch drawing tools',[tool('Polygon','polygon',self.start_polygon_tool),tool('Ellipse','ellipse'),tool('Center-to-center slot','slot'),tool('Control-point spline','spline'),tool('Conic curve','conic'),tool('Point','point'),tool('Text…','text',self.start_text_tool)])
        palette.section('Modify',[tool('Trim','trim'),tool('Extend','extend'),tool('Offset','offset',lambda:self.start_pattern('offset')),tool('Move / Rotate / Scale','transform',lambda:self.start_pattern('transform'))])
        palette.section('PATTERN',[tool('Mirror','mirror',lambda:self.start_pattern('mirror')),tool('Circular pattern','circular',lambda:self.start_pattern('circular')),tool('Rectangular pattern','rectangular',lambda:self.start_pattern('rectangular'))])
        return palette

    def start_polygon_tool(self,sides=None):
        if sides is not None:self.workspace.polygon_sides=int(sides)
        self.set_tool('polygon')

    def polygon_settings(self):
        form=self.form('Polygon settings')
        self.spin(form,'polygon_sides','Number of sides',self.workspace.polygon_sides,lambda v:setattr(self.workspace,'polygon_sides',int(v)))
        self.widgets['polygon_sides'].setDecimals(0);self.widgets['polygon_sides'].setRange(3,128)
        choice=QComboBox()
        for label,value in [('Vertex radius (inscribed)','inscribed'),('Edge radius (circumscribed)','circumscribed'),('Edge length','edge')]:choice.addItem(tr(label),value)
        choice.setCurrentIndex(choice.findData(self.workspace.polygon_mode));choice.currentIndexChanged.connect(lambda i:self.set_polygon_mode(choice.itemData(i)))
        self.widgets['polygon_mode']=choice;form.addRow(QLabel(tr('Sizing mode')));form.addRow(choice)
        exact=QCheckBox(tr('Use exact size'));exact.setChecked(self.workspace.polygon_fixed_size);exact.toggled.connect(lambda value:setattr(self.workspace,'polygon_fixed_size',value));form.addRow(exact)
        label={'inscribed':'Vertex radius','circumscribed':'Edge radius','edge':'Edge length'}[self.workspace.polygon_mode]
        def size(value):
            self.workspace.polygon_size=value;self.workspace.polygon_fixed_size=True;exact.setChecked(True);self.workspace.update()
        self.spin(form,'polygon_size','Size (mm)',self.workspace.polygon_size,size,True).setToolTip(tr(label+' (mm)'))
        self.note('Set the sides and sizing mode, then click the center (or first corner in Edge length mode). Click again to set orientation. Type a size while drawing, or enable Use exact size.')

    def set_polygon_mode(self,value):
        self.workspace.polygon_mode=value;self.workspace.points=[];self.workspace.reset_dimensions();self.workspace.update();self.show_editor()

    def start_text_tool(self):
        """Drag a text box in the sketch; its text and format are set in the right-hand panel."""
        self.set_tool('text')
        self.show_status(tr('Drag a rectangle to place the text box.'))
    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange,QEvent.FontChange) and getattr(self,'_ribbon_fitted',False):
            QTimer.singleShot(0,self.fit_ribbon_buttons)

    def sync_ribbon(self):
        self.fit_ribbon_buttons()
        self.measure_button.setChecked(self.workspace.measure_active)
        sketch=self.workspace.mode=='sketch'
        if not sketch:self.draw_palette.hide()
        self.ribbon.setCurrentWidget(self.sketch_bar if sketch else self.body_bar)
        self.sketch_bar.setVisible(sketch);self.body_bar.setVisible(not sketch)
        # The stack takes the width of the visible page only, so Inspect follows the tools directly.
        for page in (self.sketch_bar,self.body_bar):
            page.setSizePolicy(QSizePolicy.Preferred if page.isVisible() else QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.ribbon.setMinimumWidth(self.ribbon.currentWidget().sizeHint().width());self.ribbon.updateGeometry()
        self.body_mode_badge.setVisible(not sketch);self.sketch_mode_badge.setVisible(sketch);self.sketch_action_group.setVisible(sketch)
        for palette in self.tool_palettes.values():
            if palette.isVisible() and not palette.anchor.isVisible():palette.dismiss()
        if sketch:
            for key,b in self.tool_buttons.items():b.setChecked(self.workspace.construction_mode if key=='construction' else key==self.workspace.tool)
        else:
            label={'model':'SOLID','support':'SELECT PLANE','extrude':'EXTRUDE','edge':'SELECT EDGES'}[self.workspace.mode]
            if self.workspace.extrude_selecting:label='EXTRUDE SELECT'
            if self.workspace.measure_active:label='MEASURE'
            self.body_mode_label.setText(tr(label))
        if hasattr(self,'timeline_buttons'):
            for index,b in enumerate(self.timeline_buttons):b.setChecked(index==self.selected)
    def toggle_measure(self,checked=False):
        if self.workspace.measure_active:
            self.workspace.set_measure_active(False);self.show_editor();return
        if self.precise_changed() and not self.apply_entity():self.measure_button.setChecked(False);return
        self.draw_palette.dismiss()
        scenes=list(self.workspace.sketches)
        if self.workspace.mode=='sketch' and self.workspace.active:scenes=[(self.workspace.active,self.workspace.active_frame)]+[(s,f) for s,f in scenes if s['id']!=self.workspace.active['id']]
        snapshots=[copy.deepcopy(sketch) for sketch,frame in scenes];shape=self.workspace.mesh_shape
        self.workspace.preparing_sketches=True
        try:
            def prepare(report):return self.prepare_sketch_data(snapshots,report,True),[list(vertex.Center().toTuple()) for vertex in shape.Vertices()] if shape is not None else []
            data,vertices=self.run_busy('Preparing measurement geometry…',prepare)
        except Exception as err:self.measure_button.setChecked(False);self.error(err);return
        finally:self.workspace.preparing_sketches=False
        self.install_sketch_data(data);self.workspace.measure_vertices=vertices;self.workspace.set_measure_active(True);self.workspace.setFocus();self.show_editor()

    def measure_picked(self,selection):
        previous=list(self.workspace.measure_selection)
        candidate=([selection] if len(previous)==2 else previous+[selection])
        try:result=self.run_busy('Measuring geometry…',lambda report:calculate_measurement(candidate))
        except Exception as err:self.error(err);return
        self.workspace.measure_selection=candidate;self.workspace.measure_result=result;self.workspace.update();self.show_editor()

    def clear_measurement(self):
        self.workspace.measure_selection=[];self.workspace.measure_result=None;self.workspace.update();self.show_editor()

    def measure_editor(self):
        self.note('<b>'+tr('Measure')+'</b>')
        self.note(tr('Click any point, corner, edge or face. Select a second object for the shortest distance between them. A third click starts a new measurement.'))
        result=self.workspace.measure_result or {}
        for index,info in enumerate(result.get('properties',[])):
            self.note(f"{index+1}. {tr(info['label'])}")
            if 'length' in info:self.note(f"{tr('Length')}: {info['length']:.4f} mm")
            if 'radius' in info:self.note(f"{tr('Radius')}: {info['radius']:.4f} mm · {tr('Diameter')}: {info['radius']*2:.4f} mm")
            if 'area' in info:self.note(f"{tr('Area')}: {info['area']:.4f} mm²")
            if 'point' in info:self.note('X / Y / Z: '+', '.join(f'{value:.4f}' for value in info['point'])+' mm')
        if 'distance' in result:
            self.note(f"<b>{tr('Shortest distance')}: {result['distance']:.4f} mm</b>")
            self.note('ΔX / ΔY / ΔZ: '+', '.join(f'{abs(value):.4f}' for value in result['delta'])+' mm')
            if 'angle' in result:self.note(f"{tr('Angle')}: {result['angle']:.4f}°")
        self.button('Clear measurement',self.clear_measurement)
        self.button('Done measuring',self.toggle_measure,True)

    def fit_ribbon_buttons(self):
        """Give every ribbon button the width its (translated) text needs and re-flow the groups.

        The widths were measured once, when the buttons were created; a longer translation, or a
        font that was not final yet, left them too narrow and neighbouring buttons overlapped.
        """
        container=getattr(self,'ribbon_scroll',None)
        if container is None:return
        content=container.widget()
        anchors={palette.anchor for palette in getattr(self,'tool_palettes',{}).values()}
        for button in content.findChildren(QToolButton):
            if button.toolButtonStyle()!=Qt.ToolButtonTextUnderIcon:continue
            # The small arrow of a drop-down button is drawn over the label's right end, so those need room for it.
            button.ensurePolished();button.setMinimumWidth(max(64,button.sizeHint().width()+(14 if button in anchors else 4)))
        for group in content.findChildren(QWidget,'toolGroup'):
            if group.layout() is not None:group.layout().invalidate()
            group.updateGeometry()
        for bar in (getattr(self,'body_bar',None),getattr(self,'sketch_bar',None)):
            if bar is not None and bar.layout() is not None:bar.layout().invalidate();bar.layout().activate();bar.updateGeometry()
        # Pin the mode ribbon to what its pages need now: the enclosing layout would otherwise
        # keep squeezing it to an older, narrower minimum and the groups would overlap.
        # Only the page being shown counts: the wider sketch page must not leave a gap in solid mode.
        if not getattr(self,'_ribbon_signal',False):
            self._ribbon_signal=True;self.ribbon.currentChanged.connect(lambda *_:self.fit_ribbon_buttons())
        current=self.ribbon.currentWidget()
        for page in (self.body_bar,self.sketch_bar):
            page.setSizePolicy(QSizePolicy.Preferred if page is current else QSizePolicy.Ignored,QSizePolicy.Fixed)
        needed=current.layout().minimumSize().width() if current is not None and current.layout() is not None else 0
        self.ribbon.setMinimumWidth(needed);self.ribbon.setMaximumWidth(max(needed,current.sizeHint().width()) if current is not None else 16777215)
        if self.ribbon.layout() is not None:self.ribbon.layout().invalidate()
        self.ribbon.updateGeometry()
        if content.layout() is not None:content.layout().invalidate();content.layout().activate()
        # The scroll area keeps the old size of its content until told otherwise.
        need=max(content.minimumSizeHint().width(),content.sizeHint().width())
        content.resize(max(container.viewport().width(),need),content.height())
        QApplication.sendEvent(content,QEvent(QEvent.LayoutRequest))

    def toggle_browser(self):
        collapsed=not bool(self.float_left.property('collapsed'));self.float_left.setProperty('collapsed',collapsed)
        for part in self.browser_parts:part.setVisible(not collapsed)
        self.collapse_browser.setText('+' if collapsed else '–');self.schedule_float_layout()

    def schedule_float_layout(self,*_):
        if hasattr(self,'float_timer') and not self.float_timer.isActive():self.float_timer.start()

    def position_float_panels(self):
        """Place the two floating panels over the workspace, each only as tall as its content."""
        if not hasattr(self,'float_left'):return
        ws=self.workspace;width,height=ws.width(),ws.height()
        if width<200 or height<160:return
        left,right=self.float_left,self.float_right
        def rows(item):
            count=1
            if item.isExpanded():count+=sum(rows(item.child(i)) for i in range(item.childCount()))
            return count
        if left.property('collapsed'):
            left_height=left.layout().sizeHint().height()+2
        else:
            row=max(22,self.objects.sizeHintForRow(0)) if self.objects.topLevelItemCount() else 24
            total=sum(rows(self.objects.topLevelItem(i)) for i in range(self.objects.topLevelItemCount()))
            wanted=34+total*(row+3)+10
            left_height=int(min(max(90,wanted),height*.6))
        left.setGeometry(8,66,250,left_height)
        reserve=self.viewport_tools.height()+34 if hasattr(self,'viewport_tools') else 60
        panel_width=int(min(max(300,self.editor.minimumSizeHint().width()+26),460,width*.45))
        wanted=self.editor.sizeHint().height()+8
        right_height=int(min(max(90,wanted),max(120,height-12-reserve)))
        idle=bool(getattr(self,'editor_idle',False))
        right.setVisible(not idle)
        right.setGeometry(width-panel_width-12,12,panel_width,right_height)
        ws.axes_shift=0 if idle else panel_width+14
        left.raise_();right.raise_()
        if hasattr(self,'viewport_tools'):self.viewport_tools.raise_()
        ws.update()

    def position_viewport_tools(self):
        self.viewport_tools.adjustSize();self.viewport_tools.move(max(8,self.workspace.width()-self.viewport_tools.width()-12),max(8,self.workspace.height()-self.viewport_tools.height()-12));self.viewport_tools.raise_()
        if hasattr(self,'graphics_warning'):
            self.graphics_warning.move(max(8,self.workspace.width()-46),max(8,self.workspace.height()-self.viewport_tools.height()-52));self.graphics_warning.raise_()
    def update_graphics_warning(self):
        self.graphics_warning.setVisible(bool(self.workspace.gpu_error));self.position_viewport_tools()
    def show_graphics_issues(self):
        dialog=QMessageBox(self);dialog.setWindowTitle(tr('Graphics issues'));dialog.setIcon(QMessageBox.Warning)
        dialog.setText(tr('The GPU solid renderer encountered an issue. Software drawing is keeping your model visible.') if self.workspace.gpu_error else tr('No graphics issues detected.'))
        dialog.setInformativeText(self.workspace.gpu_error or '')
        dialog.setDetailedText(tr(self.workspace.graphics_diagnostics()));dialog.exec()
    def viewport_setting(self,key,value):
        self.doc.display[key]=value;setattr(self.workspace,'show_'+key,value);self.workspace.update();self.update_title()
    def toggle_grid_over(self):
        on=self.grid_over_action.isChecked()
        self.workspace.grid_over_bodies=on
        try:
            settings=platform_support.settings();settings.setValue('view/grid_over_bodies','true' if on else 'false');settings.sync()
        except Exception:pass
        self.workspace.update()
    def sync_view_settings(self):
        self.workspace.grid_over_bodies=self.grid_over_action.isChecked()
        for key in ('grid','axes','aa'):
            value=self.doc.display.get(key,True);setattr(self.workspace,'show_'+key,value);button=getattr(self,key+'_button');button.blockSignals(True);button.setChecked(value);button.blockSignals(False)
        perspective=bool(self.doc.display.get('perspective',False));self.workspace.perspective=perspective
        self.perspective_button.blockSignals(True);self.perspective_button.setChecked(perspective);self.perspective_button.blockSignals(False)
        self.populate_view_selector()
        self.workspace.update();self.position_viewport_tools()
    def body_materials(self):
        stored=self.doc.display.get('materials',{});default=copy.deepcopy(self.doc.display.get('default_material',{'color':'#4baed6','finish':'matte'}))
        indices=getattr(self,'visible_body_indices',None)
        if indices is None:indices=list(range(len(self.doc.solid.val().Solids()))) if self.doc.solid else []
        materials={str(out):copy.deepcopy(stored.get(str(source),default)) for out,source in enumerate(indices)}
        materials['default']=default;return materials

    def appearance_dialog(self,body_id=None):
        key='default' if body_id is None else str(body_id)
        defaults=self.doc.display.get('default_material',{'color':'#4baed6','finish':'matte'})
        current=copy.deepcopy(defaults if body_id is None else self.doc.display.get('materials',{}).get(key,defaults))
        title=tr('Default body appearance') if body_id is None else tr(f'Body {int(body_id)+1} appearance')
        dialog=QDialog(self);dialog.setWindowTitle(title)
        layout=QFormLayout(dialog);finish=QComboBox()
        for value in ['matte','metallic','wood']:finish.addItem(tr(value),value)
        finish.setCurrentIndex(max(0,finish.findData(current.get('finish','matte'))));layout.addRow(tr('Finish'),finish)
        color_button=QPushButton(current.get('color','#4baed6'));chosen=QColor(current.get('color','#4baed6'))
        def choose_color():
            nonlocal chosen
            value=QColorDialog.getColor(chosen,dialog,tr('Choose body color'))
            if value.isValid():chosen=value;color_button.setText(value.name())
        color_button.clicked.connect(choose_color);layout.addRow(tr('Color'),color_button)
        opacity=QSpinBox();opacity.setRange(10,100);opacity.setSuffix(' %');opacity.setValue(int(round(float(current.get('opacity',1.))*100)))
        opacity.setToolTip(tr('Below 100 % the body is drawn see-through.'));layout.addRow(tr('Opacity'),opacity)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addRow(buttons)
        if buttons.button(QDialogButtonBox.Ok):buttons.button(QDialogButtonBox.Ok).setText(tr('OK'))
        if buttons.button(QDialogButtonBox.Cancel):buttons.button(QDialogButtonBox.Cancel).setText(tr('Cancel'))
        if dialog.exec()!=QDialog.Accepted:return
        value={'color':chosen.name(),'finish':finish.currentData()}
        if opacity.value()<100:value['opacity']=opacity.value()/100.
        if body_id is None:self.doc.display['default_material']=value
        else:self.doc.display.setdefault('materials',{})[key]=value
        self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),materials=self.body_materials());self.rebuild_objects();self.update_title()

    def visible_solid(self):
        from surface_tools import scene
        base=self.visible_solid_bodies()
        key=(id(base),self.doc.revision,tuple(sorted(self.doc.display.get("surfaces",{}).items())))
        if getattr(self,"surface_scene_key",None)!=key:
            self.surface_scene_key=key;self.surface_scene=scene(base,self.doc.frames,self.doc.display.get("surfaces",{}))
        return self.surface_scene

    def visible_solid_bodies(self):
        if self.doc.solid is None:return None
        visibility=self.doc.display.get('bodies',{});state=tuple(sorted(visibility.items()))
        if getattr(self,'visible_source',None) is self.doc.solid and getattr(self,'visible_state',None)==state:return self.visible_result
        indexed=[(i,s) for i,s in enumerate(self.doc.solid.val().Solids()) if visibility.get(str(i),True)]
        self.visible_body_indices=[i for i,_ in indexed];solids=[s for _,s in indexed]
        self.visible_source=self.doc.solid;self.visible_state=state
        self.visible_result=cq.Workplane('XY').newObject([solids[0] if len(solids)==1 else cq.Compound.makeCompound(solids)]) if solids else None
        return self.visible_result
    def feature_detail(self,f):
        if f['kind']=='sketch':return f'{tr("Sketch")} · {len(f["entities"])} {tr("entities")}'+(' · '+tr('on face') if f.get('support') else ' · '+tr('origin plane'))
        if f['kind']=='extrude':
            modern='source' in f or 'sources' in f
            sources=extrusion_sources(f) if modern else []
            source_text=tr('face' if sources[0].get('type')=='face' else 'profile') if len(sources)==1 else (f'{len(sources)} {tr("sources")}' if sources else tr('profile'))
            operation='cut' if f.get('signed_depth') and f['depth']<0 else f.get('operation','add')
            return f'{tr(operation).capitalize()} · {f["depth"]:g} mm · {source_text}'
        if f['kind']=='sketch_move':return tr('Move sketch')+' · '+', '.join(f'{axis}: {f.get(key,0):+g} mm' for axis,key in zip('XYZ',('dx','dy','dz')))
        if f['kind']=='import_solid':return tr('Imported STEP')+' · '+f.get('source_name','STEP')
        if f['kind'] in BODY_TOOLS:return tr(BODY_LABELS[f['kind']])+' · '+str(len(f.get('targets',[])))+' '+tr('target bodies')
        if f['kind'] in SPATIAL_TOOLS:return tr(f['kind'].replace('_',' ').title())+' · '+str(len(f['entities']))+' '+tr('entities')
        if f['kind'] in ASSEMBLY_TOOLS:return tr(f['kind'].title())+' · '+(str(len(f.get('features',[])))+' '+tr('features') if f['kind']=='component' else tr(f.get('joint_type','rigid')))
        if f['kind'] in ADVANCED_TOOLS:return tr(f['kind'].replace('_',' ').title())+' · '+tr(str(f.get('object_type',f.get('operation',''))))
        if f['kind'] in CONSTRUCTIONS+SOLID_TOOLS:return tr(f['kind'].replace('_',' ').title())+' · '+tr(str(f.get('mode',f.get('operation',''))))
        return f'{tr(f["kind"].title())} · {f["radius"]:g} mm · {tr(f.get("edges","all"))} {tr("Edges").lower()}'
    def feature_tooltip(self,index,f):
        rows=[self.feature_detail(f), tr('Active') if f.get('enabled',True) else tr('Suppressed')]
        if f['kind']=='sketch':
            rows.append(f'{len(regions(f))} {tr("closed profiles")}')
            counts={}
            for e in f['entities']:counts[e['kind']]=counts.get(e['kind'],0)+1
            rows.append(', '.join(f'{count} {tr(kind.title())}' for kind,count in counts.items()))
            rows.append(tr('Double-click to edit sketch'))
        elif f['kind']=='extrude':
            rows.append(tr('Direction')+': '+tr(f.get('direction','one side')))
            if f.get('offset'):rows.append(f"{tr('Start offset')}: {f['offset']:g} mm")
            sources=extrusion_sources(f) if 'source' in f or 'sources' in f else []
            sketch_names=[]
            for source in sources:
                if source.get('type')=='sketch':
                    name=next((sk['name'] for sk in self.doc.features if sk.get('id')==source.get('sketch')),tr('Sketch'))
                    if name not in sketch_names:sketch_names.append(name)
            if len(sources)==1:
                rows.append(tr('Source:')+' '+(sketch_names[0] if sketch_names else tr('Planar face')))
            elif sources:rows.append(f'{tr("Sources:")} {len(sources)} {tr("selected")}')
            if len(sketch_names)>1:rows.append(tr('Sketch sources:')+' '+', '.join(sketch_names))
            rows.append(tr('Click to edit extrusion'))
        else:rows.append(tr('Click to edit parameters'))
        return '<b>'+html.escape(f"{index+1}. {f['name']}")+'</b><br>'+ '<br>'.join(html.escape(row) for row in rows if row)
    def rebuild_timeline(self):
        signature=(id(self.doc),getattr(self.doc,'revision',0))
        if self.timeline_signature==signature and hasattr(self,'timeline_buttons'):
            for index,button in enumerate(self.timeline_buttons):button.setChecked(index==self.selected)
            return
        self.timeline_signature=signature
        while self.timeline_layout.count():
            item=self.timeline_layout.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
        self.timeline_buttons=[];label=QLabel(tr('FEATURES  →'));label.setObjectName('groupTitle');self.timeline_layout.addWidget(label)
        for i,f in enumerate(self.doc.features):
            b=TimelineButton();b.setProperty('_icon_name',f['kind']);b.setIcon(icon(f['kind']));b.setText(str(i+1));b.setIconSize(QSize(20,20));b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);b.setCheckable(True);b.setChecked(i==self.selected);b.setFixedHeight(34)
            b.setToolTip(self.feature_tooltip(i,f)+'<br><br>'+tr('Click: show model at this history point')+'<br>'+tr('Double-click: edit this feature')+'<br>'+tr('Right-click: history actions'))
            b.setToolTipDuration(12000);b.double_clicked.connect(lambda index=i:self.timeline_edit(index));b.clicked.connect(lambda checked=False,index=i:self.timeline_select(index))
            b.setContextMenuPolicy(Qt.CustomContextMenu);b.customContextMenuRequested.connect(lambda pos,index=i,button=b:self.timeline_context_menu(index,button,pos))
            failed=getattr(getattr(self.doc,'build_error',None),'feature_index',None)
            if failed is not None and i>=failed:
                # Fusion-style: the failing feature is red, later ones are not built yet.
                b.setStyleSheet('color:#d0453f;font-weight:bold;' if i==failed else 'color:#8a8f96;')
                b.setToolTip(html.escape(tr(str(self.doc.build_error)) if i==failed else tr('Not built: an earlier feature fails.'))+'<br><br>'+b.toolTip())
            self.timeline_layout.addWidget(b);self.timeline_buttons.append(b)
        self.timeline_layout.addStretch()
    def historical_scene_sketches(self,features,sketches,frames):
        consumed={source['sketch'] for f in features if f.get('enabled',True) and f.get('kind')=='extrude' for source in (extrusion_sources(f) if 'source' in f or 'sources' in f else []) if source.get('type')=='sketch'}
        visibility=self.doc.display.get('sketches',{})
        return [(sketch,frames[id_]) for id_,sketch in sketches.items() if id_ in frames and visibility.get(id_,id_ not in consumed)]
    def historical_materials(self,solid):
        default=copy.deepcopy(self.doc.display.get('default_material',{'color':'#4baed6','finish':'matte'}));stored=self.doc.display.get('materials',{})
        count=len(solid.val().Solids()) if solid is not None else 0
        materials={str(i):copy.deepcopy(stored.get(str(i),default)) for i in range(count)};materials['default']=default
        return materials
    def timeline_select(self,index):
        if self.loading or not (0<=index<len(self.doc.features)):return
        if not self.abandon():self.sync_ribbon();return
        prefix=copy.deepcopy(self.doc.features[:index+1])
        try:
            solid,sketches,frames=self.run_busy(f'Showing history after feature {index+1}…',lambda report:self.doc.preview(prefix,progress=report))
            feature=self.doc.features[index]
            self.history_preview_index=index;self.selected=index;self.precise_draft=None
            # A normal timeline click is both a history view and feature selection.
            # Non-sketch features keep their parameter editor available, matching
            # the established timeline workflow while the viewport shows the prefix.
            if feature['kind']!='sketch':
                self.draft=copy.deepcopy(feature);self.draft_index=index
                self.edge_size_limit=None;self.edge_size_limit_bounded=True
            else:
                self.draft=None;self.draft_index=None
            self.workspace.set_mode('model')
            self.workspace.construction_items=[(f['id'],f['name'],frames[f['id']]) for f in prefix if f['kind'] in CONSTRUCTIONS and f['id'] in frames and self.doc.display.get('construction',{}).get(f['id'],True)]
            self.set_scene_responsive(solid,self.historical_scene_sketches(prefix,sketches,frames),materials=self.historical_materials(solid))
            self.rebuild_timeline();self.show_editor()
            self.show_status(f'History preview · model after feature {index+1} of {len(self.doc.features)} · right-click the timeline feature to revert here')
        except Exception as e:self.error(e)
    def timeline_context_menu(self,index,button,pos):
        menu=QMenu(button)
        show_action=menu.addAction(tr('Show model at this point'))
        edit_action=menu.addAction(tr('Edit this feature'))
        inspect_action=menu.addAction(tr('Inspect dependencies'))
        earlier_action=menu.addAction(tr('Move earlier'));earlier_action.setEnabled(index>0)
        later_action=menu.addAction(tr('Move later'));later_action.setEnabled(index<len(self.doc.features)-1)
        suppress_action=menu.addAction(tr('Suppress' if self.doc.features[index].get('enabled',True) else 'Unsuppress'))
        cascade_action=menu.addAction(tr('Suppress with dependents'))
        menu.addSeparator();delete_action=menu.addAction(tr('Delete feature'))
        revert_action=menu.addAction(tr('Revert project to this point…'))
        chosen=menu.exec(button.mapToGlobal(pos))
        if chosen is show_action:self.timeline_select(index)
        elif chosen is edit_action:self.timeline_edit(index)
        elif chosen is inspect_action:self.inspect_dependencies(index)
        elif chosen is earlier_action:self.reorder_feature(index,index-1)
        elif chosen is later_action:self.reorder_feature(index,index+1)
        elif chosen is suppress_action:self.suppress_feature(index,not self.doc.features[index].get('enabled',True))
        elif chosen is cascade_action:self.suppress_feature(index,False,True)
        elif chosen is delete_action:self.delete_feature(index)
        elif chosen is revert_action:self.revert_to_timeline(index)
    def inspect_dependencies(self,index):
        from feature_history import descendants
        f=self.doc.features[index];key=f.get('id') or '@'+str(index);dependencies=self.doc.dependencies()
        names={item.get('id') or '@'+str(i):item.get('name','Unnamed') for i,item in enumerate(self.doc.features)}
        dialog=QDialog(self);dialog.setWindowTitle(tr('Feature dependencies'));layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel(f['name']))
        for title,items in [('Required inputs',dependencies[key]),('Downstream dependents',descendants(self.doc.features,key))]:
            layout.addWidget(QLabel(tr(title)));listing=QListWidget();listing.addItems([names.get(id_,id_) for id_ in sorted(items)] or [tr('None')]);layout.addWidget(listing)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(dialog.reject);layout.addWidget(close);dialog.resize(450,380);dialog.exec()

    def reorder_feature(self,index,destination):
        if not self.abandon():return
        try:
            self.run_busy('Reordering feature history…',lambda progress:self.doc.reorder(index,destination,progress));self.selected=destination;self.refresh()
        except Exception as error:self.error(error)

    def suppress_feature(self,index,enabled,cascade=False):
        if not self.abandon():return
        try:
            self.run_busy('Updating feature suppression…',lambda progress:self.doc.suppress(index,enabled,cascade,progress));self.selected=index;self.refresh()
        except Exception as error:self.error(error)

    def escape_pressed(self):
        """Esc: step out of the current tool. Returns True when Esc was used.

        Open dropdowns, a running drag and dialogs handle Esc themselves first.
        In a sketch, Esc stops the drawing tool (back to Select) but keeps the
        sketch open; anywhere else it cancels the tool or feature being edited.
        """
        w=self.workspace
        if self.loading or w.gizmo.dragging or w.sketch_drag_active:return False
        if w.measure_active:
            w.set_measure_active(False);self.show_editor();self.show_status('Measure closed.');return True
        if w.mode=='sketch' and self.draft and self.draft.get('kind')=='sketch':
            if self.text_draft is not None:
                self.cancel_text();self.show_status('Text canceled.');return True
            if w.points or w.tool!='select':
                w.cancel_tool();self.set_tool('select');self.show_status('Tool canceled · Select');return True
            if w.selected_entity is not None or self.precise_draft is not None or w.pattern_selection:
                self.precise_draft=None;self.entity_index=None;w.selected_entity=None;w.pattern_selection.clear();w.update();self.show_editor();return True
            return True
        if self.draft is not None or self.history_preview_index is not None or w.mode in ('support','extrude','edge') or w.extrude_selecting:
            if w.mode=='support' and self.draft is None and not self.doc.features:
                # Nothing to go back to on an empty project: keep the plane picker open.
                return True
            self.cancel();self.show_status('Canceled.');return True
        return False
    def return_to_latest(self):
        self.history_preview_index=None;self.selected=None;self.draft=None;self.draft_index=None;self.precise_draft=None;self.workspace.set_mode('model');self.refresh()
    def revert_to_timeline(self,index):
        if self.loading or not (0<=index<len(self.doc.features)):return
        later=len(self.doc.features)-index-1
        if later<=0:
            self.timeline_select(index);return
        feature=self.doc.features[index]
        message=f'Revert the project to feature {index+1}: {feature.get("name","Unnamed")}?\n\nThis removes {later} later feature'+('' if later==1 else 's')+' from the current history. You can Undo to restore them.'
        answer=QMessageBox.question(self,tr('Revert feature history'),tr(message),QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
        if answer!=QMessageBox.Yes:return
        try:
            candidate=copy.deepcopy(self.doc.features[:index+1]);self.run_busy('Reverting feature history…',lambda report:self.doc.commit(candidate,progress=report))
            self.history_preview_index=None;self.selected=None;self.draft=None;self.draft_index=None;self.precise_draft=None;self.workspace.set_mode('model');self.refresh(True)
            self.show_status(f'Reverted to feature {index+1}. Undo restores the removed feature history.')
        except Exception as e:self.error(e)
    def timeline_edit(self,index):
        if not (0<=index<len(self.doc.features)):return
        self.history_preview_index=None
        self.refresh()
        self.select(index)
        if self.doc.features[index]['kind']=='sketch' and self.selected==index and self.draft is None:self.edit_selected_sketch()
    def rebuild_objects(self):
        bodies_state=tuple(sorted(self.doc.display.get('bodies',{}).items()));sketch_state=tuple(sorted(self.doc.display.get('sketches',{}).items()))
        draft_id=self.draft.get('id') if isinstance(self.draft,dict) and self.draft.get('kind')=='sketch' else None
        signature=(id(self.doc),getattr(self.doc,'revision',0),bodies_state,sketch_state,tuple(sorted(self.doc.display.get("surfaces",{}).items())),self.workspace.mode,draft_id,tuple(sorted(self.doc.display.get('construction',{}).items())))
        if self.object_tree_signature==signature:return
        self.object_tree_signature=signature
        self.objects.blockSignals(True);self.objects.clear()
        bodies=QTreeWidgetItem(self.objects,[tr('Bodies')]);bodies.setIcon(0,icon('body'))
        if self.doc.solid:
            for i,body in enumerate(self.doc.solid.val().Solids()):
                item=QTreeWidgetItem(bodies,[f'{tr("Body")} {i+1}']);item.setIcon(0,icon('body'));item.setData(0,Qt.UserRole,{'type':'bodies','id':str(i)})
                item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(0,Qt.Checked if self.doc.display.get('bodies',{}).get(str(i),True) else Qt.Unchecked)
                item.setToolTip(0,tr('Toggle visibility; double-click to change this body’s color/finish.'))
        from surface_tools import bodies as surface_bodies
        if surface_bodies(self.doc.frames):
            group=QTreeWidgetItem(self.objects,[tr('Surfaces')]);group.setIcon(0,icon('surface_patch'));group.setExpanded(True)
            for id_,body in surface_bodies(self.doc.frames).items():
                item=QTreeWidgetItem(group,[body['name']]);item.setIcon(0,icon('surface_patch'));item.setData(0,Qt.UserRole,dict(type='surfaces',id=id_));item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(0,Qt.Checked if self.doc.display.get('surfaces',{}).get(id_,True) else Qt.Unchecked)
        sketches=QTreeWidgetItem(self.objects,[tr('Sketches')]);sketches.setIcon(0,icon('sketch'))
        consumed={source['sketch'] for f in self.doc.features if f.get('enabled',True) and f.get('kind')=='extrude' for source in (extrusion_sources(f) if 'source' in f or 'sources' in f else []) if source.get('type')=='sketch'}
        for i,f in enumerate(self.doc.features):
            if f['kind'] not in ('sketch',)+SPATIAL_TOOLS:continue
            item=QTreeWidgetItem(sketches,[f['name']]);item.setIcon(0,icon('sketch'));item.setData(0,Qt.UserRole,{'type':'sketches','id':f['id'],'index':i})
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);visible=self.doc.display.get('sketches',{}).get(f['id'],self.workspace.mode=='extrude' or self.workspace.extrude_selecting or f['id'] not in consumed)
            active=self.workspace.mode=='sketch' and self.draft and self.draft.get('id')==f['id']
            item.setCheckState(0,Qt.Checked if active or (visible and f.get('enabled',True)) else Qt.Unchecked)
            if active:item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            if not f.get('enabled',True):item.setDisabled(True)
            item.setToolTip(0,tr('Toggle sketch visibility. Double-click its name to edit. Consumed sketches are initially hidden.'))
        if any(f['kind']=='component' for f in self.doc.features):
            components_group=QTreeWidgetItem(self.objects,[tr('Components')]);components_group.setIcon(0,icon('component'));components_group.setExpanded(True)
            for i,f in enumerate(self.doc.features):
                if f['kind']=='component':
                    item=QTreeWidgetItem(components_group,[f['name']]);item.setIcon(0,icon('component'));item.setData(0,Qt.UserRole,dict(type='components',id=f['id'],index=i));item.setToolTip(0,tr('Double-click to edit component history.'));item.setDisabled(not f.get('enabled',True))
        construction_group=QTreeWidgetItem(self.objects,[tr('Construction')]);construction_group.setIcon(0,icon('construct'))
        for i,f in enumerate(self.doc.features):
            if f['kind'] not in CONSTRUCTIONS:continue
            item=QTreeWidgetItem(construction_group,[f['name']]);item.setIcon(0,icon(f['kind']));item.setData(0,Qt.UserRole,{'type':'construction','id':f['id'],'index':i})
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(0,Qt.Checked if self.doc.display.get('construction',{}).get(f['id'],True) else Qt.Unchecked)
            item.setToolTip(0,tr('Double-click a plane to start a sketch. Edit construction parameters from the timeline.'))
        bodies.setExpanded(True);sketches.setExpanded(True);construction_group.setExpanded(True);self.objects.blockSignals(False)
    def visibility_changed(self,item,column):
        self.invalidate_preview()
        data=item.data(0,Qt.UserRole)
        if not data:return
        self.doc.display.setdefault(data['type'],{})[data['id']]=item.checkState(0)==Qt.Checked
        self.object_tree_signature=None
        self.workspace.construction_items=[(f['id'],f['name'],self.doc.frames[f['id']]) for f in self.doc.features if f['kind'] in CONSTRUCTIONS and f['id'] in self.doc.frames and self.doc.display.get('construction',{}).get(f['id'],True)]
        self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),materials=self.body_materials());self.update_title()
    def object_clicked(self,item,column):
        data=item.data(0,Qt.UserRole)
        if data:self.show_status(item.text(0)+' · '+(tr('visible') if item.checkState(0)==Qt.Checked else tr('hidden')))
    def object_edit(self,item,column):
        data=item.data(0,Qt.UserRole)
        if data and data['type']=='sketches':
            if self.doc.features[data['index']]['kind'] in SPATIAL_TOOLS:self.timeline_edit(data['index'])
            elif self.select(data['index']):self.edit_selected_sketch()
        elif data and data['type']=='components':self.open_component(data['index'])
        elif data and data['type']=='bodies':self.appearance_dialog(data['id'])
        elif data and data['type']=='construction' and not self.doc.frames.get(data['id'],{}).get('axis'):self.sketch_on_construction(data['id'])

    def make_actions(self):
        """Create the application menus once.

        Language changes update these objects in place.  Rebuilding a QMenuBar with
        clear() deletes its QMenu children, which can leave live Python references
        pointing at already-destroyed C++ objects (and also breaks menu consumers).
        """
        self.menu_bar=self.menuBar();self.menuBar().setNativeMenuBar(False);self.actions={}
        def action(menu,name,fn,key=None,icon_name=None):
            icon_name=icon_name or {'New':'new','Open':'open','Save':'save','Save as':'save','Import…':'import_step','Export…':'export_step','Recover autosave…':'repair','Appearance…':'settings','Default body appearance…':'settings','Graphics diagnostics':'warning','Sketch shortcuts…':'help','Controls / scope':'help'}.get(name)
            a=QAction(icon(icon_name),tr(name),self) if icon_name else QAction(tr(name),self)
            if icon_name:a.setProperty('_icon_name',icon_name)
            a.setProperty('_i18n_text',name)
            if key:a.setShortcut(key)
            a.triggered.connect(lambda checked=False,func=fn:func())
            menu.addAction(a);self.actions[name]=a;return a
        # Build QMenus explicitly with the menu bar as their QObject parent.  Using
        # QMenuBar.addMenu(str) relies on binding-side ownership rules that can leave
        # a Python QMenu wrapper pointing at a deleted C++ object in some PySide6 builds.
        self.file_menu=QMenu(tr('File'),self.menu_bar);self.file_menu.setProperty('_i18n_title','File');self.file_menu_action=self.menu_bar.addMenu(self.file_menu)
        action(self.file_menu,'New',self.blank,QKeySequence.New)
        action(self.file_menu,'Open',self.open,QKeySequence.Open)
        action(self.file_menu,'Save',self.save,QKeySequence.Save)
        action(self.file_menu,'Save as',lambda:self.save(True),'Ctrl+Shift+S')
        self.file_menu.addSeparator();action(self.file_menu,'Import…',self.import_file,'Ctrl+I')
        action(self.file_menu,'Export…',self.export_file,'Ctrl+E')
        self.file_menu.addSeparator();action(self.file_menu,'Recover autosave…',self.recover_autosave)
        self.file_menu.addSeparator();action(self.file_menu,'Example part',self.example)
        self.edit_menu=QMenu(tr('Edit'),self.menu_bar);self.edit_menu.setProperty('_i18n_title','Edit');self.edit_menu_action=self.menu_bar.addMenu(self.edit_menu)
        self.undo_action=action(self.edit_menu,'Undo',self.undo,QKeySequence.Undo,'undo')
        self.redo_action=action(self.edit_menu,'Redo',self.redo,'Ctrl+Shift+Z','redo')
        self.edit_menu.addSeparator()
        action(self.edit_menu,'Copy feature (with what it needs)',self.copy_features,'Ctrl+C')
        action(self.edit_menu,'Paste feature into this project',self.paste_features,'Ctrl+V')
        self.edit_menu.addSeparator()
        action(self.edit_menu,'Parameters…',self.edit_parameters,'Ctrl+Alt+P')
        self.tools_menu=QMenu(tr('Tools'),self.menu_bar);self.tools_menu.setProperty('_i18n_title','Tools');self.tools_menu_action=self.menu_bar.addMenu(self.tools_menu)
        action(self.tools_menu,'Mass properties…',self.show_mass_properties)
        action(self.tools_menu,'Check interference',self.check_interference)
        action(self.tools_menu,'Bill of materials…',self.show_bill_of_materials)
        self.tools_menu.addSeparator()
        action(self.tools_menu,'Section view',lambda:self.section_button.setChecked(not self.section_button.isChecked()),'Ctrl+Alt+S')
        action(self.tools_menu,'Zoom to selection',lambda:self.workspace.fit_selection())
        self.settings_menu=QMenu(tr('Settings'),self.menu_bar);self.settings_menu.setProperty('_i18n_title','Settings');self.settings_menu_action=self.menu_bar.addMenu(self.settings_menu)
        action(self.settings_menu,'Appearance…',self.appearance_settings)
        action(self.settings_menu,'Export options…',self.export_options)
        action(self.settings_menu,'SpaceMouse…',self.spacemouse_settings)
        action(self.settings_menu,'Default body appearance…',lambda:self.appearance_dialog())
        self.frame_menu=QMenu(tr('Frame rate'),self.settings_menu);self.frame_menu.setProperty('_i18n_title','Frame rate')
        self.settings_menu.addMenu(self.frame_menu)
        self.frame_group=QActionGroup(self);self.frame_group.setExclusive(True);self.frame_actions={}
        for key in ['auto']+[str(n) for n in self.FRAME_RATES]:
            item=QAction('',self);item.setCheckable(True);item.setData(key);self.frame_group.addAction(item);self.frame_menu.addAction(item)
            item.triggered.connect(lambda checked=False,k=key:self.set_frame_rate(k));self.frame_actions[key]=item
        saved=str(self.stored_frame_rate())
        self.frame_actions.get(saved,self.frame_actions['auto']).setChecked(True)
        self.grid_over_action=action(self.settings_menu,'Show the grid through bodies',self.toggle_grid_over)
        self.grid_over_action.setCheckable(True)
        try:self.grid_over_action.setChecked(str(platform_support.settings().value('view/grid_over_bodies','true')).lower()!='false')
        except Exception:self.grid_over_action.setChecked(True)
        self.language_menu=QMenu(tr('Language'),self.settings_menu);self.language_menu.setProperty('_i18n_title','Language');self.language_menu_action=self.settings_menu.addMenu(self.language_menu)
        self.language_group=QActionGroup(self);self.language_group.setExclusive(True);self.language_actions={}
        for code,label in [('en','English'),('hu','Hungarian')]:
            a=QAction(tr(label),self);a.setProperty('_i18n_text',label);a.setCheckable(True);a.setChecked(self.language==code);a.setData(code);self.language_group.addAction(a);a.triggered.connect(lambda checked=False,c=code:self.change_language(c));self.language_menu.addAction(a);self.language_actions[code]=a
        self.help_menu=QMenu(tr('Help'),self.menu_bar);self.help_menu.setProperty('_i18n_title','Help');self.help_menu_action=self.menu_bar.addMenu(self.help_menu)
        action(self.help_menu,'Graphics diagnostics',lambda:QMessageBox.information(self,tr('Graphics diagnostics'),tr(self.workspace.graphics_diagnostics())))
        action(self.help_menu,'Sketch shortcuts…',self.show_shortcuts)
        action(self.help_menu,'About SlothCAD…',self.show_about)
        action(self.help_menu,'Controls / scope',self.show_controls_scope)

    FRAME_RATES=(30,60,90,120,144,165,240)

    def stored_frame_rate(self):
        try:value=str(platform_support.settings().value('view/frame_rate','auto'))
        except Exception:value='auto'
        return value if value=='auto' or value in {str(n) for n in self.FRAME_RATES} else 'auto'

    def display_refresh_rate(self):
        """Refresh rate of the screen the window is on (Windows and Linux; 60 when unknown)."""
        try:
            screen=self.screen() or QApplication.primaryScreen()
            hertz=float(screen.refreshRate())
            return hertz if 20.<=hertz<=1000. else 60.
        except Exception:
            return 60.

    def effective_frame_rate(self):
        choice=self.stored_frame_rate()
        if choice=='auto':return max(30.,min(240.,self.display_refresh_rate()))
        return float(choice)

    def set_frame_rate(self,key):
        try:
            settings=platform_support.settings();settings.setValue('view/frame_rate',key);settings.sync()
        except Exception:pass
        self.apply_frame_rate()

    def apply_frame_rate(self):
        """Camera and input updates are paced by this: one batch per frame at the chosen rate."""
        fps=self.effective_frame_rate()
        if hasattr(self,'workspace'):
            self.workspace.set_frame_rate(fps,self.display_refresh_rate())
        self.update_frame_rate_labels()

    def update_frame_rate_labels(self):
        hertz=self.display_refresh_rate()
        for key,item in self.frame_actions.items():
            if key=='auto':item.setText(tr('Automatic (match the display)')+f' · {hertz:.0f} Hz')
            else:
                note=' · '+tr('display limit') if float(key)>hertz+1 else ''
                item.setText(f'{key} fps'+note)

    def screen_changed(self,*_):
        self.apply_frame_rate()
        QTimer.singleShot(0,self.fit_ribbon_buttons);QTimer.singleShot(150,self.fit_ribbon_buttons)

    def showEvent(self,event):
        super().showEvent(event)
        if not getattr(self,'_ribbon_fitted',False):
            self._ribbon_fitted=True
            # Once the first layout pass is done, and again after fonts have settled.
            QTimer.singleShot(0,self.fit_ribbon_buttons);QTimer.singleShot(150,self.fit_ribbon_buttons)
        handle=self.windowHandle()
        if handle is not None and not getattr(self,'_screen_signal',False):
            self._screen_signal=True
            handle.screenChanged.connect(self.screen_changed)
            screen=handle.screen()
            if screen is not None:screen.refreshRateChanged.connect(lambda *_:self.apply_frame_rate())
        self.apply_frame_rate()

    def retranslate_menus(self):
        """Translate existing menu/action objects without invalidating QMenu wrappers."""
        for menu in (self.file_menu,self.edit_menu,self.tools_menu,self.settings_menu,self.language_menu,self.help_menu,self.frame_menu):
            title=menu.property('_i18n_title')
            if title:menu.setTitle(tr(title))
        for a in self.actions.values():
            source=a.property('_i18n_text')
            if source:a.setText(tr(source))
        for a in self.language_actions.values():
            source=a.property('_i18n_text')
            if source:a.setText(tr(source))
            a.blockSignals(True);a.setChecked(a.data()==self.language);a.blockSignals(False)
        if hasattr(self,'frame_actions'):self.update_frame_rate_labels()

    def show_about(self):
        QMessageBox.information(self,tr('About SlothCAD'),
            f'SlothCAD {VERSION}\n\n'+tr('SlothCAD is free and open-source software, released under the GNU General Public License v3.0. You may use, study, change and share it; versions you share must stay under the same license.')
            +'\n\n'+tr('It is built on Qt for Python (LGPL), CadQuery (Apache-2.0) and OpenCASCADE (LGPL).'))

    def show_shortcuts(self):
        text=tr("""Click the workspace, then use:
L — Line    R — Rectangle    C — Circle    A — Arc
V — Select    T — Trim    X — Construction drawing
Delete — Remove selected sketch geometry

While drawing: type a dimension, Tab / Shift+Tab to switch fields, Enter to place, Esc to cancel.

Guides snap like normal geometry but never create extrusion profiles. Symmetric extrusion uses total depth.""")
        QMessageBox.information(self,tr('Sketch shortcuts'),text)

    def show_controls_scope(self):
        text=tr("""Create sketch: choose a colored origin plane or a planar body face.
Sketch tools: click two points for a line, rectangle or circle.
Arc: click start, end, then a bend point. Line continues until Esc or another tool.
Grid, vertices/centers and edges snap. Numeric input can use any size.
Finish sketch, then Extrude: click inside one or more closed profiles or planar body faces.
Enter positive/negative depth and Add/Cut/Intersect, then Apply.

Model: left drag orbit, right/middle drag pan; wheel zoom; double-click fit.
Sketch: right/middle drag pan; wheel zoom; Esc cancels drawing.
Click a feature in the history to preview that point; double-click it to edit.

Curved-face sketching and assemblies are not included.
Face supports use geometric matching; ambiguous references stop rebuilding.""")
        QMessageBox.information(self,'SlothCAD '+VERSION,text)

    def change_language(self,code):
        if code not in ('en','hu'):return
        self.language=code;set_language(code);save_language(code)
        # Keep menu instances alive and only change their visible text.  This is
        # important for Qt/PySide ownership and for callers that retain menu refs.
        self.retranslate_menus()
        if hasattr(self,'undo_button'):
            self.undo_button.setToolTip(tr('Undo · Ctrl+Z'));self.redo_button.setToolTip(tr('Redo · Ctrl+Shift+Z'))
        # Translate persistent ribbon/tree widgets and then rebuild the dynamic content.
        localize_tree(self.ribbon);localize_tree(self.centralWidget());self.fit_ribbon_buttons();QTimer.singleShot(0,self.fit_ribbon_buttons);QTimer.singleShot(80,self.fit_ribbon_buttons)
        # Restore translated view names without changing the internal camera names.
        if hasattr(self,'view_selector'):self.populate_view_selector(self.view_selector.currentData())
        self.draw_menu_button.setText(tr('Draw tools')+'  ▾');self.draw_menu_button.setToolTip(tr('More sketch drawing tools'))
        localize_tree(self.draw_palette)
        from constraints import LABELS
        for action in self.constraint_menu.actions():action.setText(tr(LABELS[action.data()]))
        for action in self.body_menu.actions():action.setText(tr(BODY_LABELS[action.data()]))
        for menu in (self.solid_menu,self.solid_modify_menu,self.surface_menu,self.assembly_menu,self.body_pattern_menu):
            for action in menu.actions():
                source=action.property('_i18n_text') or (action.data().replace('_',' ').title() if isinstance(action.data(),str) else action.text())
                action.setText(tr(source))
                if action.menu():action.menu().setTitle(tr(source))
        for action in self.construction_menu.actions():action.setText(tr(action.property('_i18n_text')))
        for button in self.ribbon.findChildren(QToolButton):
            button.ensurePolished();button.setMinimumWidth(max(64,button.sizeHint().width()))
        self.object_tree_signature=None;self.timeline_signature=None
        self.rebuild_objects();self.rebuild_timeline();self.sync_ribbon();self.show_editor();self.workspace.update();self.update_title()
        self.viewport_tools.adjustSize();self.position_viewport_tools()
        self.show_status(tr('Language setting saved.'))

    def appearance_settings(self):
        dialog=QDialog(self);dialog.setWindowTitle(tr('Settings · Appearance'));layout=QVBoxLayout(dialog)
        layout.setContentsMargins(24,24,24,24);layout.setSpacing(14)
        layout.addWidget(QLabel(tr('SLOTHCAD  /  APPEARANCE')))
        choice=QComboBox();choice.addItem(tr('Light'),'light');choice.addItem(tr('Dark'),'dark');choice.setCurrentIndex(max(0,choice.findData(self.theme)));layout.addWidget(choice)
        note=QLabel(tr('Ivory or slate. Your choice is remembered for every project and the next launch.'));note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        if buttons.button(QDialogButtonBox.Save):buttons.button(QDialogButtonBox.Save).setText(tr('Save'))
        if buttons.button(QDialogButtonBox.Cancel):buttons.button(QDialogButtonBox.Cancel).setText(tr('Cancel'))
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()==QDialog.Accepted:self.change_theme(choice.currentData())

    def change_theme(self,name):
        self.theme=name;save_theme(name);apply_theme(QApplication.instance(),name);self.workspace.set_theme(name)
        for button in self.centralWidget().findChildren(QToolButton):
            key=button.property('_icon_name')
            if key:button.setIcon(icon(key))
        actions=list(self.actions.values())
        for menu in (self.solid_menu,self.solid_modify_menu,self.construction_menu,self.body_menu,self.constraint_menu):actions.extend(menu.actions())
        for action in actions:
            key=action.property('_icon_name')
            if key:action.setIcon(icon(key))
        self.object_tree_signature=None;self.timeline_signature=None
        self.rebuild_timeline();self.rebuild_objects();self.position_viewport_tools()

    def set_extrusion_depth(self,feature,value):
        if 'source' in feature or 'sources' in feature:
            feature.update(depth=value,signed_depth=False);return
        old=feature['depth'];feature.update(depth=value,signed_depth=True)
        if value<0 or old<0<=value:
            feature['operation']='cut' if value<0 else 'add'
            if 'operation' in self.widgets:
                self.widgets['operation'].blockSignals(True);self.widgets['operation'].setCurrentIndex(max(0,self.widgets['operation'].findData(feature['operation'])));self.widgets['operation'].blockSignals(False)

    def start_pattern(self,kind):
        if self.workspace.mode!='sketch':return
        selected=self.entity_index
        if self.precise_changed() and not self.apply_entity():return
        self.set_tool(kind)
        if selected is not None:self.workspace.pattern_selection={selected}
        self.show_editor()

    def pattern_selection_changed(self):self.show_editor()
    def pattern_list_selection(self,listing):
        self.workspace.pattern_selection={listing.row(item) for item in listing.selectedItems()};self.workspace.update()
    def pattern_stage_meta(self,stage=None):
        stage=stage or self.workspace.pattern_stage
        mirror=self.workspace.tool=='mirror'
        if stage=='sources':
            return {'title':'Select source geometry','summary':f'{len(self.workspace.pattern_selection)} item'+('' if len(self.workspace.pattern_selection)==1 else 's')+' selected','hint':'Click sketch entities in the viewport or select them in the list.'}
        if stage=='axis':
            selected='Line '+str(self.pattern_axis+1) if self.pattern_axis is not None else 'No guide line selected yet'
            return {'title':'Select the guide line','summary':selected,'hint':'Click a straight sketch line in the viewport, or choose one from the Guide field.'}
        center='No center point selected yet' if self.pattern_center is None else f'Center at ({self.pattern_center[0]:g}, {self.pattern_center[1]:g})'
        return {'title':'Select the center point','summary':center,'hint':'Click the workspace to place the center, or type the X / Y values below.'}

    def choose_pattern_stage(self,stage):
        self.workspace.pattern_stage=stage
        self.show_status(tr({'sources':'Selecting source geometry. Click geometry to toggle selection.','axis':'Selecting the guide line. Click a straight sketch line for the mirror guide.','center':'Selecting the center point. Click the workspace; grid and geometry snapping apply.'}[stage]))
        self.show_editor();self.workspace.update()
    def set_mirror_axis(self,index):
        self.pattern_axis=index;self.workspace.pattern_axis=index;self.workspace.pattern_stage='sources';self.show_editor();self.workspace.update()
    def set_pattern_center(self,point):
        self.pattern_center=point;self.workspace.pattern_center=point;self.workspace.pattern_stage='sources';self.show_editor();self.workspace.update()

    def pattern_editor(self):
        kind=self.workspace.tool;mirror=kind=='mirror';circular=kind=='circular';rectangular=kind=='rectangular'
        stage=self.pattern_stage_meta()
        self.note('Pattern workflow: choose source geometry, set the pattern reference/spacing, then create the copies.')
        self.note(f'<b>Current step:</b> {html.escape(stage["title"])}<br>{html.escape(stage["summary"])}<br>{html.escape(stage["hint"])}')
        source_button=QPushButton(tr('Choose source geometry'));source_button.setCheckable(True);source_button.setChecked(self.workspace.pattern_stage=='sources')
        source_button.clicked.connect(lambda:self.choose_pattern_stage('sources'));self.editor_layout.addWidget(source_button)
        form=self.form('Line mirror' if mirror else ('Circular pattern' if circular else 'Rectangular pattern'))
        if mirror:
            guides=QComboBox();guides.addItem(tr('Choose a straight line…'),None)
            for i,e in enumerate(self.draft['entities']):
                if e['kind']=='line':guides.addItem(f'{tr("Line")} {i+1}',i)
            guides.setCurrentIndex(max(0,guides.findData(self.pattern_axis)))
            guides.currentIndexChanged.connect(lambda i:self.set_mirror_axis(guides.itemData(i)) if guides.itemData(i) is not None else None)
            form.addRow(tr('Guide'),guides)
            guide_button=QPushButton(tr('Choose guide line in workspace'));guide_button.setCheckable(True);guide_button.setChecked(self.workspace.pattern_stage=='axis')
            guide_button.clicked.connect(lambda:self.choose_pattern_stage('axis'));self.editor_layout.addWidget(guide_button)
        elif circular:
            center_button=QPushButton(tr('Choose center point in workspace'));center_button.setCheckable(True);center_button.setChecked(self.workspace.pattern_stage=='center')
            center_button.clicked.connect(lambda:self.choose_pattern_stage('center'));self.editor_layout.addWidget(center_button)
            if self.pattern_center is not None:
                for j,label in enumerate(('Center X','Center Y')):self.spin(form,'pattern_center_'+str(j),label,self.pattern_center[j],lambda v,k=j:self.update_pattern_center(k,v))
            count=QSpinBox();count.setRange(1,100);count.setValue(self.pattern_copies);count.valueChanged.connect(lambda v:(setattr(self,'pattern_copies',v),self.sync_gizmo()));form.addRow('New copies',count);self.widgets['copies']=count
            self.note('5 copies + original = 6 equal positions.')
        else:
            columns=QSpinBox();columns.setRange(1,100);columns.setValue(self.pattern_columns);columns.valueChanged.connect(lambda v:(setattr(self,'pattern_columns',v),self.sync_gizmo()));form.addRow('Columns',columns);self.widgets['columns']=columns
            rows=QSpinBox();rows.setRange(1,100);rows.setValue(self.pattern_rows);rows.valueChanged.connect(lambda v:(setattr(self,'pattern_rows',v),self.sync_gizmo()));form.addRow('Rows',rows);self.widgets['rows']=rows
            self.spin(form,'pattern_dx','X spacing',self.pattern_spacing_x,lambda v:setattr(self,'pattern_spacing_x',v))
            self.spin(form,'pattern_dy','Y spacing',self.pattern_spacing_y,lambda v:setattr(self,'pattern_spacing_y',v))
            self.note('The original is the first grid position; copies extend by the X/Y spacing values.')
        if mirror:
            guide_state='not selected' if self.pattern_axis is None else f'Line {self.pattern_axis+1} selected';self.note(f'Sources selected: {len(self.workspace.pattern_selection)} · Guide line: {guide_state}')
        elif circular:
            center_state='not selected' if self.pattern_center is None else f'({self.pattern_center[0]:g}, {self.pattern_center[1]:g})';self.note(f'Sources selected: {len(self.workspace.pattern_selection)} · Center point: {center_state}')
        else:self.note(f'Sources selected: {len(self.workspace.pattern_selection)} · Grid: {self.pattern_columns} × {self.pattern_rows}')
        self.button('Create mirrored copies' if mirror else ('Create circular pattern' if circular else 'Create rectangular pattern'),self.apply_pattern,True)

    def update_pattern_center(self,index,value):
        self.pattern_center[index]=value;self.workspace.pattern_center=list(self.pattern_center);self.workspace.update()
    def apply_pattern(self):
        try:
            sources=copy.deepcopy([self.draft['entities'][i] for i in sorted(self.workspace.pattern_selection) if 0<=i<len(self.draft['entities'])])
            if not sources:raise ModelError('Select at least one source entity.')
            kind=self.workspace.tool
            if kind=='mirror' and (self.pattern_axis is None or self.pattern_axis>=len(self.draft['entities'])):raise ModelError('Select a guide line.')
            if kind=='circular' and self.pattern_center is None:raise ModelError('Select a middle point.')
            guide=copy.deepcopy(self.draft['entities'][self.pattern_axis]) if kind=='mirror' else None
            def generate(report):
                if kind=='mirror':copies=mirror_entities(sources,guide)
                elif kind=='circular':copies=circular_entities(sources,self.pattern_center,self.pattern_copies)
                else:copies=rectangular_entities(sources,self.pattern_columns,self.pattern_rows,self.pattern_spacing_x,self.pattern_spacing_y)
                if not copies:raise ModelError('Select geometry other than the guide line.')
                for i,e in enumerate(copies):
                    validate_entity(e)
                    if i%100==0:report(i+1,len(copies),'Preparing pattern…')
                return copies
            copies=self.run_busy('Preparing pattern…',generate)
            self.sketch_change();self.draft['entities'].extend(copies);self.workspace.pattern_selection.clear();self.workspace.update();self.show_editor()
            self.show_status(f'Created {len(copies)} editable entities. Undo reverses the entire operation.')
        except Exception as err:self.error(err)

    def error(self,e):
        if self.doc.pending_features is None:QMessageBox.warning(self,tr('Operation could not be completed'),tr(str(e)));return
        box=QMessageBox(self);box.setWindowTitle(tr('Operation could not be completed'));box.setText(tr(str(e)));box.setInformativeText(tr('The last valid model is unchanged. Inspect downstream references to repair this pending edit.'))
        repair=box.addButton(tr('Inspect / Repair references'),QMessageBox.ActionRole);box.addButton(QMessageBox.Close);box.exec()
        if box.clickedButton()==repair:self.open_reference_recovery()
    def dirty(self):
        if getattr(self,'component_stack',[]):
            root=self.component_stack[0];return self.assembled_snapshot()!=root['saved_features'] or root['document'].display!=root['saved_display'] or root['document'].parameters_dirty()
        return self.doc.features!=self.saved_features or self.doc.display!=self.saved_display or self.doc.parameters_dirty()
    def precise_changed(self):
        return self.workspace.mode=='sketch' and self.precise_draft is not None and self.precise_draft!=self.precise_baseline
    def has_draft(self):
        if self.precise_changed():return True
        return self.draft is not None and (self.draft_index is None or self.draft!=self.doc.features[self.draft_index])
    def abandon(self):
        if self.has_draft() and QMessageBox.question(self,tr('Unapplied changes'),tr('Discard the current unapplied changes?'),QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Cancel)!=QMessageBox.Discard:return False
        self.history_preview_index=None;self.preview_active=False;self.draft=None;self.draft_index=None;self.precise_draft=None;self.extrude_hits=[];self.workspace.set_extrusion_selection([],False);self.workspace.set_mode('model');self.sketch_bar.hide()
        self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),materials=self.body_materials());return True
    def safe_to_leave(self):
        if not self.abandon():return False
        if not self.dirty():return True
        answer=QMessageBox.question(self,tr('Unsaved project'),tr('Save this project before continuing?'),QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
        if answer==QMessageBox.Cancel:return False
        return self.save() if answer==QMessageBox.Save else True
    def clear_editor(self):
        self.picker_buttons=[];self.current_slots=[]
        while self.editor_layout.count():
            item=self.editor_layout.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
        self.widgets={}
    PICKER_BUTTON_PREFIXES=('Pick ','Click the ','Click a ','Click two points','Use the axis')

    def button(self,label,fn,primary=False):
        b=QPushButton(tr(label));b.clicked.connect(fn)
        if primary:b.setObjectName('primary')
        self.editor_layout.addWidget(b)
        if label.startswith(self.PICKER_BUTTON_PREFIXES):self.picker_buttons.append(b)      # replaced by clicking in the 3D view
        return b
    def note(self,text):
        w=QLabel(tr(text));w.setWordWrap(True);self.editor_layout.addWidget(w)
    def form(self,title,collapsed=False):
        content=QWidget();form=QFormLayout(content);form.setContentsMargins(6,6,6,6);form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        if collapsed:
            group=CollapsibleSection(tr(title),content,self.expanded_sections.get(title,False),lambda on:self.expanded_sections.update({title:on}))
        else:
            group=QGroupBox(tr(title));layout=QVBoxLayout(group);layout.setContentsMargins(0,0,0,0);layout.addWidget(content)
        self.editor_layout.addWidget(group);return form
    def invalidate_preview(self):
        if self.preview_active:
            self.preview_active=False;self.workspace.construction_items=[(f['id'],f['name'],self.doc.frames[f['id']]) for f in self.doc.features if f['kind'] in CONSTRUCTIONS and f['id'] in self.doc.frames and self.doc.display.get('construction',{}).get(f['id'],True)];self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),materials=self.body_materials())
            if hasattr(self,'preview_label'):self.preview_label.setText(tr('Parameters changed · click Preview to update'))
    live_preview=True                     # the Preview updates by itself after a parameter changes
    LIVE_PREVIEW_SKIP=('sketch','extrude','body_move','sketch_move','fillet','chamfer','shell','offset_face','press_pull','construction_plane','hole')

    def live_preview_skipped(self,f):
        """Tools with their own drag arrow refresh themselves; the others use the timer."""
        if f.get('kind')=='construction_plane':return f.get('mode','offset')=='offset'
        return f.get('kind') in self.LIVE_PREVIEW_SKIP

    def parameter_changed(self,callback,value):
        self.invalidate_preview();callback(value);self.precise_redo=None
        self.sync_gizmo();self.schedule_live_preview()

    def schedule_live_preview(self):
        """Tools without a drag arrow get their preview refreshed shortly after each edit.

        Tools that have arrows with exact outlines (extrude, fillet, ...) already show their
        result live; this covers the rest (draft, revolve, patterns, scale, body tools, ...).
        """
        f=self.draft
        if not self.live_preview or f is None or self.live_preview_skipped(f) or self.loading:return
        timer=getattr(self,'live_timer',None)
        if timer is None:
            timer=self.live_timer=QTimer(self);timer.setSingleShot(True);timer.setInterval(300);timer.timeout.connect(self.run_live_preview)
        timer.start()

    def run_live_preview(self):
        f=self.draft
        if not self.live_preview or f is None or self.live_preview_skipped(f) or self.loading:return
        started=time.perf_counter()
        self.preview_feature(quiet=True)
        elapsed=time.perf_counter()-started
        if elapsed>2.0:
            # A model this heavy would make every keystroke wait: fall back to the Preview button.
            self.live_preview=False
            box=self.widgets.get('live_preview')
            if box is not None:
                box.blockSignals(True);box.setChecked(False);box.blockSignals(False)
            self.show_status(tr('Live preview turned off: this model rebuilds slowly. Use Preview.'))
    def preview_feature(self,quiet=False):
        if self.draft is None or self.draft['kind']=='sketch':return
        if missing_inputs(self.draft):return
        self.invalidate_preview()
        try:
            self.prepare_edge_feature()
            features=copy.deepcopy(self.doc.features);draft=self.resolved_feature(prompt=False)
            if self.draft_index is None:features.insert(self.feature_insert_index(draft),draft)
            else:features[self.draft_index]=draft
            solid,preview_sketches,preview_frames=self.run_busy('Building preview…',lambda report:self.doc.preview(features,progress=report))
            preview_items=[(s,preview_frames[id_]) for id_,s in preview_sketches.items()] if draft['kind']=='sketch_move' else []
            self.set_scene_responsive(__import__('surface_tools').scene(solid,preview_frames),preview_items,materials=self.body_materials(),draft=True);self.workspace.construction_items=[(f['id'],f['name'],preview_frames[f['id']]) for f in features if f['kind'] in CONSTRUCTIONS and f['id'] in preview_frames];self.preview_active=True
            note=self.edge_fit_note(draft)
            self.preview_label.setText(tr('Preview only · Apply to keep this result')+(('\n'+note) if note else ''))
            self.show_status(note or 'Preview only. Orbit to inspect; Apply commits, Cancel restores the model.',15000 if note else 0)
        except Exception as e:
            # While typing, a value that cannot be built is reported in the status bar, not in a dialog.
            if quiet:self.show_status(tr(str(e)),8000)
            else:self.error(e)
    def evaluate_expression(self,text):
        """Value of an expression typed into a number box, using the project's parameters."""
        from expressions import evaluate_with_parameters
        return evaluate_with_parameters(text,self.doc.parameters)

    def expression_field(self,key):
        """The numeric field of the feature being edited that a number box with this key edits."""
        f=self.draft
        if not isinstance(f,dict) or f.get('kind') in (None,'sketch'):return None
        value=f.get(key)
        return key if isinstance(value,(int,float)) and not isinstance(value,bool) else None

    def remember_expression(self,field,box):
        """Keep the expression of a number box next to the value it produced (or forget it)."""
        f=self.draft
        if field is None or not isinstance(f,dict):return
        if box.expression:
            f.setdefault('expressions',{})[field]=box.expression
            f.setdefault('expression_values',{})[field]=float(f.get(field,box.value()))
        else:
            for name in ('expressions','expression_values'):
                table=f.get(name)
                if table is not None:
                    table.pop(field,None)
                    if not table:f.pop(name,None)

    def spin(self,form,key,label,value,callback,positive=False):
        w=ExpressionSpinBox(self.evaluate_expression);w.setDecimals(4);w.setRange(.0001 if positive else -100000,100000);w.setSingleStep(1);w.setValue(value)
        field=self.expression_field(key)
        stored=(self.draft.get('expressions') or {}).get(field) if field else None
        if stored:w.set_expression(stored,value)
        def changed(v):
            self.parameter_changed(callback,v);self.remember_expression(field,w)
        w.valueChanged.connect(changed);self.widgets[key]=w;form.addRow(tr(label),w);return w
    def combo(self,form,key,label,values,current,callback):
        w=QComboBox()
        for value in values:w.addItem(tr(option_label(value)),value)
        w.setCurrentIndex(max(0,w.findData(current)))
        w.currentIndexChanged.connect(lambda i:self.parameter_changed(callback,w.itemData(i)));self.widgets[key]=w;form.addRow(tr(label),w)
    def name_field(self,form,f):
        w=QLineEdit(f['name']);w.textChanged.connect(lambda text:f.update(name=text));self.widgets['name']=w;form.addRow(tr('Name'),w)

    def scene_sketches(self):
        sketches,frames=self.doc.sketches,self.doc.frames
        consumed={source['sketch'] for f in self.doc.features if f.get('enabled',True) and f.get('kind')=='extrude' for source in (extrusion_sources(f) if 'source' in f or 'sources' in f else []) if source.get('type')=='sketch'}
        visibility=self.doc.display.get('sketches',{})
        return [(s,frames[id_]) for id_,s in sketches.items() if visibility.get(id_,self.workspace.mode=='extrude' or self.workspace.extrude_selecting or id_ not in consumed) and (not self.draft or id_!=self.draft.get('id'))]
    def refresh(self,fit=False):
        self.preview_active=False
        from expressions import set_default_parameters
        set_default_parameters(self.doc.parameters)       # interface-side sketch solves use this project's table
        if self.selected is not None and self.selected>=len(self.doc.features):self.selected=None
        self.workspace.construction_items=[(f['id'],f['name'],self.doc.frames[f['id']]) for f in self.doc.features if f['kind'] in CONSTRUCTIONS and f['id'] in self.doc.frames and self.doc.display.get('construction',{}).get(f['id'],True)]
        volume=self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),fit,materials=self.body_materials(),volume_of=self.doc.solid)
        self.rebuild_objects();self.rebuild_timeline();self.sync_view_settings();self.show_editor();self.update_title()
        volume=volume or 0
        self.show_status(f'{len(self.doc.features)} features · Volume {volume:,.3f} mm³ · all dimensions in mm')
    def update_title(self):
        if getattr(self,'session_id',None) is None and getattr(self,'sessions',None) is not None and not self.sessions:
            self.setWindowTitle(f'SlothCAD {VERSION}');return
        self.setWindowTitle(f'SlothCAD {VERSION} — {self.path.name if self.path else tr("Untitled")}{" *" if self.dirty() else ""}')
        if hasattr(self,'tabs'):self.sync_tab_title()
    def eventFilter(self,obj,event):
        if obj is getattr(self,'menu_bar',None) and event.type() in (QEvent.Resize,QEvent.LayoutRequest) and hasattr(self,'tab_row'):
            self.fit_tab_row()
        return super().eventFilter(obj,event)

    def start_sketch(self):
        if not self.abandon():return
        self.selected=None;self.workspace.set_mode('support');self.show_editor()
    def support_picked(self,hit):
        try:
            if hit['type']=='construction':self.sketch_on_construction(hit['id']);return
            if hit['type']=='plane':frame=base_frame(hit['plane']);support=None;name=f'{tr("Sketch")} {hit["plane"]}'
            else:
                frame=frame_on_face(self.workspace.faces[hit['index']],projected=True);support=hit['face'];name=tr('Sketch on face')
            self.draft=new_sketch(frame,name,support);self.draft_index=None
            # Anchor new face sketches to the projected world origin so their geometry
            # stays put when the supporting face is resized (older sketches keep the face centre).
            if support:self.draft['frame_origin']='projected'
            self.entity_index=None;self.sketch_undo=[];self.sketch_redo=[]
            self.workspace.set_mode('sketch',self.draft,frame);self.sketch_bar.show();self.set_tool('rectangle')
            if support:
                # The sketch origin can lie outside the face now; keep the clicked face in view.
                self.workspace.center=np.asarray(self.workspace.faces[hit['index']].Center().toTuple(),dtype=float);self.workspace.update()
        except Exception as e:self.error(e)
    def change_sketch_plane(self,reference):
        if reference is None:return
        try:
            from solid_tools import plane_reference
            result,sketches,frames=self.tool_context();frame=plane_reference(reference,result,frames)
            if self.precise_changed() and not self.apply_entity():return
            self.sketch_change();self.draft.update(plane_ref=copy.deepcopy(reference),support=None,frame=copy.deepcopy(frame));self.workspace.active_frame=frame;self.workspace.align(frame);self.workspace.points=[];self.workspace.update()
        except Exception as error:self.error(error)
    def restore_sketch_frame(self):
        from solid_tools import plane_reference
        result,sketches,frames=self.tool_context()
        frame=plane_reference(self.draft['plane_ref'],result,frames) if self.draft.get('plane_ref') else sketch_frame(self.draft,result)
        self.workspace.active_frame=frame;self.workspace.align(frame)

    def toggle_construction(self):
        self.workspace.construction_mode=not self.workspace.construction_mode
        if self.precise_draft is not None and self.entity_index is None:
            self.precise_draft['construction']=self.workspace.construction_mode
            self.precise_baseline['construction']=self.workspace.construction_mode
        self.sync_ribbon();self.workspace.setFocus();self.workspace.update()
        self.show_status('Construction guides: snap and mirror references; never extruded.' if self.workspace.construction_mode else 'Normal sketch geometry.')
    def set_tool(self,tool):
        if hasattr(self.workspace,'reference_highlight'):self.workspace.reference_highlight=[]
        self.workspace.set_measure_active(False)
        if tool=='measure_exit':self.show_editor();return
        self.pattern_axis=None;self.pattern_center=None;self.sketch_corners=[];self.workspace.pattern_pick=None
        if self.workspace.mode!='sketch':return
        if self.precise_changed() and not self.apply_entity():return
        if tool!='text' and self.text_draft is not None:
            # Switching tools keeps a typed text: it is placed like a finished entity.
            if self.text_style_now().text.strip():
                if not self.apply_text():return
            else:self.clear_text_draft()
        self.workspace.constraint_refs=[];self.workspace.constraint_feedback='';self.constraint_feedback=''
        self.workspace.set_tool(tool);self.workspace.setFocus();self.precise_draft=None;self.entity_index=None;self.workspace.selected_entity=None
        for name,b in self.tool_buttons.items():b.setChecked(self.workspace.construction_mode if name=='construction' else name==tool)
        self.show_editor()
    @staticmethod
    def sketch_snapshot(sketch):
        return {key:copy.deepcopy(sketch.get(key,[] if key in ('entities','constraints','projections') else {} if key=='parameters' else None)) for key in ('entities','constraints','name','frame','support','plane_ref','enabled','parameters','projections')}
    def sketch_change(self):
        self.sketch_undo.append(self.sketch_snapshot(self.draft));self.sketch_undo=self.sketch_undo[-100:];self.sketch_redo=[];self.precise_redo=None
    def add_entity(self,ent):
        try:
            if ent.get('kind')=='text_box':
                self.begin_text_box(ent['rect']);return
            if ent.get('kind')=='text':
                created=self.run_busy('Building text outlines…',lambda report:text_polygons(ent.get('text',''),ent.get('position',[0,0]),ent.get('height',5.0)))
                if self.workspace.construction_mode:
                    for item in created:item['construction']=True
                for item in created:validate_entity(item)
                self.sketch_change();self.draft['entities'].extend(created);self.entity_index=None
                self.workspace.active=self.draft;self.workspace.update();self.show_editor();return
            if self.workspace.construction_mode:ent.setdefault('construction',True)
            validate_entity(ent);self.sketch_change();self.draft['entities'].append(ent);self.entity_index=None
            if self.auto_constraints_enabled() and ent.get('kind') in auto_constraints.KINDS:
                # Like Fusion and FreeCAD: ends that land on geometry are joined, near-horizontal lines made horizontal.
                try:
                    result,added=auto_constraints.apply(self.draft,ent)
                    if added:self.draft['entities']=result['entities'];self.draft['constraints']=result.get('constraints',[])
                except Exception:pass
            self.workspace.active=self.draft;self.workspace.update();self.show_editor()
        except Exception as e:self.error(e)

    def auto_constraints_enabled(self):
        try:return str(platform_support.settings().value('sketch/auto_constraints','true')).lower()!='false'
        except Exception:return True

    def set_auto_constraints(self,on):
        try:
            settings=platform_support.settings();settings.setValue('sketch/auto_constraints','true' if on else 'false');settings.sync()
        except Exception:pass
    def select_entity(self,index):
        self.workspace.selected_entity=index;self.workspace.update()
        self.precise_redo=None;self.entity_index=index;self.precise_draft=copy.deepcopy(self.draft['entities'][index]);self.precise_baseline=copy.deepcopy(self.precise_draft);self.show_editor()
    def toggle_sketch_corner(self,point):
        """Corner tools work like the solid tools: pick first, then size with the arrow, then apply."""
        try:
            from sketch_corners import modify_corner
            tolerance=12/max(self.workspace.scale(),1e-12)
            corners=[list(c) for c in getattr(self,'sketch_corners',[])]
            for index,existing in enumerate(corners):
                if math.dist(existing,point)<=2*tolerance:
                    corners.pop(index);self.sketch_corners=corners;self.show_editor();return
            modify_corner(self.draft['entities'],point,self.workspace.tool,1e-3,tolerance)   # raises when no corner is there
            corners.append([float(point[0]),float(point[1])]);self.sketch_corners=corners
            self.show_editor()
        except Exception as e:self.show_status(tr(str(e)))
    def clear_sketch_corners(self):
        self.sketch_corners=[];self.show_editor()
    def enter_pressed(self,widget):
        """Enter applies the tool being edited, like its Apply button. True when it was used."""
        from PySide6.QtWidgets import QAbstractSpinBox
        w=self.workspace
        if self.draft is None or w.measure_active:return False
        parent=widget.parentWidget()
        spin=widget if isinstance(widget,QAbstractSpinBox) else (parent if isinstance(parent,QAbstractSpinBox) else None)
        if widget is not w and spin is None:return False
        if w.mode=='sketch':
            tool=w.tool
            if tool=='text' and self.text_draft is not None:
                if spin is not None:spin.interpretText()
                self.apply_text();return True
            if tool in ('fillet','chamfer') and getattr(self,'sketch_corners',None):
                if spin is not None:spin.interpretText()
                self.apply_sketch_corners();return True
            if tool in ('mirror','circular','rectangular') and w.pattern_selection:
                if spin is not None:spin.interpretText()
                self.apply_pattern();return True
            return False            # drawing tools keep Enter for their own input (splines, typed sizes)
        if self.draft.get('kind')=='sketch':return False
        if spin is not None:spin.interpretText()
        self.apply_feature();return True

    def apply_sketch_corners(self):
        corners=list(getattr(self,'sketch_corners',[]))
        if not corners:self.show_status(tr('Click a corner first.'));return
        try:
            from sketch_corners import modify_corner
            tolerance=12/max(self.workspace.scale(),1e-12);size=float(getattr(self,'sketch_corner_size',1.))
            entities=copy.deepcopy(self.draft['entities'])
            for point in corners:entities=modify_corner(entities,point,self.workspace.tool,size,tolerance)
            linked={e['id']:e for e in self.draft['entities'] if e.get('projection')}
            changed={e['id']:e for e in entities}
            if any(changed.get(id_)!=e for id_,e in linked.items()):raise ModelError('Break the projection link before editing this geometry.')
            result=retain_constraints(self.draft,entities)
            self.sketch_change();self.draft.update(self.sketch_snapshot(result))
            self.sketch_corners=[];self.entity_index=None;self.precise_draft=None;self.workspace.selected_entity=None
            self.workspace.update();self.show_editor()
        except Exception as e:self.error(e)
    def modify_sketch_corner(self,point):
        try:
            from sketch_corners import modify_corner
            replacement=modify_corner(self.draft['entities'],point,self.workspace.tool,getattr(self,'sketch_corner_size',1.),12/max(self.workspace.scale(),1e-12))
            linked={e['id']:e for e in self.draft['entities'] if e.get('projection')}
            changed={e['id']:e for e in replacement}
            if any(changed.get(id_)!=e for id_,e in linked.items()):raise ModelError('Break the projection link before editing this geometry.')
            result=retain_constraints(self.draft,replacement)
            self.sketch_change();self.draft.update(self.sketch_snapshot(result))
            self.entity_index=None;self.precise_draft=None;self.workspace.selected_entity=None
            self.workspace.update();self.show_editor()
        except Exception as e:self.error(e)

    def trim_entity(self,index,point):
        if self.draft['entities'][index].get('projection'):self.show_status(tr('Break the projection link before editing this geometry.'));return
        try:
            if self.workspace.tool=='extend':
                from sketch_tools import extend_entity
                replacement=extend_entity(copy.deepcopy(self.draft['entities']),index,point)
            else:
                replacement=self.run_busy('Trimming sketch…',lambda report:trim_entities(copy.deepcopy(self.draft['entities']),index,point))
            result=retain_constraints(self.draft,replacement)
            self.sketch_change();self.draft.update(self.sketch_snapshot(result))
            self.entity_index=None;self.precise_draft=None;self.workspace.selected_entity=None
            self.workspace.update();self.show_editor()
        except Exception as e:self.error(e)
    def delete_entity(self):
        w=self.workspace
        if self.entity_index is None and w.tool=='select' and w.pattern_selection and self.draft and self.draft.get('kind')=='sketch':
            chosen={i for i in w.pattern_selection if 0<=i<len(self.draft['entities'])}
            if any(self.draft['entities'][i].get('projection') for i in chosen):self.show_status(tr('Break the projection link before editing this geometry.'));return
            replacement=[e for i,e in enumerate(self.draft['entities']) if i not in chosen]
            try:result=retain_constraints(self.draft,replacement)
            except Exception as e:self.error(e);return
            self.sketch_change();self.draft.update(self.sketch_snapshot(result));w.pattern_selection.clear();self.precise_draft=None;w.selected_entity=None
            w.update();self.show_editor();self.show_status(f'{len(chosen)} '+tr('sketch entities deleted'));return
        if self.entity_index is None:return
        if self.draft['entities'][self.entity_index].get('projection'):self.show_status(tr('Break the projection link before editing this geometry.'));return
        replacement=[e for i,e in enumerate(self.draft['entities']) if i!=self.entity_index]
        try:result=retain_constraints(self.draft,replacement)
        except Exception as e:self.error(e);return
        self.sketch_change();self.draft.update(self.sketch_snapshot(result));self.entity_index=None;self.precise_draft=None;self.workspace.selected_entity=None
        self.workspace.update();self.show_editor()
    def toggle_selected_construction(self):
        w=self.workspace
        chosen=[i for i in sorted(w.pattern_selection) if 0<=i<len(self.draft['entities'])]
        if not chosen:return
        self.sketch_change()
        turn_on=not all(self.draft['entities'][i].get('construction') for i in chosen)
        for i in chosen:self.draft['entities'][i]['construction']=turn_on
        w.update();self.show_editor()

    def apply_entity(self):
        try:
            ent=copy.deepcopy(self.precise_draft);validate_entity(ent)
            if self.entity_index is None:self.add_entity(ent)
            else:
                result=edit_entity(self.draft,ent)
                self.sketch_change();self.draft['entities']=result['entities'];self.workspace.update()
            self.precise_draft=None;self.entity_index=None;self.workspace.selected_entity=None;self.workspace.pattern_selection.clear();self.show_editor();return True
        except Exception as e:
            self.constraint_error(e) if self.draft.get("constraints") else self.error(e)
            return False
    def finish_sketch(self):
        if not self.draft or self.draft['kind']!='sketch':return False
        if self.precise_changed():
            if not self.apply_entity():return False
        if self.text_draft is not None:
            # A text that is still in its box is placed, not lost.
            if self.text_style_now().text.strip():
                if not self.apply_text():return False
            else:self.clear_text_draft()
        try:
            if not self.draft['entities']:raise ModelError('Draw or add at least one sketch entity before finishing.')
            if not self.draft['name'].strip():raise ModelError('Enter a sketch name.')
            features=copy.deepcopy(self.doc.features)
            if self.draft_index is None:features.append(self.draft);index=len(features)-1
            else:features[self.draft_index]=self.draft;index=self.draft_index
            self.run_busy('Rebuilding model…',lambda report:self.doc.commit(features,progress=report));self.selected=index;self.draft=None;self.draft_index=None;self.precise_draft=None
            self.workspace.set_mode('model');self.sketch_bar.hide();self.refresh();return True
        except Exception as e:self.error(e);return False
    def edit_selected_sketch(self):
        if self.selected is None or self.doc.features[self.selected]['kind']!='sketch':return
        if not self.abandon():return
        try:
            self.draft=copy.deepcopy(self.doc.features[self.selected]);self.draft_index=self.selected;self.entity_index=None;self.precise_draft=None
            frame=copy.deepcopy(self.doc.frames.get(self.draft['id'],self.draft['frame']))
            self.workspace.set_mode('sketch',self.draft,frame);self.sketch_undo=[];self.sketch_redo=[];self.sketch_bar.show();self.set_tool('select')
            self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),materials=self.body_materials())
        except Exception as e:self.error(e)
    def start_extrude(self):
        if self.workspace.mode=='sketch':
            if not self.finish_sketch():return
        elif not self.abandon():return
        self.selected=None;self.extrude_hits=[];self.workspace.set_mode('extrude');self.workspace.set_extrusion_selection([],True)
        self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),materials=self.body_materials());self.show_editor()

    def extrusion_source_key(self,source):
        return self.workspace.extrusion_source_key(source)

    def normalized_extrusion_source(self,hit):
        return {k:copy.deepcopy(v) for k,v in hit.items() if k!='index'}

    PROFILE_PICK_TOOLS=('revolve','sweep','loft')

    def profile_picked(self,hit):
        """A clicked sketch profile becomes the profile (revolve, sweep) or the next section (loft)."""
        f=self.draft
        if hit.get('type') not in ('sketch','face'):
            self.show_status(tr('Pick a closed sketch profile or a planar face.'));return
        source=self.normalized_extrusion_source(hit)
        if f['kind']=='loft':
            key=self.extrusion_source_key(source);sections=f.setdefault('sections',[])
            found=next((i for i,item in enumerate(sections) if self.extrusion_source_key(item)==key),None)
            if found is None:sections.append(source)
            else:sections.pop(found)
        else:f['source']=source
        self.invalidate_preview();self.show_editor()
        if f['kind']=='sweep' and not f.get('path'):self.begin_path_pick()

    def extrusion_picked(self,hit):
        if self.draft and self.draft.get('kind') in self.PROFILE_PICK_TOOLS:
            self.profile_picked(hit);return
        key=self.extrusion_source_key(hit);found=next((i for i,item in enumerate(self.extrude_hits) if self.extrusion_source_key(item)==key),None)
        if found is None:self.extrude_hits.append(copy.deepcopy(hit))
        else:self.extrude_hits.pop(found)
        self.apply_extrusion_hits()

    def extrusion_box(self,hits,mode):
        """Add (or, with Ctrl+Shift, remove) every profile and face a rubber band caught, in one update."""
        changed=0
        for hit in hits:
            key=self.extrusion_source_key(hit);found=next((i for i,item in enumerate(self.extrude_hits) if self.extrusion_source_key(item)==key),None)
            if mode=='add' and found is None:self.extrude_hits.append(copy.deepcopy(hit));changed+=1
            elif mode=='remove' and found is not None:self.extrude_hits.pop(found);changed+=1
        if not changed:
            self.show_status(tr('Nothing new inside the box.'));return
        self.apply_extrusion_hits()

    def select_all_profiles(self):
        """Every closed profile of the visible sketches becomes an extrusion source."""
        hits=[]
        for sketch,frame in self.workspace.sketches:
            for profile in self.workspace.cached_profiles(sketch):
                hits.append(dict(type='sketch',sketch=sketch['id'],entities=profile['entities'],holes=profile['holes'],profile_mode='nested'))
        if not hits:self.show_status(tr('There are no visible sketch profiles to select.'));return
        self.extrusion_box(hits,'add')

    def apply_extrusion_hits(self):
        sources=[self.normalized_extrusion_source(item) for item in self.extrude_hits]
        if self.draft is None or self.draft.get('kind')!='extrude':
            self.draft=dict(kind='extrude',id=identifier(),name=tr('Extrude selection'),enabled=True,depth=DEFAULT_EXTRUDE_DEPTH,operation='auto',signed_depth=False,sources=[])
            self.draft_index=None
        self.draft['sources']=sources
        if sources:self.draft['source']=copy.deepcopy(sources[0])  # compatibility with pre-multi-extrude builds
        else:self.draft.pop('source',None)
        count=len(sources);self.draft['name']=tr('Extrude')+' '+tr(('selection' if count!=1 else ('sketch' if sources[0].get('type')=='sketch' else 'face')))
        # Keep model-style orbit controls after the first pick while click-to-toggle extrusion selection remains active.
        if self.workspace.mode=='extrude':self.workspace.set_mode('model')
        self.workspace.set_extrusion_selection(self.extrude_hits,True);self.show_editor();self.sync_ribbon()
        self.show_status(f'{count} extrusion source'+('' if count==1 else 's')+' selected · click another face/profile to add it, or click a selected one to remove it.')

    def box_selected(self,info):
        kind=info.get('kind');mode=info.get('mode','add')
        if kind=='extrude':self.extrusion_box(info.get('hits',[]),mode)
        elif kind=='faces':self.faces_box(info.get('indices',[]),mode)

    def faces_box(self,indices,mode):
        """Rubber-band selection for tools that take faces or bodies."""
        f=self.draft;w=self.workspace
        if not f or not indices:
            self.show_status(tr('Nothing inside the box.'));return
        from body_tools import BODY_TOOLS
        from references import resolve_body,body_reference
        from solid_tools import face_ref
        try:
            result=self.tool_context()[0]
            if f['kind'] in BODY_TOOLS:
                if result is None:return
                bodies=result.val().Solids();key=w.solid_pick_key if w.solid_pick_key in ('targets','tools') else 'targets'
                refs=f.setdefault(key,[]);owners=[]
                for index in indices:
                    face=w.faces[index]
                    owner=next((i for i,b in enumerate(bodies) if any(face.isSame(x) for x in b.Faces())),None)
                    if owner is not None and owner not in owners:owners.append(owner)
                for owner in owners:
                    existing=next((r for r in refs if resolve_body(result,r)[0]==owner),None)
                    if mode=='remove' and existing is not None:refs.remove(existing)
                    elif mode=='add' and existing is None:
                        if f['kind']=='body_combine' and key=='targets':refs.clear()
                        refs.append(body_reference(bodies[owner],owner,len(bodies),result))
                self.invalidate_preview();self.show_editor();return
            if f['kind'] in ('shell','draft')+__import__('face_tools').FACE_TOOLS+__import__('advanced_patterns').PATTERN_TOOLS:
                refs=f.setdefault('faces',[])
                for index in indices:
                    face=w.faces[index];existing=next((r for r in refs if self.face_is_selected(face,[r],result)),None)
                    if mode=='remove' and existing is not None:refs.remove(existing)
                    elif mode=='add' and existing is None:refs.append(face_ref(face,result))
                self.invalidate_preview();self.show_editor();return
            self.show_status(tr('This tool takes a single face: click the face you want.'))
        except Exception as error:self.error(error)

    def set_extrude_selection_active(self,on):
        if not self.draft or self.draft.get('kind')!='extrude' or self.draft_index is not None:return
        self.workspace.set_extrusion_selection(self.extrude_hits,bool(on));self.sync_ribbon()

    def clear_extrusion_sources(self):
        if not self.draft or self.draft.get('kind')!='extrude' or self.draft_index is not None:return
        self.extrude_hits=[];self.draft['sources']=[];self.draft.pop('source',None)
        self.workspace.set_extrusion_selection([],True);self.invalidate_preview();self.show_editor()
    def resolved_feature(self,prompt=False):
        f=copy.deepcopy(self.draft)
        if not f or f.get('kind')!='extrude' or f.get('operation')!='auto':return f
        if self.doc.solid is None:f['operation']='add';return f
        intersects=False
        try:
            probe=copy.deepcopy(f);probe['operation']='intersect'
            prefix=self.doc.features if self.draft_index is None else self.doc.features[:self.draft_index]
            self.run_busy('Checking extrusion overlap…',lambda report:self.doc.preview(copy.deepcopy(prefix)+[probe],progress=report));intersects=True
        except Exception:
            intersects=False
        if not intersects:f['operation']='add';return f
        if not prompt:f['operation']='add';return f
        box=QMessageBox(self);box.setWindowTitle(tr('Extrusion crosses an existing body'))
        box.setText(tr('This extrusion intersects existing solid material. What should SlothCAD do?'))
        join=box.addButton(tr('Join'),QMessageBox.AcceptRole);cut=box.addButton(tr('Cut'),QMessageBox.DestructiveRole);box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton()==join:f['operation']='add'
        elif box.clickedButton()==cut:f['operation']='cut'
        else:return None
        return f

    def apply_feature(self):
        if not self.draft:return
        need=missing_inputs(self.draft)
        if need:
            self.show_status(tr('Still needed:')+' '+', '.join(tr(n) for n in need));return
        try:
            if not self.draft['name'].strip():raise ModelError('Enter a feature name.')
            self.prepare_edge_feature()
            feature=self.resolved_feature(prompt=True)
            if feature is None:return
            features=copy.deepcopy(self.doc.features)
            if self.draft_index is None:index=self.feature_insert_index(feature);features.insert(index,feature)
            else:features[self.draft_index]=feature;index=self.draft_index
            self.run_busy('Rebuilding model…',lambda report:self.doc.commit(features,progress=report));self.selected=index;self.draft=None;self.draft_index=None;self.extrude_hits=[]
            self.workspace.set_extrusion_selection([],False);self.workspace.set_mode('model');self.refresh(fit=len(features)<=2)
            note=self.edge_fit_note(feature)
            if note:self.show_status(note,15000)
        except Exception as e:self.error(e)
    def edge_fit_note(self,feature):
        """Explain what auto-fit adjusted on the last build of a fillet/chamfer."""
        from model import EDGE_REPORTS
        report=EDGE_REPORTS.get(feature.get('id')) if feature else None
        if not report or not (report.get('reduced') or report.get('skipped')):return ''
        parts=[]
        if report['reduced']:
            sizes=', '.join(f'{size:.3g} mm' for _,size in report['reduced'])
            parts.append(f"{tr('Edges using a smaller size (largest that fits):')} {len(report['reduced'])}/{report['total']} ({sizes})")
        if report['skipped']:
            parts.append(f"{tr('Edges skipped (no size fits):')} {len(report['skipped'])}/{report['total']}")
        return tr(report['kind'].title())+' · '+' · '.join(parts)
    def prepare_edge_feature(self):
        """Fillets and chamfers fit oversized values automatically unless turned off."""
        if self.draft and self.draft.get('kind') in ('fillet','chamfer'):self.draft.setdefault('auto_fit',True)
    def new_edge(self,kind):
        if not self.abandon():return
        if self.doc.solid is None:self.error('Create a body before using '+kind+'.');return
        self.edge_pick_point=None;self.workspace.last_edge_pick=None
        self.draft=new_feature(kind);self.draft['id']=identifier();self.draft['name']=tr(self.draft.get('name',kind.title()));self.draft['edge_refs']=[];self.draft['auto_fit']=True;self.draft_index=None;self.selected=None
        self.edge_size_limit=None;self.edge_size_limit_bounded=True
        warm_up_limit_search()        # worker processes start while the edges are being picked
        self.workspace.set_mode('edge');self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),materials=self.body_materials());self.show_editor()

    def edge_limit_key(self):
        if not self.draft or self.draft.get('kind') not in ('fillet','chamfer'):return None
        refs=self.draft.get('edge_refs') or []
        compact=tuple((tuple(round(float(v),7) for v in ref.get('center',[])),round(float(ref.get('length',0)),7)) for ref in refs)
        mode=tuple(self.draft.get(k) for k in ('mode','distance2','angle','radius_end','flip'))
        return (self.doc.revision,self.draft_index,self.draft['kind'],compact,mode)

    def calculate_edge_size_limit(self,block=False):
        """Make the largest working fillet/chamfer size known for the current selection.

        It is searched once per selection and remembered. In the running program the search
        happens in worker processes while the window stays usable (the arrow is simply not
        capped until the answer arrives); tests and offscreen runs search synchronously.
        """
        if not self.draft or self.draft.get('kind') not in ('fillet','chamfer'):return
        refs=self.draft.get('edge_refs') or []
        if not refs:
            self.edge_size_limit=None;self.edge_size_limit_bounded=True;return
        key=self.edge_limit_key()
        if key in self.edge_limit_cache:
            self.edge_size_limit,self.edge_size_limit_bounded=self.edge_limit_cache[key];return
        kind=self.draft['kind'];hint=self.draft.get('radius',1.0);index=self.draft_index
        try:options=edge_options(self.draft)
        except ModelError:options={}
        self._limit_options=options
        if not block and LIMIT_ASYNC:
            if self.edge_limit_pending==key:return
            self.edge_limit_pending=key
            # Wait until the selection has rested: every click would otherwise start a search that
            # is out of date a moment later (and resolving the picks alone holds the interpreter lock).
            timer=getattr(self,'_limit_timer',None)
            if timer is None:
                timer=self._limit_timer=QTimer(self);timer.setSingleShot(True);timer.setInterval(700)
                timer.timeout.connect(self.start_limit_search)
            self._limit_job=(key,kind,hint,index);timer.start()
            return
        self.begin_limit_search(key,kind,hint,index,refs)

    def start_limit_search(self):
        job=getattr(self,'_limit_job',None)
        if job is None:return
        key,kind,hint,index=job
        if key!=self.edge_limit_key():
            if self.edge_limit_pending==key:self.edge_limit_pending=None
            return
        self.begin_limit_search(key,kind,hint,index,copy.deepcopy(self.draft.get('edge_refs') or []),background=True)

    def begin_limit_search(self,key,kind,hint,index,refs,background=False):
        options=getattr(self,'_limit_options',{})
        if background:
            doc=self.doc;solid=doc.solid;history=copy.deepcopy(doc.features[:index]) if index is not None else None
            references=copy.deepcopy(refs);signals=self._limit_signals
            def work():
                try:
                    from mesh_cache import KERNEL_LOCK
                    if history is None:base=solid
                    else:
                        with KERNEL_LOCK:base,_,_=doc.preview(history)
                    value,bounded=maximum_edge_size(base,kind,references,hint=hint,options=options,
                                                    on_partial=lambda size:signals.done.emit((key,size,True,None,True)))
                    signals.done.emit((key,value,bounded,None))
                except BaseException as error:signals.done.emit((key,None,True,error))
            threading.Thread(target=work,name='SlothCAD-limit-search',daemon=True).start()
            return
        def operation(report):
            if index is None:
                base=self.doc.solid
            else:
                report(0,32,'Preparing geometry before this feature…')
                base,_,_=self.doc.preview(copy.deepcopy(self.doc.features[:index]))
            return maximum_edge_size(base,kind,copy.deepcopy(refs),hint=hint,progress=report,options=options)
        try:
            value,bounded=self.run_busy(f'Finding maximum {kind} size…',operation)
            self.edge_size_limit=value;self.edge_size_limit_bounded=bounded
            self.edge_limit_cache[key]=(value,bounded)
        except Exception:
            # Keep the editor usable if an old saved edge reference can no longer
            # be resolved; Preview/Apply will still report the detailed error.
            self.edge_size_limit=0.0;self.edge_size_limit_bounded=True

    # ---- size limits of the tools whose value needs the whole history (shell, offset face, press/pull)
    def history_limits_async(self):
        import limit_search
        return LIMIT_ASYNC and limit_search.worker_count()>0

    def request_history_limits(self,cache_key,f,field,sign,minimum):
        pending=self.__dict__.setdefault('history_limit_pending',{})
        if pending.get('key')==cache_key:return
        pending['key']=cache_key
        features=copy.deepcopy(self.doc.features)
        position=self.draft_index if self.draft_index is not None else self.feature_insert_index(f)
        diagonal=1000.
        try:
            box=self.tool_context()[0].val().BoundingBox()
            diagonal=max(10.,2*math.sqrt(box.xlen**2+box.ylen**2+box.zlen**2))
        except Exception:pass
        self._history_job=(cache_key,features[:position],copy.deepcopy(f),field,sign,minimum,diagonal,abs(float(f.get(field,0.) or 0.)))
        timer=getattr(self,'_history_timer',None)
        if timer is None:
            timer=self._history_timer=QTimer(self);timer.setSingleShot(True);timer.setInterval(700)
            timer.timeout.connect(self.start_history_search)
            self._history_signals=_LimitSignals(self);self._history_signals.done.connect(self.history_limits_ready)
        timer.start()

    def start_history_search(self):
        job=getattr(self,'_history_job',None)
        if job is None or self.__dict__.get('history_limit_pending',{}).get('key')!=job[0]:return
        cache_key,prefix,trial,field,sign,minimum,diagonal,current=job
        signals=self._history_signals
        def work():
            import limit_search
            try:
                state={}
                def partial(direction,good):
                    state['neg' if direction<0 else 'pos']=good
                    signals.done.emit((cache_key,minimum,state.get('neg'),state.get('pos'),True,None))
                outcome=limit_search.history_limits(prefix,trial,field,sign,diagonal,current,on_partial=partial)
                if outcome is NotImplemented:signals.done.emit((cache_key,minimum,None,None,False,RuntimeError('no workers')))
                else:signals.done.emit((cache_key,minimum,outcome[0],outcome[1],False,None))
            except BaseException as error:signals.done.emit((cache_key,minimum,None,None,False,error))
        threading.Thread(target=work,name='SlothCAD-history-limits',daemon=True).start()

    def history_limits_ready(self,payload):
        cache_key,minimum,negative,positive,provisional,error=payload
        pending=self.__dict__.setdefault('history_limit_pending',{})
        if error is not None:
            # leave the tool uncapped rather than searching again on every refresh
            self.__dict__.setdefault('value_limit_cache',{})[cache_key]=(minimum,None)
            if pending.get('key')==cache_key:pending['key']=None
            return
        pair=self.history_limit_pair(negative,positive,minimum)
        if provisional:self.__dict__.setdefault('value_limit_partial',{})[cache_key]=pair
        else:
            self.__dict__.setdefault('value_limit_cache',{})[cache_key]=pair
            self.__dict__.setdefault('value_limit_partial',{}).pop(cache_key,None)
            if pending.get('key')==cache_key:pending['key']=None
        if self.draft is not None:self.sync_gizmo()

    def edge_limit_ready(self,payload):
        """A background size search finished: remember it and cap the arrow if it still applies."""
        key,value,bounded,error=payload[:4];provisional=len(payload)>4 and payload[4]
        if self.edge_limit_pending==key and not provisional:self.edge_limit_pending=None
        if provisional:
            # A size already known to build: cap the arrow now, the exact limit follows.
            if key==self.edge_limit_key() and (self.edge_size_limit is None or value>self.edge_size_limit or self.edge_limit_provisional!=key):
                self.edge_size_limit,self.edge_size_limit_bounded=value,True;self.edge_limit_provisional=key
                self.sync_gizmo()
            return
        if error is not None:
            self.show_status(tr('The maximum size could not be calculated; the size is fitted when applying.'),6000)
        else:self.edge_limit_cache[key]=(value,bounded)
        if error is not None or key!=self.edge_limit_key():return
        self.edge_size_limit,self.edge_size_limit_bounded=value,bounded
        hint=self.widgets.get('edge_limit_hint') if hasattr(self,'widgets') else None
        try:
            if hint is not None and self.draft:hint.setText(tr(self.edge_limit_text(self.draft['kind'],len(self.draft.get('edge_refs') or []))))
        except RuntimeError:pass
        self.sync_gizmo()

    def edge_selection_changed(self):
        if not self.draft or self.draft.get('kind') not in ('fillet','chamfer'):return
        picked=getattr(self.workspace,'last_edge_pick',None)
        if picked is not None:self.edge_pick_point=picked
        # Anchor picks to the full model (all bodies, with body identities), not the
        # visible-only display shape. When editing an earlier feature the final model
        # is the wrong context, so store a plain reference and let the rebuild anchor it.
        context=self.doc.solid if self.draft_index is None else None
        self.draft['edge_refs']=[edge_reference(e,context) for e in self.workspace.selected_edge_objects()]
        # The maximum-size search runs up to 32 trial fillets, so it is only run on
        # request (or reused from cache) instead of blocking every edge click.
        self.invalidate_preview();self.edge_size_limit=None;self.edge_size_limit_bounded=True
        key=self.edge_limit_key()
        if key in self.edge_limit_cache:self.edge_size_limit,self.edge_size_limit_bounded=self.edge_limit_cache[key]
        self.show_editor()
    def select(self,row):
        if self.loading or row<0:return False
        self.history_preview_index=None
        if not self.abandon():
            self.sync_ribbon();return False
        self.selected=row;f=self.doc.features[row]
        if f['kind']!='sketch':
            self.draft=copy.deepcopy(f);self.draft_index=row
            if f['kind'] in SPATIAL_TOOLS:self.spatial_undo=[];self.spatial_redo=[];self.spatial_points=[]
            self.edge_size_limit=None;self.edge_size_limit_bounded=True
        self.show_editor()
        return True
    def cancel(self):
        if self.workspace.measure_active:
            self.workspace.set_measure_active(False);self.show_editor();return
        self.history_preview_index=None;self.preview_active=False;self.draft=None;self.draft_index=None;self.precise_draft=None;self.extrude_hits=[];self.workspace.set_extrusion_selection([],False);self.workspace.set_mode('model');self.sketch_bar.hide();self.refresh()
    def delete_feature(self,index=None):
        if index is not None:
            if not 0<=index<len(self.doc.features):return
            self.selected=index
        if self.selected is None:return
        if not self.abandon():return
        try:
            features=copy.deepcopy(self.doc.features);del features[self.selected];self.run_busy('Rebuilding model…',lambda report:self.doc.commit(features,progress=report));self.selected=None;self.refresh()
        except Exception as e:self.error(e)
    def undo(self):
        if self.draft and self.draft['kind'] in SPATIAL_TOOLS:self.spatial_history();return
        if self.workspace.mode=='sketch' and self.draft:
            if self.workspace.points:
                self.workspace.point_redo.append(self.workspace.points.pop());self.workspace.reset_dimensions();self.workspace.update();return
            if self.precise_changed():
                self.precise_redo=copy.deepcopy(self.precise_draft);self.precise_draft=copy.deepcopy(self.precise_baseline);self.workspace.update();self.show_editor();return
            if self.sketch_undo:
                self.sketch_redo.append(self.sketch_snapshot(self.draft));self.draft.update(self.sketch_undo.pop());self.constraint_feedback='';self.constraint_conflicts=[];self.constraint_refs.clear();self.workspace.constraint_refs=[];self.workspace.selected_entity=None;self.workspace.pattern_selection.clear();self.entity_index=None;self.precise_draft=None;self.precise_redo=None;self.precise_baseline=None;self.workspace.points=[];self.workspace.reset_dimensions();self.restore_sketch_frame();self.workspace.update();self.show_editor()
            return
        if not self.abandon():return
        if self.run_busy('Undoing change…',lambda report:self.doc.undo(progress=report)):self.selected=None;self.refresh()
    def redo(self):
        if self.draft and self.draft['kind'] in SPATIAL_TOOLS:self.spatial_history(True);return
        if self.workspace.mode=='sketch' and self.draft:
            if self.precise_redo is not None and self.precise_draft is not None:
                self.precise_draft=self.precise_redo;self.precise_redo=None;self.workspace.update();self.show_editor();return
            if self.workspace.point_redo:
                self.workspace.points.append(self.workspace.point_redo.pop());self.workspace.update();return
            if self.sketch_redo:
                self.sketch_undo.append(self.sketch_snapshot(self.draft));self.draft.update(self.sketch_redo.pop());self.constraint_feedback='';self.constraint_conflicts=[];self.constraint_refs.clear();self.workspace.constraint_refs=[];self.workspace.selected_entity=None;self.workspace.pattern_selection.clear();self.entity_index=None;self.precise_draft=None;self.precise_redo=None;self.precise_baseline=None;self.workspace.points=[];self.workspace.reset_dimensions();self.restore_sketch_frame();self.workspace.update();self.show_editor()
            return
        if not self.abandon():return
        if self.run_busy('Redoing change…',lambda report:self.doc.redo(progress=report)):self.selected=None;self.refresh()
    def view_preset(self,name):
        if self.workspace.mode=='sketch':self.workspace.align(self.workspace.active_frame)
        else:self.workspace.preset(name)

    def show_editor(self):
        self.show_editor_content()
        self.schedule_float_layout()

    def show_editor_content(self):
        self.prepare_active_sketch()
        self.clear_editor();mode=self.workspace.mode;self.sync_ribbon();self.rebuild_objects();self.editor_idle=False
        if self.workspace.measure_active:self.measure_editor()
        elif self.history_preview_index is not None and self.draft is None and mode=='model':
            index=self.history_preview_index;f=self.doc.features[index]
            self.note(f'<b>History preview</b><br>Showing the model immediately after feature {index+1}: {html.escape(f.get("name","Unnamed"))}.')
            self.note(f'Later features ({len(self.doc.features)-index-1}) are temporarily hidden; nothing has been deleted.')
            self.button('Return to latest model',self.return_to_latest,True)
            self.button('Edit this feature',lambda i=index:self.timeline_edit(i))
            if index<len(self.doc.features)-1:self.button('Revert project to this point…',lambda i=index:self.revert_to_timeline(i))
        elif mode=='support':
            self.note('Select one of the colored planes in the workspace, or click a planar face on the body.')
            for name,label in [('XY','XY plane · normal Z'),('XZ','XZ plane · normal Y'),('YZ','YZ plane · normal X')]:
                self.button(label,lambda checked=False,n=name:self.support_picked({'type':'plane','plane':n}))
            self.note('Origin planes pass through world 0,0,0. A face sketch aligns to the selected face.');self.button('Cancel',self.cancel)
        elif mode=='sketch':self.sketch_editor()
        elif self.draft is not None:self.feature_editor()
        elif mode=='extrude':self.note('Select one or more closed sketch profiles and/or planar body faces. Selected sources stay highlighted. Every selected source will use the same extrusion depth and operation.');self.button('Cancel extrusion',self.cancel)
        elif self.selected is not None and self.doc.features[self.selected]['kind']=='sketch':
            f=self.doc.features[self.selected];self.note(f'{f["name"]}\n{len(f["entities"])} entities · {len(regions(f))} closed profiles')
            self.note('Double-click this sketch in the left panel to edit it.');self.button('Extrude a profile',self.start_extrude);self.button('Move sketch',self.start_sketch_move)
        else:
            # Nothing is being edited: the tool settings window stays hidden.
            self.editor_idle=True
            self.note('Create sketch to start on an origin plane or body face. Finish the sketch, then use Extrude to select a profile. Extrude also works directly on planar body faces.')
        self.sync_slots()
        localize_tree(self.editor);self.editor_layout.addStretch();self.sync_gizmo()

    def sketch_editor(self):
        if self.text_draft is not None and self.workspace.tool=='text' and self.workspace.text_box is not None:
            self.text_editor();return
        self.constraint_editor()
        if self.workspace.tool=="constraint":return
        if self.workspace.tool=="project":self.projection_editor();return
        if self.entity_index is not None and self.draft['entities'][self.entity_index].get('projection'):
            self.note('Linked geometry is read-only. Break its projection link before editing.');self.button('Break selected projection link',self.break_projection)
        form=self.form('Sketch settings',collapsed=True);self.name_field(form,self.draft)
        self.reference_combo(form,'sketch_plane','Sketch plane',self.plane_choices(),self.draft.get('plane_ref'),self.change_sketch_plane)
        pattern=self.workspace.tool in Workspace.SELECTION_TOOLS
        if not pattern:
            self.spin(form,'grid','Grid spacing',self.workspace.grid,lambda v:self.set_grid(v),True)
        check=QCheckBox(tr('Snap to grid and geometry'));check.setChecked(self.workspace.snap_enabled);check.toggled.connect(lambda v:setattr(self.workspace,'snap_enabled',v));form.addRow(check)
        auto=QCheckBox(tr('Add constraints while drawing'));auto.setChecked(self.auto_constraints_enabled())
        auto.setToolTip(tr('Joins end points that land on other geometry and makes near-horizontal or vertical lines exact.'))
        auto.toggled.connect(self.set_auto_constraints);form.addRow(auto);self.widgets['auto_constraints']=auto

        if self.workspace.tool in ('fillet','chamfer'):
            corner_form=self.form('Fillet' if self.workspace.tool=='fillet' else 'Chamfer')
            label='Fillet radius' if self.workspace.tool=='fillet' else 'Chamfer distance'
            self.spin(corner_form,'sketch_corner_size',label,getattr(self,'sketch_corner_size',1.),lambda v:setattr(self,'sketch_corner_size',v),True)
            count=len(getattr(self,'sketch_corners',[]))
            self.note('Click the corners where sketch curves meet to select them (click again to deselect). '
                      'Drag the arrow or type a size, then apply. The outline shows the real result; sizes above the largest possible are not offered.')
            self.note(f'{count} '+('corner selected' if count==1 else 'corners selected'))
            self.button('Apply fillet' if self.workspace.tool=='fillet' else 'Apply chamfer',self.apply_sketch_corners,True).setEnabled(count>0)
            self.button('Clear selection',self.clear_sketch_corners).setEnabled(count>0)
            return

        listing=QListWidget();listing.setMaximumHeight(90 if pattern else 140)
        listing.addItems([f'{i+1}. {tr(e["kind"].title())}'+(' · '+tr('guide') if e.get('construction') else '') for i,e in enumerate(self.draft['entities'])])
        if self.entity_index is not None:listing.setCurrentRow(self.entity_index)
        if self.workspace.tool in Workspace.SELECTION_TOOLS:
            listing.setSelectionMode(QAbstractItemView.MultiSelection)
            for i in self.workspace.pattern_selection:
                if 0<=i<listing.count():listing.item(i).setSelected(True)
            listing.itemSelectionChanged.connect(lambda:self.pattern_list_selection(listing))
        else:
            listing.itemClicked.connect(lambda item:self.select_entity(listing.row(item)))
            listing.itemActivated.connect(lambda item:self.select_entity(listing.row(item)))
        group=CollapsibleSection(tr('Geometry list'),listing,self.expanded_sections.get('Geometry list',False),lambda on:self.expanded_sections.update({'Geometry list':on}));self.editor_layout.addWidget(group)
        if self.entity_index is not None:self.note(f'Editing {self.draft["entities"][self.entity_index]["kind"]} {self.entity_index+1}')
        elif not pattern and self.workspace.tool!='polygon':self.note({'select':'Click sketch geometry to edit its dimensions. Use L / R / C / A to draw.', 'trim':'Click edges to trim between intersections.',
            'polygon':f'Click the center, then a vertex to place a {self.workspace.polygon_sides}-sided polygon.',
            'ellipse':'Click center, major-axis point, then minor radius.', 'slot':'Click both slot centers, then set the width.',
            'spline':'Click points; click the first point to close the spline, or press Enter for an open curve.', 'conic':'Click start, end, then the control point.',
            'point':'Click once to place a sketch reference point.', 'text':'Drag a rectangle for the text box. Its text, font, size and alignment are set here afterwards.',
            'center_rectangle':'Click the center, then a corner.', 'rectangle_3p':'Click two points for the first edge, then a third point for width.',
            'circle_3p':'Click three points on the circle.', 'center_arc':'Click center, start, then end direction.'}.get(self.workspace.tool,'Click to draw, or type a size after placing the first point. Tab switches dimensions.'))
        tool=self.workspace.tool
        if tool=='select' and self.entity_index is None and self.workspace.pattern_selection:
            count=len(self.workspace.pattern_selection)
            self.note(f'<b>{count} '+tr('sketch entities selected')+'</b><br>'+tr('Delete removes them; Shift+drag adds more, Ctrl+Shift+drag removes.'))
            self.button('Delete selected geometry',self.delete_entity)
            self.button('Toggle construction guide',self.toggle_selected_construction)
            self.button('Clear selection',lambda:(self.workspace.pattern_selection.clear(),self.workspace.update(),self.show_editor()))
        if tool=='polygon' and self.entity_index is None:
            self.polygon_settings();return
        if tool in ('offset','transform'):
            self.modify_editor();return
        if tool in ('mirror','circular','rectangular'):
            self.pattern_editor();return
        if self.precise_draft is None:
            if self.entity_index is not None:self.precise_draft=copy.deepcopy(self.draft['entities'][self.entity_index])
            elif tool=='rectangle':self.precise_draft=entity('rectangle',center=[0.,0.],width=20.,height=15.)
            elif tool=='circle':self.precise_draft=entity('circle',center=[0.,0.],radius=5.)
            elif tool=='line':self.precise_draft=entity('line',a=[0.,0.],b=[20.,0.])
            elif tool=='arc':self.precise_draft=entity('arc',a=[-10.,0.],mid=[0.,10.],b=[10.,0.])
            elif tool=='polygon':self.precise_draft=entity('polygon',points=[[10.,0.],[5.,8.6603],[-5.,8.6603],[-10.,0.],[-5.,-8.6603],[5.,-8.6603]])
            elif tool=='ellipse':self.precise_draft=entity('ellipse',center=[0.,0.],major=[10.,0.],minor_radius=5.)
            elif tool=='slot':self.precise_draft=entity('slot',a=[-10.,0.],b=[10.,0.],width=6.)
            elif tool=='spline':self.precise_draft=entity('spline',basis='bspline',points=[[-10.,0.],[0.,7.],[10.,0.]])
            elif tool=='conic':self.precise_draft=entity('conic',a=[-10.,0.],control=[0.,8.],b=[10.,0.])
            elif tool=='point':self.precise_draft=entity('point',p=[0.,0.])
            if self.precise_draft is not None and self.entity_index is None and self.workspace.construction_mode:self.precise_draft['construction']=True
            self.precise_baseline=copy.deepcopy(self.precise_draft)
        e=self.precise_draft
        if e:
            ef=self.form('Precise input',collapsed=self.entity_index is None)
            guide=QCheckBox(tr('Construction guide'));guide.setChecked(e.get('construction',False));guide.toggled.connect(lambda v:e.update(construction=v));ef.addRow(guide)
            if e['kind']=='polygon':
                for i,point in enumerate(e['points']):
                    for j,axis in enumerate(('X','Y')):
                        self.spin(ef,f'point_{i}_{j}',f'Corner {i+1} {axis}',point[j],lambda v,k=i,d=j:e['points'][k].__setitem__(d,v))
            elif e['kind'] in ('rectangle','circle'):
                self.point_fields(ef,e,'center','Center')
                if e['kind']=='rectangle':
                    self.spin(ef,'width','Width',e['width'],lambda v:e.update(width=v),True)
                    self.spin(ef,'height','Height',e['height'],lambda v:e.update(height=v),True)
                else:self.spin(ef,'radius','Radius',e['radius'],lambda v:e.update(radius=v),True)
            elif e['kind']=='ellipse':
                self.point_fields(ef,e,'center','Center');self.point_fields(ef,e,'major','Major axis point');self.spin(ef,'minor_radius','Minor radius',e['minor_radius'],lambda v:e.update(minor_radius=v),True)
            elif e['kind']=='slot':
                self.point_fields(ef,e,'a','First center');self.point_fields(ef,e,'b','Second center');self.spin(ef,'width','Width',e['width'],lambda v:e.update(width=v),True)
            elif e['kind']=='spline':
                degree=QSpinBox();degree.setRange(1,min(25,len(e['points'])-1));degree.setValue(e.get('degree',min(3,len(e['points'])-1)));degree.setEnabled('knots' not in e);degree.valueChanged.connect(lambda value:e.update(degree=value));ef.addRow(tr('Spline degree'),degree);self.widgets['degree']=degree
                self.combo(ef,'basis','Spline type',['catmull','bspline'],e.get('basis','catmull'),lambda v:e.update(basis=v))
                closed=QCheckBox(tr('Closed curve'));closed.setChecked(e.get('closed',False));closed.setEnabled('knots' not in e);closed.toggled.connect(lambda on:e.update(closed=on));ef.addRow(closed)
                for i,point in enumerate(e['points']):
                    for j,axis in enumerate(('X','Y')):self.spin(ef,f'spline_{i}_{j}',f'Control {i+1} {axis}',point[j],lambda v,k=i,d=j:e['points'][k].__setitem__(d,v))
                    if e.get('weights'):self.spin(ef,f'weight_{i}',f'Weight {i+1}',e['weights'][i],lambda v,k=i:e['weights'].__setitem__(k,v),True)
            elif e['kind']=='conic':
                self.spin(ef,'weight','Conic weight',e.get('weight',1),lambda v:e.update(weight=v),True)
                for key,label in [('a','Start'),('control','Control'),('b','End')]:self.point_fields(ef,e,key,label)
            elif e['kind']=='point':self.point_fields(ef,e,'p','Point')
            else:
                for key,label in [('a','Start'),('mid','Through'),('b','End')]:
                    if key in e:self.point_fields(ef,e,key,label)
            button=self.button('Apply geometry edit' if self.entity_index is not None else 'Add geometry',self.apply_entity,True)
            self.editor_layout.removeWidget(button);ef.addRow(button)
        if self.entity_index is not None:self.button('Delete selected geometry',self.delete_entity)

    def point_fields(self,form,e,key,label):
        for axis,i in [('X',0),('Y',1)]:
            self.spin(form,f'{key}_{axis.lower()}',f'{label} {axis}',e[key][i],lambda v,k=key,j=i:e[k].__setitem__(j,v))
    def set_grid(self,value):self.workspace.grid=value;self.workspace.update()

    def edge_limit_text(self,kind,count):
        noun='fillet radius' if kind=='fillet' else 'chamfer distance'
        if count==0:return 'Maximum for selected edges: select one or more edges first.'
        if self.edge_size_limit is None and getattr(self,'edge_limit_pending',None) is not None:return 'Maximum for selected edges: calculating…'
        if self.edge_size_limit is None:return 'Maximum for selected edges: click Find maximum size to check.'
        if self.edge_size_limit<=0:return f'Maximum {noun}: no valid positive size found for this selection.'
        value=float(self.edge_size_limit);order=math.floor(math.log10(value)) if value>0 else 0
        decimals=max(0,min(8,4-order));scale=10.0**decimals;shown=math.floor(value*scale+1e-12)/scale
        number_text=f'{shown:.{decimals}f}'.rstrip('0').rstrip('.') if decimals else f'{shown:.0f}'
        prefix='≈ ' if self.edge_size_limit_bounded else '≥ '
        return f'Maximum {noun} for selected edges: {prefix}{number_text} mm'

    def feature_action_row(self,feature):
        """Primary feature actions stay at the top so Apply never requires scrolling."""
        bar=QWidget();bar.setObjectName('featureActions');layout=QHBoxLayout(bar);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        apply_button=QPushButton(tr('Apply extrusion' if feature['kind']=='extrude' else 'Apply feature'));apply_button.setObjectName('primary');apply_button.clicked.connect(self.apply_feature)
        preview_button=QPushButton(tr('Preview'));preview_button.clicked.connect(self.preview_feature)
        cancel_button=QPushButton(tr('Cancel'));cancel_button.clicked.connect(self.cancel)
        layout.addWidget(apply_button,2);layout.addWidget(preview_button,1);layout.addWidget(cancel_button,1)
        self.editor_layout.addWidget(bar)
        need=missing_inputs(feature)
        if need:
            # Like Fusion's OK button: unavailable until the required selections are made, with the reason.
            apply_button.setEnabled(False);preview_button.setEnabled(False)
            hint=QLabel(tr('Still needed:')+' '+', '.join(tr(n) for n in need));hint.setWordWrap(True);hint.setObjectName('missingHint')
            hint.setStyleSheet('color:#c7782a;');self.editor_layout.addWidget(hint);self.widgets['missing_hint']=hint
        steps=STEPS.get(feature.get('kind'))
        if steps:
            line=QLabel(tr(steps));line.setWordWrap(True);line.setObjectName('subtle');self.editor_layout.addWidget(line);self.widgets['tool_steps']=line
        self.render_slots(feature)
        if feature['kind'] in SPATIAL_TOOLS+ASSEMBLY_TOOLS+ADVANCED_TOOLS+BODY_TOOLS+CONSTRUCTIONS+SOLID_TOOLS+('import_solid','sketch_move'):
            active=QCheckBox(tr('Active'));active.setChecked(feature.get('enabled',True));active.toggled.connect(lambda value:self.parameter_changed(lambda on:feature.update(enabled=on),value));self.editor_layout.addWidget(active);self.widgets['enabled']=active
        if feature['kind'] not in self.LIVE_PREVIEW_SKIP:
            live=QCheckBox(tr('Live preview'));live.setChecked(self.live_preview)
            live.setToolTip(tr('Update the preview automatically after each change.'))
            live.toggled.connect(self.set_live_preview);self.editor_layout.addWidget(live);self.widgets['live_preview']=live
        self.preview_label=QLabel(tr('Preview active · Apply to keep it' if self.preview_active else 'Apply is always available here; Preview is optional.'))
        self.preview_label.setWordWrap(True);self.preview_label.setObjectName('subtle');self.editor_layout.addWidget(self.preview_label)
        return preview_button,apply_button

    def set_live_preview(self,on):
        self.live_preview=bool(on)
        if on:self.schedule_live_preview()

    def compact_button_row(self,items):
        row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        buttons=[]
        for label,fn in items:
            button=QPushButton(tr(label));button.clicked.connect(fn);layout.addWidget(button);buttons.append(button)
        return row,buttons

    def feature_editor(self):
        self.feature_editor_panel()
        self.highlight_references()

    def feature_editor_panel(self):
        f=self.draft
        if f['kind']=='sketch_move':self.sketch_move_editor();return
        if f['kind'] in SPATIAL_TOOLS:self.spatial_editor();return
        if f['kind'] in ASSEMBLY_TOOLS:self.assembly_editor();return
        if f['kind'] in ADVANCED_TOOLS:self.advanced_editor();return
        if f['kind']=='import_solid':self.imported_feature_editor();return
        if f['kind'] in BODY_TOOLS:self.body_feature_editor();return
        if f['kind'] in CONSTRUCTIONS+SOLID_TOOLS:self.solid_feature_editor();return
        preview_button,apply_button=self.feature_action_row(f)
        if f['kind']=='extrude':
            form=self.form('Extrude')
            self.spin(form,'depth','Distance',f['depth'],lambda v:self.set_extrusion_depth(f,v))
            reverse=QCheckBox(tr('Reverse direction'));reverse.setChecked(float(f['depth'])<0)
            reverse.setToolTip(tr('Extrude to the other side of the sketch plane or face.'))
            def flip(on):
                box=self.widgets['depth'];value=abs(box.value());box.setValue(-value if on else value)
            reverse.toggled.connect(flip);form.addRow(reverse);self.widgets['reverse']=reverse
            self.combo(form,'operation','Operation',['auto','add','cut','intersect'],f.get('operation','add'),lambda v:f.update(operation=v))
            modern='source' in f or 'sources' in f
            if modern:
                try:sources=extrusion_sources(f)
                except ModelError:sources=[]
                count=len(sources);faces=sum(source.get('type')=='face' for source in sources);profiles=count-faces
                status=QLabel(f'<b>{count} {tr("source" if count==1 else "sources")} {tr("selected")}</b> · {faces} {tr("face")} · {profiles} {tr("profile")}')
                status.setWordWrap(True);form.addRow('Selection',status)
                if self.draft_index is None:
                    row,buttons=self.compact_button_row([('Select sources',lambda:self.set_extrude_selection_active(True)),('Clear',self.clear_extrusion_sources)])
                    buttons[0].clicked.disconnect();buttons[0].setCheckable(True);buttons[0].setChecked(self.workspace.extrude_selecting)
                    buttons[0].toggled.connect(self.set_extrude_selection_active)
                    buttons[1].setEnabled(count>0);form.addRow(row)
                    every=QPushButton(tr('Select all profiles'));every.setToolTip(tr('Adds every closed profile of the visible sketches.'));every.clicked.connect(self.select_all_profiles)
                    self.widgets['select_all_profiles']=every;form.addRow(every)
                    drag=QCheckBox(tr('Drag selects a box'));drag.setChecked(self.workspace.drag_selects)
                    drag.setToolTip(tr('Off: Shift+drag draws the selection box and plain drag orbits. On: plain drag draws the box.'))
                    drag.toggled.connect(lambda on:setattr(self.workspace,'drag_selects',bool(on)));self.widgets['drag_selects']=drag;form.addRow(drag)
                    hint=QLabel('Click profiles or faces to add or remove them. Shift+drag draws a selection box: left to right selects what is fully inside, right to left what it touches; Ctrl+Shift removes.');hint.setWordWrap(True);hint.setObjectName('subtle');form.addRow('',hint)
                advanced=self.form('Direction & details',collapsed=True)
                self.name_field(advanced,f)
                enabled=QCheckBox(tr('Active'));enabled.setChecked(f.get('enabled',True));enabled.toggled.connect(lambda v:self.parameter_changed(lambda value:f.update(enabled=value),v));advanced.addRow(enabled)
                self.combo(form,'direction','Direction',['one side','symmetric','two sides'],f.get('direction','one side'),lambda v:self.change_extrusion_direction(v))
                if f.get('direction')=='two sides':
                    f.setdefault('depth2',f['depth'])
                    self.spin(form,'depth2','Second distance',f['depth2'],lambda v:f.update(depth2=v))
                self.spin(advanced,'offset','Start offset',f.get('offset',0),lambda v:f.update(offset=v))
                self.combo(form,'extent','Extent',['distance','through all','to object'],f.get('extent','distance'),lambda v:self.change_extrusion_extent(v))
                self.spin(form,'taper','Taper angle',f.get('taper',0),lambda v:f.update(taper=v))
                thin=QCheckBox(tr('Thin wall'));thin.setChecked(bool(f.get('thin')));thin.setToolTip(tr('Extrude only a wall of the given thickness along the outline instead of the whole profile.'))
                thin.toggled.connect(self.toggle_thin_wall);form.addRow(thin);self.widgets['thin_toggle']=thin
                if f.get('thin'):
                    self.spin(form,'thin','Wall thickness',f['thin'],lambda v:f.update(thin=v),True)
                    side=QComboBox()
                    for label,value in [('Inside the outline','inside'),('Outside the outline','outside'),('Centered on the outline','centered')]:side.addItem(tr(label),value)
                    side.setCurrentIndex(max(0,side.findData(f.get('thin_side','inside'))))
                    side.currentIndexChanged.connect(lambda i:self.parameter_changed(lambda value:f.update(thin_side=value),side.itemData(i)));form.addRow(tr('Wall position'),side);self.widgets['thin_side']=side
                if f.get('extent')=='to object':
                    self.reference_combo(form,'target','Target',self.plane_choices(),f.get('target'),lambda value:f.update(target=value))
                    self.button('Pick target face',lambda:self.enable_face_pick('target'))
                auto_hint=QLabel('Auto checks overlap when applying and asks Join or Cut when needed.');auto_hint.setWordWrap(True);auto_hint.setObjectName('subtle');advanced.addRow('',auto_hint)
            else:
                advanced=self.form('Legacy extrusion details',collapsed=True);self.name_field(advanced,f)
                enabled=QCheckBox(tr('Active'));enabled.setChecked(f.get('enabled',True));enabled.toggled.connect(lambda v:self.parameter_changed(lambda value:f.update(enabled=value),v));advanced.addRow(enabled)
                for key,label in [('x','Origin X'),('y','Origin Y'),('z','Origin Z'),('width','Width'),('height','Height'),('radius','Radius')]:
                    if key in f:self.spin(advanced,key,label,f[key],lambda v,k=key:f.__setitem__(k,v),key in ('width','height','radius'))
        else:
            form=self.form('Fillet' if f['kind']=='fillet' else 'Chamfer')
            label='Fillet radius' if f['kind']=='fillet' else 'Chamfer distance'
            self.spin(form,'radius',label,f['radius'],lambda v:f.update(radius=v),True)
            from model import EDGE_MODES
            modes=EDGE_MODES[f['kind']];current=f.get('mode',modes[0])
            mode_box=QComboBox()
            for value in modes:mode_box.addItem(tr(self.EDGE_MODE_LABELS[value]),value)
            mode_box.setCurrentIndex(max(0,mode_box.findData(current)))
            mode_box.currentIndexChanged.connect(lambda i:self.change_edge_mode(mode_box.itemData(i)));form.addRow(tr('Type'),mode_box);self.widgets['edge_mode']=mode_box
            if current=='two_distance':
                f.setdefault('distance2',f['radius']);self.spin(form,'distance2','Second distance',f['distance2'],lambda v:f.update(distance2=v),True)
            elif current=='distance_angle':
                f.setdefault('angle',45.);self.spin(form,'angle','Angle',f['angle'],lambda v:f.update(angle=v),True)
            elif current=='variable':
                f.setdefault('radius_end',f['radius']);self.spin(form,'radius_end','End radius',f['radius_end'],lambda v:f.update(radius_end=v),True)
            if current in ('two_distance','distance_angle'):
                flip=QCheckBox(tr('Swap the two faces'));flip.setChecked(bool(f.get('flip',False)))
                flip.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(flip=value),bool(on)));form.addRow(flip);self.widgets['flip']=flip
            count=len(f.get('edge_refs',[])) if f.get('edge_refs') is not None else 0
            limit_hint=QLabel(self.edge_limit_text(f['kind'],count));limit_hint.setWordWrap(True);limit_hint.setObjectName('subtle')
            form.addRow('',limit_hint);self.widgets['edge_limit_hint']=limit_hint
            if count and self.edge_size_limit is None:
                find=QPushButton(tr('Find maximum size'));find.setToolTip(tr('Tests trial sizes with the CAD kernel; this can take a few seconds.'))
                find.clicked.connect(lambda:(self.calculate_edge_size_limit(),self.show_editor()));form.addRow('',find)
            if f.get('edge_refs') is not None:
                row,buttons=self.compact_button_row([('Select all edges',self.workspace.select_all_edges),('Clear selection',self.workspace.clear_edge_selection)])
                form.addRow(row)
                status=QLabel(f'<b>{count} {tr("edge")} {tr("selected")}</b> · '+tr('click model edges to toggle selection; click a vertex to select its incident edges'))
                status.setWordWrap(True);form.addRow('Selection',status)
                chain=QCheckBox(tr('Tangent chain'));chain.setChecked(self.workspace.edge_tangent_chain)
                chain.setToolTip(tr('Clicking an edge also selects the edges joined to it smoothly, as in Fusion. Rounded outlines need the whole chain.'))
                chain.toggled.connect(lambda on:setattr(self.workspace,'edge_tangent_chain',bool(on)));form.addRow('',chain)
                fit=QCheckBox(tr('Fit size automatically'));fit.setChecked(f.get('auto_fit',True))
                fit.setToolTip(tr('If the size is too large for some edges, those edges get the largest size that fits instead of the feature failing.'))
                fit.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(auto_fit=value),bool(on)));form.addRow('',fit);self.widgets['auto_fit']=fit
                note=self.edge_fit_note(f) if self.draft_index is not None else ''
                if note:
                    fit_note=QLabel(note);fit_note.setWordWrap(True);fit_note.setObjectName('subtle');form.addRow('',fit_note)
            else:
                self.combo(form,'edges','Edges',['vertical','top','bottom','all'],f.get('edges','vertical'),lambda v:f.update(edges=v))
            advanced=self.form('Feature details',collapsed=True);self.name_field(advanced,f)
            enabled=QCheckBox(tr('Active'));enabled.setChecked(f.get('enabled',True));enabled.toggled.connect(lambda v:self.parameter_changed(lambda value:f.update(enabled=value),v));advanced.addRow(enabled)
        if f['kind']=='extrude' and ('source' in f or 'sources' in f):
            try:has_sources=bool(extrusion_sources(f))
            except ModelError:has_sources=False
            preview_button.setEnabled(has_sources);apply_button.setEnabled(has_sources)

    def change_extrusion_extent(self,value):
        self.draft['extent']=value;self.show_editor()

    def change_extrusion_direction(self,value):
        self.draft['direction']=value
        if value=='two sides' and self.draft.get('extent','distance')!='distance':self.draft['extent']='distance'
        self.show_editor()

    def toggle_thin_wall(self,on):
        f=self.draft
        if on:f['thin']=f.get('thin') or 2.0
        else:
            for name in ('thin','expressions','expression_values'):
                table=f.get(name)
                if name=='thin':f.pop('thin',None)
                elif isinstance(table,dict):
                    table.pop('thin',None)
                    if not table:f.pop(name,None)
        self.invalidate_preview();self.show_editor()

    EDGE_MODE_LABELS={'equal':'Equal distance','two_distance':'Two distances','distance_angle':'Distance and angle','constant':'Constant radius','variable':'Variable radius'}

    def change_edge_mode(self,value):
        f=self.draft;f['mode']=value
        f.setdefault('distance2',f.get('radius',1.));f.setdefault('angle',45.);f.setdefault('radius_end',f.get('radius',1.))
        self.edge_size_limit=None;self.edge_size_limit_bounded=True;self.invalidate_preview();self.show_editor()

    def import_step_file(self):
        self.ensure_session();super().import_step_file()
    def import_dxf_file(self):
        self.ensure_session();super().import_dxf_file()
    def blank(self):
        # A new project opens in its own tab (an untouched blank one is simply reused).
        if not self.begin_new_project(replace_pristine=False):return
        self.stack.setCurrentWidget(self.workspace);self.set_project_chrome(True)
        self.workspace.set_mode('support');self.refresh(True);self.show_editor();self.update_title()
    def open(self):
        filename,_=QFileDialog.getOpenFileName(self,tr('Open project'),'',tr('SlothCAD projects (*.fcad)'))
        if not filename:return
        self.load(filename)
    def load(self,path):
        try:
            path=Path(path).resolve()
            for session in self.sessions:
                other=session['path'] if session['id']!=self.session_id else self.path
                if other is not None and Path(other).resolve()==path:
                    self.tabs.setCurrentIndex(self.tab_index(session['id']));return
            doc=self.run_busy('Opening project…',lambda report:Document.load(path,progress=report))
            if not self.begin_new_project():return
            self.component_stack=[];self.doc=doc;self.path=path;self.saved_features=copy.deepcopy(doc.features);self.saved_display=copy.deepcopy(doc.display);self.selected=None;self.draft=None
            self.stack.setCurrentWidget(self.workspace);self.set_project_chrome(True)
            self.workspace.set_mode('model');self.refresh(True);self.report_build_error();self.remember_recent(path);self.update_title()
        except Exception as e:self.error(e)
    def report_build_error(self):
        """Explain a project that opened with a failing feature, and offer Repair."""
        error=getattr(self.doc,'build_error',None)
        if error is None:return
        index=getattr(error,'feature_index',0)
        box=QMessageBox(self);box.setIcon(QMessageBox.Warning);box.setWindowTitle(tr('Project opened with an error'))
        box.setText(tr(str(error)))
        box.setInformativeText(tr('The model is shown up to the last working feature')+f' ({index}). '+tr('Edit, suppress or repair the failing feature; later features are kept but not built until it works.'))
        repair=box.addButton(tr('Inspect / Repair references'),QMessageBox.ActionRole);box.addButton(QMessageBox.Close);box.exec()
        if box.clickedButton()==repair:self.open_reference_recovery()
    def save(self,save_as=False):
        if self.has_draft():self.error('Finish your sketch or Apply / Cancel current feature changes before saving.');return False
        path=self.component_stack[0]['path'] if getattr(self,'component_stack',[]) else self.path
        if save_as or path is None:
            filename,_=QFileDialog.getSaveFileName(self,tr('Save project'),str(path or 'Untitled.fcad'),tr('SlothCAD projects (*.fcad)'))
            if not filename:return False
            path=Path(filename if filename.lower().endswith('.fcad') else filename+'.fcad')
        if getattr(self,'component_stack',[]):
            try:return self.save_assembly(path)
            except Exception as error:self.error(error);return False
        try:
            self.doc.save(path);self.path=path;self.saved_features=copy.deepcopy(self.doc.features);self.saved_display=copy.deepcopy(self.doc.display);self.remember_recent(path)
            self.save_thumbnail(path);self.update_title();return True
        except Exception as e:self.error(e);return False
    def export_step(self):self.export_format('step')
    def export_stl(self):self.export_format('stl')
    def export_format(self,format_):
        if self.has_draft():self.error('Finish your sketch or Apply / Cancel current changes before exporting.');return
        suffix={'step':'step','stl':'stl','3mf':'3mf','glb':'glb'}[format_]
        filter_={'step':tr('STEP solid (*.step *.stp)'),'stl':tr('STL mesh (*.stl)'),'3mf':tr('3MF model (*.3mf)'),'glb':tr('glTF binary (*.glb)')}[suffix]
        filename,_=QFileDialog.getSaveFileName(self,tr('Export '+suffix.upper()),'part.'+suffix,filter_)
        if not filename:return
        suffixes=('.step','.stp') if suffix=='step' else ('.'+suffix,)
        if Path(filename).suffix.lower() not in suffixes:filename+='.'+suffix
        tolerance,angular,visible_only=self.export_preferences()
        try:
            from exchange import export_kind
            from kernel_process import KERNEL,item_bytes
            export_kind(filename,tolerance,angular)
            # Writing the file runs in the kernel process: a long kernel call there cannot freeze the window.
            def work(report):
                report(0,0,'Preparing export…')
                items=item_bytes(self.doc.export_items(visible_only))
                KERNEL.call('export',dict(items=items,path=str(filename),label=suffix.upper(),tolerance=tolerance,angular_tolerance=angular),report)
            self.run_busy('Exporting '+suffix.upper()+'…',work);self.show_status(f'Exported {filename}')
        except Exception as e:self.error(e)
    def example(self):
        try:
            doc=self.run_busy('Opening example…',lambda report:Document.load(Path(__file__).parent/'examples'/'face_sketch_demo.fcad',progress=report))
            if not self.begin_new_project():return
            self.component_stack=[];self.doc=doc;self.path=None;self.saved_features=[];self.saved_display={};self.selected=None
            self.stack.setCurrentWidget(self.workspace);self.set_project_chrome(True)
            self.workspace.set_mode('model');self.refresh(True);self.update_title()
        except Exception as e:self.error(e)
    # ---- updates from GitHub
    def check_for_update(self):
        """Ask GitHub for a newer version in the background; a button appears when there is one."""
        import updater
        if not updater.enabled():return
        signals=self._update_signals=_LimitSignals(self);signals.done.connect(self.update_found)
        threading.Thread(target=lambda:signals.done.emit(updater.newer_version(VERSION)),name='SlothCAD-update-check',daemon=True).start()

    def update_found(self,version):
        if not version:return
        self.update_version=version
        button=getattr(self,'update_button',None)
        if button is None:
            button=self.update_button=QToolButton();button.setObjectName('updateButton');button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor);button.clicked.connect(self.install_update)
            button.setStyleSheet('QToolButton#updateButton{background:palette(highlight);color:palette(highlighted-text);border:none;border-radius:4px;padding:1px 10px;font-weight:600;}')
            self.tab_row_layout.addWidget(button)
        button.setText(tr('Update available')+f' · {version}')
        button.setToolTip(tr('SlothCAD {new} is available (you have {old}). Click to install it and restart.').format(new=version,old=VERSION))
        button.show()

    def install_update(self):
        import updater
        version=getattr(self,'update_version','')
        answer=QMessageBox.question(self,tr('Update SlothCAD'),tr('Install SlothCAD {new} now? The changed files are downloaded from GitHub and SlothCAD restarts. You are asked to save unsaved projects first.').format(new=version))
        if answer!=QMessageBox.Yes:return
        try:count=self.run_busy('Downloading update…',updater.install)
        except Exception as error:
            self.error(error);return
        if not count:
            self.update_button.hide();self.show_status(tr('SlothCAD is already up to date.'),6000);return
        project=self.path
        if self.close():updater.restart(project)
        else:QMessageBox.information(self,tr('Update SlothCAD'),tr('The update is installed. It takes effect the next time SlothCAD starts.'))

    def closeEvent(self,event):
        if self.loading:
            self.show_status('A CAD operation is still finishing; the window is responsive and will be ready shortly.')
            event.ignore();return
        if self.confirm_close_all():self.stop_spacemouse();self.autosave.cleanup();event.accept()
        else:event.ignore()

def main():
    import platform_support
    if QApplication.instance() is None:
        from PySide6.QtGui import QSurfaceFormat
        from gpu_renderer import surface_format
        QSurfaceFormat.setDefaultFormat(surface_format())
        platform_support.prepare_process()
    QApplication.setAttribute(Qt.AA_CompressHighFrequencyEvents,True)
    app=QApplication.instance() or QApplication(sys.argv);app.setApplicationName('SlothCAD');app.setDesktopFileName('slothcad');app.setStyle('Fusion');apply_theme(app,load_theme())
    if platform_support.app_icon_path():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(platform_support.app_icon_path())))
    splash.step('Building the workspace…')
    window=Window(start_with_project=False)
    if len(sys.argv)>1:window.load(sys.argv[1])
    splash.step('Almost ready…')
    window.show();splash.finish(window);QTimer.singleShot(0,lambda:window.recover_autosave(startup=True))
    QTimer.singleShot(3000,window.check_for_update);sys.exit(app.exec())
if __name__=='__main__':main()
