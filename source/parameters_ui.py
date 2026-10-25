"""The document parameter table: named values and expressions that features and sketches can use."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QTableWidget,QTableWidgetItem,QPushButton,
                               QDialogButtonBox,QLabel,QHeaderView)
from legacy_model import ModelError
from i18n import tr


class ParametersUI:
    def parameter_rows(self,table):
        """The (name, expression) rows of the dialog table, validated."""
        parameters={}
        for row in range(table.rowCount()):
            name=table.item(row,0);expression=table.item(row,1)
            key=name.text().strip() if name is not None else ''
            text=expression.text().strip() if expression is not None else ''
            if not key and not text:continue
            if not key or not text:raise ModelError('Enter both a parameter name and an expression.')
            if key in parameters:raise ModelError('Duplicate parameter name: '+key)
            try:parameters[key]=float(text.replace(',','.'))
            except ValueError:parameters[key]=text
        return parameters

    def edit_parameters(self):
        """Dialog for the project's parameters. Applying rebuilds the model as one undoable step."""
        if self.loading:return
        if getattr(self,'component_stack',[]):
            self.show_status(tr('Return to the parent assembly to edit the document parameters.'));return
        if not self.abandon():return
        from expressions import resolve
        dialog=QDialog(self);dialog.setWindowTitle(tr('Document parameters'));dialog.resize(560,380)
        layout=QVBoxLayout(dialog)
        intro=QLabel(tr('Named values for the whole project. Use them in any number box of a feature or in a sketch dimension, for example: width / 2 + 1.'));intro.setWordWrap(True);layout.addWidget(intro)
        table=QTableWidget(0,3);table.setHorizontalHeaderLabels([tr('Name'),tr('Expression'),tr('Value')])
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeToContents)
        layout.addWidget(table)
        status=QLabel('');status.setWordWrap(True);layout.addWidget(status)
        refreshing=[False]
        def add_row(name='',expression=''):
            row=table.rowCount();table.insertRow(row)
            table.setItem(row,0,QTableWidgetItem(name));table.setItem(row,1,QTableWidgetItem(str(expression)))
            value=QTableWidgetItem('');value.setFlags(value.flags()&~Qt.ItemIsEditable);table.setItem(row,2,value)
        def refresh_values(*_):
            if refreshing[0]:return
            refreshing[0]=True
            try:
                try:
                    parameters=self.parameter_rows(table);values=resolve(parameters);problem=''
                except ModelError as error:
                    values={};problem=tr(str(error))
                for row in range(table.rowCount()):
                    name=table.item(row,0);cell=table.item(row,2)
                    if cell is None:continue
                    key=name.text().strip() if name is not None else ''
                    cell.setText(f'{values[key]:.6g}' if key in values else '')
                status.setText(problem);status.setStyleSheet('color: #d65b55;' if problem else '')
            finally:refreshing[0]=False
        for name,expression in self.doc.parameters.items():add_row(name,expression)
        table.itemChanged.connect(refresh_values);refresh_values()
        row=QHBoxLayout()
        add=QPushButton(tr('Add parameter'));add.clicked.connect(lambda:(add_row(),table.setCurrentCell(table.rowCount()-1,0),refresh_values()));row.addWidget(add)
        remove=QPushButton(tr('Delete selected parameter'));remove.clicked.connect(lambda:(table.removeRow(table.currentRow()) if table.currentRow()>=0 else None,refresh_values()));row.addWidget(remove)
        row.addStretch(1);layout.addLayout(row)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.Ok).setText(tr('Apply'));buttons.button(QDialogButtonBox.Cancel).setText(tr('Cancel'))
        buttons.rejected.connect(dialog.reject)
        def apply():
            try:
                parameters=self.parameter_rows(table)
                table_copy=copy.deepcopy(self.doc.features)
                # The new table is tried first, so a value that breaks the model changes nothing.
                self.run_busy('Checking parameters…',lambda report:self.doc.preview(table_copy,progress=report,parameters=parameters))
                changed=self.run_busy('Rebuilding model…',lambda report:self.doc.set_parameters(parameters,progress=report))
            except Exception as error:
                status.setText(tr(str(error)));status.setStyleSheet('color: #d65b55;');return
            dialog.accept()
            if changed:self.selected=None;self.refresh()
        buttons.accepted.connect(apply)
        dialog.exec()
