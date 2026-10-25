"""Sketch text tool: draw a text box, then format it in the right-hand panel.

The flow follows a word processor: drag a rectangle (the text box), then set the text,
font, size, bold / italic / underline, horizontal and vertical alignment and line spacing.
The workspace shows a live outline of the result inside the box; "Place text" turns it
into ordinary closed polygons in the sketch.
"""
import copy
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QFontComboBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QToolButton, QWidget)

from i18n import tr
from legacy_model import ModelError


def alignment_icon(kind, color):
    """Small pictogram like the alignment buttons of a document writer."""
    pixmap = QPixmap(26, 26)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(QPen(QColor(color), 2))
    if kind in ('left', 'center', 'right', 'justify'):
        widths = [20, 13, 20, 9, 16] if kind != 'justify' else [20, 20, 20, 20, 14]
        for row, width in enumerate(widths):
            y = 4 + row * 4
            if kind in ('left', 'justify'):
                x = 3
            elif kind == 'center':
                x = 3 + (20 - width) // 2
            else:
                x = 3 + 20 - width
            p.drawLine(x, y, x + width, y)
    else:
        # Vertical alignment: a frame edge and a block of text pinned to it.
        p.setPen(QPen(QColor(color), 1))
        p.drawLine(2, 2, 24, 2)
        p.drawLine(2, 23, 24, 23)
        p.setPen(QPen(QColor(color), 2))
        top = {'top': 4, 'middle': 9, 'bottom': 14}[kind]
        for row in range(3):
            y = top + row * 3
            p.drawLine(6, y, 20 if row != 1 else 15, y)
    p.end()
    return QIcon(pixmap)


