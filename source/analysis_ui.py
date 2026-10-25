"""Tools menu: mass properties, interference check, bill of materials, drawings and export options."""
import csv
import io
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QDoubleSpinBox,QCheckBox,
                               QDialogButtonBox,QTableWidget,QTableWidgetItem,QPushButton,QFileDialog,QHeaderView,
                               QApplication,QGroupBox)
from legacy_model import ModelError
from analysis import MATERIALS
from i18n import tr
import platform_support

MESH_QUALITY={'draft':(0.2,0.35),'standard':(0.05,0.1),'fine':(0.01,0.05)}


def _setting(key,default):
    try:return platform_support.settings().value(key,default)
    except Exception:return default


def _store(key,value):
    try:
        settings=platform_support.settings();settings.setValue(key,value);settings.sync()
    except Exception:pass


class AnalysisUI:
    # ---- export preferences ---------------------------------------------------------------
    def export_preferences(self):
        """``(tolerance, angular_tolerance, visible_only)`` chosen under Settings > Export options."""
        quality=str(_setting('export/quality','standard'))
        if quality in MESH_QUALITY:tolerance,angular=MESH_QUALITY[quality]
        else:
            try:tolerance=float(_setting('export/tolerance',0.05));angular=float(_setting('export/angular',0.1))
            except (TypeError,ValueError):tolerance,angular=MESH_QUALITY['standard']
            if not (tolerance>0 and angular>0):tolerance,angular=MESH_QUALITY['standard']
        visible=str(_setting('export/visible_only','false')).lower()=='true'
        return tolerance,angular,visible

    def export_options(self):
        dialog=QDialog(self);dialog.setWindowTitle(tr('Export options'));layout=QVBoxLayout(dialog)
        tolerance,angular,visible=self.export_preferences()
        form=QFormLayout();layout.addLayout(form)
        quality=QComboBox()
        for label,key in (('Draft · small files','draft'),('Standard','standard'),('Fine · smooth curves','fine'),('Custom','custom')):quality.addItem(tr(label),key)
        current=str(_setting('export/quality','standard'));quality.setCurrentIndex(max(0,quality.findData(current)))
        form.addRow(tr('Mesh quality (STL, 3MF, glTF)'),quality)
        deviation=QDoubleSpinBox();deviation.setDecimals(4);deviation.setRange(.0005,10);deviation.setSingleStep(.01);deviation.setValue(tolerance);deviation.setSuffix(' mm')
        angle=QDoubleSpinBox();angle.setDecimals(3);angle.setRange(.01,1.5);angle.setSingleStep(.05);angle.setValue(angular);angle.setSuffix(' rad')
        form.addRow(tr('Largest deviation'),deviation);form.addRow(tr('Largest angle between facets'),angle)
        def sync(*_):
            custom=quality.currentData()=='custom'
            deviation.setEnabled(custom);angle.setEnabled(custom)
            if not custom:
                d,a=MESH_QUALITY[quality.currentData()];deviation.setValue(d);angle.setValue(a)
        quality.currentIndexChanged.connect(sync);sync()
        only=QCheckBox(tr('Only the bodies shown in the browser'));only.setChecked(visible);layout.addWidget(only)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()==QDialog.Accepted:
            _store('export/quality',quality.currentData());_store('export/tolerance',deviation.value());_store('export/angular',angle.value())
            _store('export/visible_only','true' if only.isChecked() else 'false')

    # ---- mass properties ------------------------------------------------------------------
    def show_mass_properties(self):
        if self.doc.solid is None:
            self.show_status(tr('Create a body first.'));return
        dialog=QDialog(self);dialog.setWindowTitle(tr('Mass properties'));dialog.resize(520,560);layout=QVBoxLayout(dialog)
        form=QFormLayout();layout.addLayout(form)
        material=QComboBox()
        for name,density in MATERIALS:material.addItem(f'{tr(name)} · {density:g} g/cm³',density)
        material.addItem(tr('Custom density'),None)
        density=QDoubleSpinBox();density.setDecimals(4);density.setRange(.0001,100);density.setSuffix(' g/cm³');density.setValue(MATERIALS[0][1])
        form.addRow(tr('Material'),material);form.addRow(tr('Density'),density)
        visible=QCheckBox(tr('Only the bodies shown in the browser'));layout.addWidget(visible)
        report=QLabel();report.setTextInteractionFlags(Qt.TextSelectableByMouse);report.setWordWrap(True);report.setAlignment(Qt.AlignTop|Qt.AlignLeft)
        layout.addWidget(report,1)
        def update(*_):
            chosen=material.currentData()
            if chosen is not None:
                density.blockSignals(True);density.setValue(chosen);density.blockSignals(False)
            density.setEnabled(chosen is None)
            try:result=self.doc.mass_properties(density.value(),visible.isChecked())
            except ModelError as error:
                report.setText(tr(str(error)));return
            c=result['center'];t=result['inertia'];p=result['principal']
            rows=[f"<b>{tr('Volume')}</b>: {result['volume']:,.3f} mm³",f"<b>{tr('Surface area')}</b>: {result['area']:,.3f} mm²",
                  f"<b>{tr('Mass')}</b>: {result['mass']:,.4f} g",f"<b>{tr('Center of mass')}</b> (X, Y, Z): {c[0]:.4f}, {c[1]:.4f}, {c[2]:.4f} mm",
                  f"<b>{tr('Principal moments of inertia')}</b> (g·mm²): {p[0]:,.4g}, {p[1]:,.4g}, {p[2]:,.4g}",
                  f"<b>{tr('Inertia tensor about the center of mass')}</b> (g·mm²):<br><tt>"+'<br>'.join('  '.join(f'{v:14,.5g}' for v in row) for row in t)+'</tt>']
            if len(result['bodies'])>1:
                rows.append(f"<b>{tr('Bodies')}</b>:")
                rows.extend(f"&nbsp;&nbsp;{n}: {b['mass']:,.4f} g · {b['volume']:,.2f} mm³" for n,b in zip(result['names'],result['bodies']))
            report.setText('<br>'.join(rows))
        material.currentIndexChanged.connect(update);density.valueChanged.connect(update);visible.toggled.connect(update);update()
        copy=QPushButton(tr('Copy to clipboard'));copy.clicked.connect(lambda:QApplication.clipboard().setText(report.text().replace('<br>','\n').replace('&nbsp;',' ').replace('<tt>','').replace('</tt>','').replace('<b>','').replace('</b>','')))
        layout.addWidget(copy)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);buttons.accepted.connect(dialog.accept);layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.Close).clicked.connect(dialog.accept)
        dialog.exec()

    # ---- interference ---------------------------------------------------------------------
    def check_interference(self):
        if self.doc.solid is None or len(self.doc.solids())<2:
            self.show_status(tr('Interference needs at least two bodies.'));return None
        try:pairs=self.run_busy('Checking interference…',lambda report:self.doc.interferences())
        except Exception as error:
            self.error(error);return None
        if not pairs:
            self.show_status(tr('No interference found: no two bodies share volume.'));return pairs
        dialog=QDialog(self);dialog.setWindowTitle(tr('Interference'));dialog.resize(480,320);layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel(tr('These bodies overlap:')))
        table=QTableWidget(len(pairs),3);table.setHorizontalHeaderLabels([tr('Body'),tr('Body'),tr('Overlap (mm³)')])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row,(a,b,volume) in enumerate(pairs):
            for column,text in enumerate((a,b,f'{volume:,.3f}')):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemIsEditable);table.setItem(row,column,item)
        layout.addWidget(table)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.Close).clicked.connect(dialog.accept)
        dialog.exec()
        return pairs

    # ---- bill of materials ----------------------------------------------------------------
    def show_bill_of_materials(self):
        if self.doc.solid is None:
            self.show_status(tr('Create a body first.'));return None
        rows=self.doc.bill_of_materials()
        dialog=QDialog(self);dialog.setWindowTitle(tr('Bill of materials'));dialog.resize(520,360);layout=QVBoxLayout(dialog)
        table=QTableWidget(len(rows),3);table.setHorizontalHeaderLabels([tr('Part'),tr('Quantity'),tr('Volume (mm³)')])
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        for r,row in enumerate(rows):
            for c,text in enumerate((row['name'],str(row['quantity']),f"{row['volume']:,.3f}")):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemIsEditable);table.setItem(r,c,item)
        layout.addWidget(table)
        line=QHBoxLayout();layout.addLayout(line)
        save=QPushButton(tr('Save as CSV…'));line.addWidget(save);line.addStretch(1)
        def write():
            filename,_=QFileDialog.getSaveFileName(dialog,tr('Save bill of materials'),'bill-of-materials.csv',tr('CSV table (*.csv)'))
            if not filename:return
            if not filename.lower().endswith('.csv'):filename+='.csv'
            try:Path(filename).write_text(self.bill_as_csv(rows),encoding='utf-8-sig',newline='')
            except OSError as error:self.error(error)
        save.clicked.connect(write)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);line.addWidget(buttons)
        buttons.button(QDialogButtonBox.Close).clicked.connect(dialog.accept)
        dialog.exec()
        return rows

    @staticmethod
    def bill_as_csv(rows):
        out=io.StringIO();writer=csv.writer(out,lineterminator='\r\n')
        writer.writerow(['Part','Quantity','Volume (mm3)'])
        for row in rows:writer.writerow([row['name'],row['quantity'],f"{row['volume']:.3f}"])
        return out.getvalue()

    # ---- drawings -------------------------------------------------------------------------
    def drawing_options(self):
        """Ask which views the drawing sheet contains. Returns None when cancelled."""
        from drawing import VIEW_NAMES
        dialog=QDialog(self);dialog.setWindowTitle(tr('Export drawing'));layout=QVBoxLayout(dialog)
        box=QGroupBox(tr('Views'));column=QVBoxLayout(box);checks={}
        defaults=str(_setting('drawing/views','front,top,right')).split(',')
        for name in VIEW_NAMES:
            check=QCheckBox(tr(name.title()));check.setChecked(name in defaults);column.addWidget(check);checks[name]=check
        layout.addWidget(box)
        form=QFormLayout();layout.addLayout(form)
        hidden=QCheckBox(tr('Hidden lines (dashed)'));hidden.setChecked(True);form.addRow(hidden)
        dims=QCheckBox(tr('Overall dimensions (DXF)'));dims.setChecked(True);form.addRow(dims)
        scale=QComboBox()
        for label,value in (('1 : 1',1.),('2 : 1',2.),('5 : 1',5.),('1 : 2',.5),('1 : 5',.2),('1 : 10',.1)):scale.addItem(label,value)
        form.addRow(tr('Scale'),scale)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()!=QDialog.Accepted:return None
        chosen=[name for name,check in checks.items() if check.isChecked()]
        if not chosen:
            self.show_status(tr('Choose at least one view for the drawing.'));return None
        _store('drawing/views',','.join(chosen))
        return dict(views=chosen,hidden=hidden.isChecked(),dimensions=dims.isChecked(),scale=scale.currentData())

    def export_drawing_file(self):
        if self.has_draft():self.error('Finish your sketch or Apply / Cancel current changes before exporting.');return
        if self.doc.solid is None:self.error('Create geometry before exporting.');return
        options=self.drawing_options()
        if options is None:return
        filename,_=QFileDialog.getSaveFileName(self,tr('Export drawing'),'drawing.dxf',tr('DXF drawing (*.dxf);;SVG graphic (*.svg)'))
        if not filename:return
        from drawing import export_dxf,export_svg
        svg=filename.lower().endswith('.svg')
        if not svg and not filename.lower().endswith('.dxf'):filename+='.dxf'
        tolerance,angular,visible_only=self.export_preferences()
        title=self.path.stem if self.path else ''
        try:
            def work(report):
                shape=self.doc.export_items(visible_only)
                import cadquery as cq
                solid=shape[0][1] if len(shape)==1 else cq.Compound.makeCompound([item[1] for item in shape])
                if svg:return export_svg(filename,solid,options['views'],options['hidden'],options['scale'],title)
                return export_dxf(filename,solid,options['views'],options['hidden'],options['scale'],options['dimensions'],title)
            self.run_busy('Exporting drawing…',work)
            self.show_status(f'Exported {filename}')
        except Exception as error:self.error(error)

    # ---- importing ------------------------------------------------------------------------
    def import_model_file(self):
        """STEP, IGES or a triangle mesh (STL, OBJ, 3MF)."""
        self.ensure_session()
        if not self.abandon():return
        filename,_=QFileDialog.getOpenFileName(self,tr('Import model'),'',tr('3D models (*.step *.stp *.iges *.igs *.stl *.obj *.3mf)'))
        if not filename:return
        from exchange import import_model
        try:
            before=len(self.doc.solids())
            feature=self.run_busy('Importing model…',lambda progress:import_model(filename))
            self.run_busy('Rebuilding model…',lambda progress:self.doc.commit(self.doc.features+[feature],progress))
            self.apply_import_colors(feature,before)
            self.selected=len(self.doc.features)-1;self.workspace.set_mode('model');self.refresh(True)
        except Exception as error:self.error(error)

    def apply_import_colors(self,feature,first_body):
        """Bodies that came with a colour in the file keep it."""
        colors=feature.get('part_colors') or []
        if not colors:return
        materials=self.doc.display.setdefault('materials',{})
        for offset,color in enumerate(colors):
            if color:materials[str(first_body+offset)]={'color':color,'finish':'matte'}
