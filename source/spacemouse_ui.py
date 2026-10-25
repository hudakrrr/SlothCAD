"""SpaceMouse wiring for the main window: controller, button actions and the settings dialog."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget)

import platform_support
from i18n import tr
from spacemouse import ACTION_NAMES, AXIS_NAMES, GESTURES, SpaceMouseController, dominant_axis


class SpaceMouseUI:
    def init_spacemouse(self):
        self.spacemouse = None
        try:
            actions = {
                'Fit view': lambda: self.workspace.fit(),
                'Iso view': lambda: self.view_preset('Iso'), 'Top view': lambda: self.view_preset('Top'),
                'Front view': lambda: self.view_preset('Front'), 'Right view': lambda: self.view_preset('Right'),
                'Apply': lambda: self.draft and self.apply_feature(), 'Cancel': lambda: self.draft and self.cancel(),
                'Undo': self.undo, 'Redo': self.redo, 'Toggle grid': self.toggle_grid_over,
                'Turn 90°': lambda: self.workspace.turn_object(90.),
                'Rotate only': lambda: self.show_status(tr('Only rotating') if self.spacemouse.toggle_rotate_only() else tr('Pan, zoom and rotate')),
                'Lock rotation': lambda: self.show_status(tr('Rotation locked') if self.spacemouse.toggle_rotation_lock() else tr('Rotation free')),
            }
            self.spacemouse = SpaceMouseController(self, self.workspace, actions, platform_support.settings())
            self.spacemouse.start()
        except Exception:
            self.spacemouse = None      # no device or driver: the mouse keeps working as before

    def stop_spacemouse(self):
        if self.spacemouse is not None:
            self.spacemouse.stop()

    def spacemouse_settings(self):
        controller = self.spacemouse
        if controller is None:
            self.show_status(tr('SpaceMouse support is not available on this system.'))
            return
        profile = controller.profile
        dialog = QDialog(self);dialog.setWindowTitle(tr('Settings · SpaceMouse'));layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24);layout.setSpacing(12)
        state = QLabel();state.setWordWrap(True);layout.addWidget(state)

        def refresh_state():
            if controller.connected:
                state.setText(tr('Listening for a 3Dconnexion device.') + ((' ' + controller.device_name()) if controller.product else ''))
            else:
                state.setText(tr('No SpaceMouse input found (Linux needs the spacenavd daemon).'))
        refresh_state()
        enabled = QCheckBox(tr('Use the SpaceMouse to move the view'));enabled.setChecked(profile.enabled);layout.addWidget(enabled)
        form = QFormLayout();layout.addLayout(form)
        sliders = {}
        for key, label in (('rotate', 'Rotation speed'), ('pan', 'Pan speed'), ('zoom', 'Zoom speed')):
            slider = QSlider(Qt.Horizontal);slider.setRange(10, 400);slider.setValue(int(getattr(profile, key) * 100))
            sliders[key] = slider;form.addRow(tr(label), slider)
        dead = QSlider(Qt.Horizontal);dead.setRange(0, 80);dead.setValue(profile.deadzone);form.addRow(tr('Dead zone'), dead)
        grid = QGridLayout();grid.setHorizontalSpacing(12)
        for column, title in ((0, 'Active'), (2, 'Reverse')):
            grid.addWidget(QLabel(tr(title)), 0, column)
        axis_rows = []
        for row, label in enumerate(('Push left / right', 'Push forward / back', 'Lift / press (zoom)', 'Tilt forward / back', 'Roll left / right', 'Twist (spin)'), 1):
            active = QCheckBox();active.setChecked(profile.axis_active[row - 1])
            speed = QSlider(Qt.Horizontal);speed.setRange(10, 400);speed.setValue(int(profile.axis_speed[row - 1] * 100))
            reverse = QCheckBox();reverse.setChecked(profile.axis_reverse[row - 1])
            grid.addWidget(active, row, 0);grid.addWidget(speed, row, 1);grid.addWidget(reverse, row, 2);grid.addWidget(QLabel(tr(label)), row, 3)
            axis_rows.append((active, speed, reverse))
        layout.addLayout(grid)
        reverse_all = QPushButton(tr('Reverse all axes'))
        reverse_all.clicked.connect(lambda: [r.setChecked(not r.isChecked()) for _a, _s, r in axis_rows]);layout.addWidget(reverse_all)
        dominant = QCheckBox(tr('Dominant axis only (one movement at a time)'));dominant.setChecked(profile.dominant);layout.addWidget(dominant)
        bars = []
        for name in AXIS_NAMES:
            bar = QProgressBar();bar.setRange(-350, 350);bar.setFormat(name);bar.setValue(0);bars.append(bar);layout.addWidget(bar)
        controller.changed.connect(lambda raw: [b.setValue(int(max(-350, min(350, v)))) for b, v in zip(bars, raw)])
        # button assignment: press a button on the device, then pick what it does
        row = QHBoxLayout();last = QLabel(tr('Press a button on the device to assign it.'));row.addWidget(last)
        choice = QComboBox();choice.addItem(tr('(nothing)'), '')
        for name in ACTION_NAMES:
            choice.addItem(tr(name), name)
        row.addWidget(choice);layout.addLayout(row)
        picked = {'index': None}

        def button_seen(index):
            picked['index'] = index;last.setText(tr('Button') + f' {index}')
            choice.setCurrentIndex(max(0, choice.findData(profile.buttons.get(str(index), ''))))
        controller.button_pressed.connect(button_seen)
        choice.activated.connect(lambda _=0: picked['index'] is not None and (
            profile.buttons.__setitem__(str(picked['index']), choice.currentData()) if choice.currentData()
            else profile.buttons.pop(str(picked['index']), None)))
        calibrate = QPushButton(tr('Calibrate axes…'));calibrate.clicked.connect(lambda: self.spacemouse_calibrate(dialog));layout.addWidget(calibrate)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.Save).setText(tr('Save'));buttons.button(QDialogButtonBox.Cancel).setText(tr('Cancel'))
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        before = profile.to_json()
        accepted = dialog.exec() == QDialog.Accepted
        try:
            controller.changed.disconnect();controller.button_pressed.disconnect(button_seen)
        except Exception:
            pass
        if accepted:
            profile.axis_active = [a.isChecked() for a, _s, _r in axis_rows]
            profile.axis_reverse = [r.isChecked() for _a, _s, r in axis_rows]
            profile.axis_speed = [s.value() / 100. for _a, s, _r in axis_rows]
            profile.enabled = enabled.isChecked();profile.dominant = dominant.isChecked();profile.deadzone = dead.value()
            for key, slider in sliders.items():
                setattr(profile, key, slider.value() / 100.)
            controller.save()
        else:
            controller.profile = type(profile).from_json(before)

    def spacemouse_calibrate(self, parent):
        """Ask for each gesture in turn and learn which device axis answers it."""
        controller = self.spacemouse
        steps = list(GESTURES)

        def next_step():
            if not steps:
                self.show_status(tr('SpaceMouse axes calibrated.'));return
            channel, instruction, result = steps.pop(0)
            self.show_status(tr(instruction) + ' (' + tr(result) + ')')

            def finished(samples):
                found = dominant_axis(samples)
                if found is not None:
                    index, sign = found
                    controller.profile.mapping[channel] = [index, sign]
                next_step()
            controller.record(2.5, finished)
        next_step()
