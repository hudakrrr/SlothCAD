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


def _scaled_mass_properties(unit,density):
    """Mass properties computed for density 1 g/cm³, rescaled to ``density``."""
    import math
    if density<=0 or not math.isfinite(density):raise ModelError('Density must be a positive number.')
    scale=lambda rows:[[v*density for v in row] for row in rows]
    result=dict(unit,mass=unit['mass']*density,inertia=scale(unit['inertia']),principal=[v*density for v in unit['principal']],density=float(density))
    result['bodies']=[dict(b,mass=b['mass']*density,inertia=scale(b['inertia']),principal=[v*density for v in b['principal']]) for b in unit['bodies']]
    return result


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
        # Bodies unchecked in the browser are left out unless asked for (a separate key from the
        # old opt-in 'export/visible_only', so an earlier saved 'off' does not keep including them).
        visible=str(_setting('export/include_hidden','false')).lower()!='true'
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
        hidden=QCheckBox(tr('Also export bodies hidden in the browser'));hidden.setChecked(not visible);layout.addWidget(hidden)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()==QDialog.Accepted:
            _store('export/quality',quality.currentData());_store('export/tolerance',deviation.value());_store('export/angular',angle.value())
            _store('export/include_hidden','true' if hidden.isChecked() else 'false')

    # ---- mass properties ------------------------------------------------------------------
    def _unit_mass_properties(self,visible_only,report=None):
        """Mass properties at density 1 g/cm³, computed in the kernel process."""
        from kernel_process import KERNEL,shape_bytes
        chosen=self.doc.chosen_bodies(visible_only)
        if not chosen:raise ModelError('There is no solid to measure.')
        result=KERNEL.call('mass',dict(shapes=[shape_bytes(body) for _,body in chosen],density=1.),report)
        result['names']=[name for name,_ in chosen]
        return result

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
        # The kernel work (volume, area, inertia) runs once per body selection, in the background;
        # mass and inertia scale linearly with density, so changing the material is instant.
        unit={}
        def update(*_):
            chosen=material.currentData()
            if chosen is not None:
                density.blockSignals(True);density.setValue(chosen);density.blockSignals(False)
            density.setEnabled(chosen is None)
            only=visible.isChecked()
            try:
                if only not in unit:unit[only]=self.run_busy('Computing mass properties…',lambda progress:self._unit_mass_properties(only,progress))
                result=_scaled_mass_properties(unit[only],density.value())
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
        def work(report):
            from kernel_process import KERNEL,shape_bytes
            shapes=[(name,shape_bytes(body)) for name,body in zip(self.doc.body_names(),self.doc.solids())]
            return [tuple(pair) for pair in KERNEL.call('interference',dict(shapes=shapes),report)]
        try:pairs=self.run_busy('Checking interference…',work)
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
        svg=filename.lower().endswith('.svg')
        if not svg and not filename.lower().endswith('.dxf'):filename+='.dxf'
        tolerance,angular,visible_only=self.export_preferences()
        title=self.path.stem if self.path else ''
        try:
            from kernel_process import KERNEL,item_bytes
            def work(report):
                # Hidden-line projection is many long kernel calls; it runs in the kernel process.
                report(0,0,'Preparing export…')
                items=item_bytes(self.doc.export_items(visible_only))
                return KERNEL.call('drawing',dict(items=items,path=str(filename),svg=svg,options=options,title=title),report)
            self.run_busy('Exporting drawing…',work)
            self.show_status(f'Exported {filename}')
        except Exception as error:self.error(error)

    # ---- importing ------------------------------------------------------------------------
    def import_model_file(self,filter_=None):
        """STEP, IGES or a triangle mesh (STL, OBJ, 3MF); ``filter_`` limits the file dialog to one type."""
        self.ensure_session()
        if not self.abandon():return
        filter_=filter_ or tr('3D models (*.step *.stp *.iges *.igs *.stl *.obj *.3mf)')
        filename,_=QFileDialog.getOpenFileName(self,tr('Import model'),'',filter_)
        if not filename:return
        try:self.import_feature_file(filename)
        except Exception as error:self.error(error)

    def apply_import_colors(self,feature,first_body):
        """Bodies that came with a colour in the file keep it."""
        colors=feature.get('part_colors') or []
        if not colors:return
        materials=self.doc.display.setdefault('materials',{})
        for offset,color in enumerate(colors):
            if color:materials[str(first_body+offset)]={'color':color,'finish':'matte'}