class TextUI:
    text_draft = None     # {'rect': [x0, y0, x1, y1], 'style': TextStyle fields}
    text_style = None     # the last style used, offered for the next box

    # ---- state ---------------------------------------------------------------------------
    def clear_text_draft(self):
        self.text_draft = None
        self.workspace.text_box = None

    def begin_text_box(self, rect):
        from text_tool import TextStyle, with_defaults
        style = with_defaults(self.text_style or TextStyle())
        self.text_draft = {'rect': [float(v) for v in rect], 'style': style.to_dict()}
        self.text_info = None
        self.text_refresh()
        self.show_editor()

    def text_style_now(self):
        from text_tool import TextStyle
        return TextStyle.from_dict(self.text_draft['style'])

    def text_refresh(self):
        """Lay the text out again and hand the outline to the viewport (cheap: a few ms)."""
        draft = self.text_draft
        if draft is None:
            self.workspace.text_box = None
            return
        from text_tool import layout_text
        try:
            layout = layout_text(self.text_style_now(), draft['rect'])
            self.text_info = layout
            self.workspace.text_box = dict(rect=list(draft['rect']), loops=layout.loops,
                                           overflow=layout.overflow_x or layout.overflow_y)
        except Exception as error:
            self.text_info = None
            self.workspace.text_box = dict(rect=list(draft['rect']), loops=[], overflow=True)
            self.show_status(tr(str(error)))
        self.text_readout()
        self.workspace.update()

    def text_readout(self):
        label = self.widgets.get('text_readout') if hasattr(self, 'widgets') else None
        if label is None:
            return
        info = getattr(self, 'text_info', None)
        style = self.text_style_now() if self.text_draft else None
        if info is None or style is None:
            label.setText('')
            return
        x0, y0, x1, y1 = self.text_draft['rect']
        parts = [f'{tr("Text")}: {info.width:.2f} × {info.height:.2f} mm',
                 f'{info.lines} ' + tr('line' if info.lines == 1 else 'lines'),
                 f'{style.size_pt:g} pt = {style.size_mm:.2f} mm',
                 f'{tr("Box")}: {abs(x1 - x0):.2f} × {abs(y1 - y0):.2f} mm']
        warning = []
        if info.overflow_x:
            warning.append(tr('The text is wider than the box.'))
        if info.overflow_y:
            warning.append(tr('The text is taller than the box.'))
        label.setText(' · '.join(parts) + (('\n⚠ ' + ' '.join(warning)) if warning else ''))
        label.setStyleSheet('color:#c45c62;' if warning else '')

    def text_set(self, **values):
        """Change style fields, remember them for the next box and refresh the preview."""
        if self.text_draft is None:
            return
        self.text_draft['style'].update(values)
        self.text_style = self.text_style_now()
        self.text_refresh()

    def text_set_rect(self, rect):
        if self.text_draft is None:
            return
        self.text_draft['rect'] = [float(v) for v in rect]
        self.text_refresh()

    # ---- panel ---------------------------------------------------------------------------
    def text_editor(self):
        d = self.text_draft
        style = self.text_style_now()
        self.note('Type the text, choose the font and alignment; the outline in the workspace shows how it will look. '
                  'Place text (Ctrl+Enter) adds it to the sketch as closed outlines.')
        # The actions stay at the top so they are never scrolled out of sight.
        self.button('Place text', self.apply_text, True)
        self.button('Cancel text', self.cancel_text)

        form = self.form('Text')
        edit = QPlainTextEdit(style.text)
        edit.setMinimumHeight(70)
        edit.setMaximumHeight(150)
        edit.setPlaceholderText(tr('Text'))
        edit.textChanged.connect(lambda: self.text_set(text=edit.toPlainText()))
        QShortcut(QKeySequence('Ctrl+Return'), edit, activated=self.apply_text)
        QShortcut(QKeySequence('Ctrl+Enter'), edit, activated=self.apply_text)
        self.widgets['text_content'] = edit
        form.addRow(edit)

        # The format bar of a document writer, split into rows that fit a narrow side panel:
        # font family / size with bold, italic, underline / horizontal / vertical alignment.
        def row_of(*widgets, stretch=True):
            holder = QWidget()
            box = QHBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            for item in widgets:
                box.addWidget(item)
            if stretch:
                box.addStretch(1)
            return holder

        families = QFontComboBox()
        families.setCurrentFont(QFont(style.font))
        families.setSizeAdjustPolicy(QFontComboBox.AdjustToMinimumContentsLengthWithIcon)
        families.setMinimumContentsLength(10)
        families.setMinimumWidth(60)
        families.currentFontChanged.connect(lambda font: self.text_set(font=font.family()))
        self.widgets['text_font'] = families
        form.addRow(families)

        size = QDoubleSpinBox()
        size.setDecimals(1)
        size.setRange(1., 2000.)
        size.setSingleStep(1.)
        size.setSuffix(' pt')
        size.setValue(style.size_pt)
        size.setKeyboardTracking(False)
        size.setMinimumWidth(70)
        size.valueChanged.connect(lambda v: self.text_set(size_pt=float(v)))
        size.setToolTip(tr('Font size in points (1 pt = 0.353 mm).'))
        self.widgets['text_size'] = size
        formatting = [size]
        for key, label, field, tip in (('text_bold', 'B', 'bold', 'Bold'), ('text_italic', 'I', 'italic', 'Italic'),
                                       ('text_underline', 'U', 'underline', 'Underline')):
            button = QToolButton()
            button.setText(tr(label))
            font = button.font()
            font.setBold(field == 'bold')
            font.setItalic(field == 'italic')
            font.setUnderline(field == 'underline')
            button.setFont(font)
            button.setCheckable(True)
            button.setChecked(bool(getattr(style, field)))
            button.setToolTip(tr(tip))
            button.setFixedSize(30, 28)
            button.toggled.connect(lambda on, f=field: self.text_set(**{f: bool(on)}))
            self.widgets[key] = button
            formatting.append(button)
        form.addRow(row_of(*formatting))

        color = self.palette().color(self.foregroundRole()).name()
        for group_name, kinds, current in (('h', ('left', 'center', 'right', 'justify'), style.halign),
                                           ('v', ('top', 'middle', 'bottom'), style.valign)):
            group = QButtonGroup(self)
            group.setExclusive(True)
            buttons = []
            for kind in kinds:
                button = QToolButton()
                button.setIcon(alignment_icon(kind, color))
                button.setIconSize(QSize(22, 22))
                button.setCheckable(True)
                button.setChecked(kind == current)
                button.setFixedSize(34, 28)
                name = {'left': 'Align left', 'center': 'Align center', 'right': 'Align right', 'justify': 'Justify',
                        'top': 'Align top', 'middle': 'Align middle', 'bottom': 'Align bottom'}[kind]
                button.setToolTip(tr(name))
                field = 'halign' if group_name == 'h' else 'valign'
                button.clicked.connect(lambda _=False, f=field, k=kind: self.text_set(**{f: k}))
                group.addButton(button)
                self.widgets[f'text_{field}_{kind}'] = button
                buttons.append(button)
            form.addRow(tr('Horizontal') if group_name == 'h' else tr('Vertical'), row_of(*buttons))
            self.widgets[f'text_{group_name}_group'] = group

        spacing = QDoubleSpinBox()
        spacing.setDecimals(2)
        spacing.setRange(.5, 5.)
        spacing.setSingleStep(.1)
        spacing.setValue(style.spacing)
        spacing.setKeyboardTracking(False)
        spacing.valueChanged.connect(lambda v: self.text_set(spacing=float(v)))
        self.widgets['text_spacing'] = spacing
        form.addRow(tr('Line spacing'), spacing)
        wrap = QCheckBox(tr('Wrap text to the box width'))
        wrap.setChecked(style.wrap)
        wrap.toggled.connect(lambda on: self.text_set(wrap=bool(on)))
        self.widgets['text_wrap'] = wrap
        form.addRow(wrap)

        # Placement of the box itself (mm in the sketch plane).
        box = self.form('Text box position and size')
        x0, y0, x1, y1 = d['rect']

        def box_spin(key, label, value, apply, minimum=-100000., maximum=100000.):
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(minimum, maximum)
            spin.setSingleStep(1.)
            spin.setSuffix(' mm')
            spin.setValue(value)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda v: apply(float(v)))
            self.widgets[key] = spin
            box.addRow(tr(label), spin)

        def moved(axis):
            def apply(value):
                a, b, c, e = self.text_draft['rect']
                if axis == 'x':
                    self.text_set_rect([value, b, value + (c - a), e])
                else:
                    self.text_set_rect([a, value, c, value + (e - b)])
            return apply

        def resized(axis):
            def apply(value):
                a, b, c, e = self.text_draft['rect']
                if axis == 'w':
                    self.text_set_rect([a, b, a + value, e])
                else:
                    self.text_set_rect([a, b, c, b + value])
            return apply

        box_spin('text_box_x', 'Left', min(x0, x1), moved('x'))
        box_spin('text_box_y', 'Bottom', min(y0, y1), moved('y'))
        box_spin('text_box_w', 'Width', abs(x1 - x0), resized('w'), .01)
        box_spin('text_box_h', 'Height', abs(y1 - y0), resized('h'), .01)
        fit = QToolButton()
        fit.setText(tr('Fit box to text'))
        fit.setToolButtonStyle(Qt.ToolButtonTextOnly)
        fit.clicked.connect(self.text_fit_box)
        box.addRow(fit)

        readout = QLabel('')
        readout.setWordWrap(True)
        self.widgets['text_readout'] = readout
        self.editor_layout.addWidget(readout)
        self.text_readout()

    def text_fit_box(self):
        """Shrink or grow the box to the text, keeping its top-left corner."""
        info = getattr(self, 'text_info', None)
        if self.text_draft is None or info is None or not info.lines:
            return
        x0, y0, x1, y1 = self.text_draft['rect']
        left, top = min(x0, x1), max(y0, y1)
        width = max(info.width, .01) + .0001
        height = max(info.height, .01) + .0001
        self.text_set_rect([left, top - height, left + width, top])
        for key, value in (('text_box_w', width), ('text_box_h', height), ('text_box_y', top - height)):
            spin = self.widgets.get(key)
            if spin is not None:
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)

    # ---- finishing -----------------------------------------------------------------------
    def apply_text(self):
        """Turn the text box into sketch outlines. True when nothing is pending afterwards."""
        draft = self.text_draft
        if draft is None:
            return True
        from text_tool import layout_text, polygon_entities
        from geometry import validate_entity
        try:
            style = self.text_style_now()
            if not style.text.strip():
                raise ModelError('Text cannot be empty.')
            layout = layout_text(style, draft['rect'])
            if not layout.loops:
                raise ModelError('Text did not produce any sketch outlines.')
            created = polygon_entities(layout, self.workspace.construction_mode)
            for item in created:
                validate_entity(item)
            self.sketch_change()
            self.draft['entities'].extend(created)
            self.text_style = style
            self.clear_text_draft()
            self.entity_index = None
            self.workspace.active = self.draft
            self.workspace.update()
            self.show_editor()
            self.show_status(tr('Text placed.'))
            return True
        except Exception as error:
            self.error(error)
            return False

    def cancel_text(self):
        self.clear_text_draft()
        self.workspace.update()
        self.show_editor()
