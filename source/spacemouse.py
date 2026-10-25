"""3Dconnexion SpaceMouse support (SpaceMouse Pro Wireless and the other 6-axis models).

How the device reaches the program
* Windows: Raw Input (HID). The window registers for the "multi-axis controller" usage
  (page 0x01, usage 0x08) and Qt's native event filter sees ``WM_INPUT`` messages. No
  vendor library is needed; the 3DxWare driver may stay installed.
* Linux: the ``spacenavd`` daemon through ``libspnav`` (ctypes), read with a socket notifier.

HID reports (SpaceMouse Pro / Wireless / Navigator and relatives)
* report 0x01: translation, three signed 16-bit values; 13 bytes or more also carry the
  rotation (report 0x02's payload) in the same packet
* report 0x02: rotation, three signed 16-bit values
* report 0x03: button bit mask (bit 0 = button 1)

Everything that does not touch the operating system lives in plain functions
(:func:`parse_report`, :func:`decode_rawinput`, :func:`shape_axes`, :func:`to_motion`) so it
can be tested with recorded or simulated packets.
"""
import ctypes
import json
import math
import os
import struct
import sys
import time
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QAbstractNativeEventFilter, QObject, QSocketNotifier, QTimer, Signal

WINDOWS = sys.platform.startswith('win')
VENDOR_IDS = (0x256F, 0x046D)
RAW_RANGE = 350.0               # a fully deflected cap reports about +-350
AXIS_NAMES = ('x', 'y', 'z', 'rx', 'ry', 'rz')
CHANNELS = ('pan_x', 'pan_y', 'zoom', 'tilt', 'spin')

# Gestures of the calibration wizard: (channel, instruction, what the scene should do).
GESTURES = (
    ('pan_x', 'Push the cap to the right', 'the model moves right'),
    ('pan_y', 'Push the cap forward, away from you', 'the model moves up'),
    ('zoom', 'Lift the cap straight up', 'the view zooms in'),
    ('tilt', 'Tilt the cap forward', 'the model tips forward'),
    ('spin', 'Twist the cap clockwise (seen from above)', 'the model turns clockwise'),
)
# channel -> (index into the six raw axes, sign). Derived from how FreeCAD maps the same
# device; the wizard replaces it with what this particular device and user actually do.
DEFAULT_MAPPING = {'pan_x': (0, 1.), 'pan_y': (1, -1.), 'zoom': (2, -1.), 'tilt': (3, 1.), 'spin': (5, 1.)}

# Names of the things a button can do; the app supplies the callables.
ACTION_NAMES = ('Fit view', 'Iso view', 'Top view', 'Front view', 'Right view',
                'Apply', 'Cancel', 'Undo', 'Redo', 'Toggle grid', 'Lock rotation', 'Rotate only', 'Turn 90°')

# Button numbers measured on a SpaceMouse Pro Wireless: 2 Fit, 3 Top, 5 Right, 6 Front, 9 Rotate only, 27 Lock rotation.
DEFAULT_BUTTONS = {'2': 'Fit view', '9': 'Turn 90°', '27': 'Lock rotation', '3': 'Top view', '5': 'Right view', '6': 'Front view', '7': 'Cancel'}

PRODUCTS = {
    0xC603: 'SpaceMouse Plus', 0xC625: 'SpacePilot', 0xC626: 'SpaceNavigator', 0xC627: 'SpaceExplorer',
    0xC628: 'SpaceNavigator for Notebooks', 0xC629: 'SpacePilot Pro', 0xC62B: 'SpaceMouse Pro',
    0xC62E: 'SpaceMouse Wireless', 0xC62F: 'SpaceMouse Wireless (receiver)',
    0xC631: 'SpaceMouse Pro Wireless', 0xC632: 'SpaceMouse Pro Wireless (receiver)',
    0xC633: 'SpaceMouse Enterprise', 0xC635: 'SpaceMouse Compact',
}


# ----------------------------------------------------------------------------- decoding
def parse_report(data):
    """Decode one HID input report.

    Returns ``('motion', translation, rotation)``, ``('translation', t)``, ``('rotation', r)``,
    ``('buttons', mask)`` or ``None`` for reports that are not understood.
    """
    data = bytes(data)
    if len(data) < 5:
        return None
    kind = data[0]
    if kind == 1 and len(data) >= 7:
        translation = struct.unpack_from('<hhh', data, 1)
        if len(data) >= 13:
            return ('motion', translation, struct.unpack_from('<hhh', data, 7))
        return ('translation', translation)
    if kind == 2 and len(data) >= 7:
        return ('rotation', struct.unpack_from('<hhh', data, 1))
    if kind == 3:
        return ('buttons', int.from_bytes(data[1:5], 'little'))
    return None


def decode_rawinput(buffer, pointer_size=None):
    """Split a Windows ``RAWINPUT`` buffer into ``(type, device handle, [HID reports])``.

    ``type`` is 2 for HID input. Layout: RAWINPUTHEADER (DWORD type, DWORD size, HANDLE
    device, WPARAM wParam), then RAWHID (DWORD sizeHid, DWORD count, BYTE data[]).
    """
    pointer_size = pointer_size or ctypes.sizeof(ctypes.c_void_p)
    header = 8 + 2 * pointer_size
    if len(buffer) < header + 8:
        return None
    kind, _size = struct.unpack_from('<II', buffer, 0)
    handle = int.from_bytes(buffer[8:8 + pointer_size], 'little')
    size_hid, count = struct.unpack_from('<II', buffer, header)
    reports = []
    offset = header + 8
    for index in range(max(0, min(count, 64))):
        chunk = bytes(buffer[offset + index * size_hid: offset + (index + 1) * size_hid])
        if len(chunk) == size_hid and size_hid:
            reports.append(chunk)
    return kind, handle, reports


def spnav_to_axes(x, y, z, rx, ry, rz):
    """spacenavd reports in its own axis order; bring it to the HID order used everywhere else."""
    return [x, -z, -y, rx, -rz, -ry]


# ----------------------------------------------------------------------------- settings
@dataclass
class Profile:
    enabled: bool = True
    rotate: float = 1.0
    pan: float = 1.0
    zoom: float = 1.0
    deadzone: int = 14            # raw units (of about +-350) that are ignored
    curve: float = 1.3            # >1: gentle near the centre, fast at full deflection
    dominant: bool = False        # only the strongest axis moves the view
    mapping: dict = field(default_factory=lambda: {k: [v[0], v[1]] for k, v in DEFAULT_MAPPING.items()})
    buttons: dict = field(default_factory=lambda: dict(DEFAULT_BUTTONS))   # "7" -> action name
    axis_active: list = field(default_factory=lambda: [True] * 6)     # per device axis (x, y, z, rx, ry, rz)
    axis_reverse: list = field(default_factory=lambda: [False] * 6)
    axis_speed: list = field(default_factory=lambda: [1.] * 6)

    def to_json(self):
        return json.dumps({k: getattr(self, k) for k in self.__dataclass_fields__}, sort_keys=True)

    @classmethod
    def from_json(cls, text):
        profile = cls()
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return profile
        if not isinstance(data, dict):
            return profile
        for key in ('enabled', 'dominant'):
            if isinstance(data.get(key), bool):
                setattr(profile, key, data[key])
        for key, low, high in (('rotate', .1, 8.), ('pan', .1, 8.), ('zoom', .1, 8.), ('curve', 1., 3.)):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                setattr(profile, key, max(low, min(high, float(value))))
        if isinstance(data.get('deadzone'), int) and not isinstance(data['deadzone'], bool):
            profile.deadzone = max(0, min(200, data['deadzone']))
        mapping = data.get('mapping')
        if isinstance(mapping, dict):
            for channel in CHANNELS:
                item = mapping.get(channel)
                if (isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], int)
                        and 0 <= item[0] < 6 and item[1] in (1, -1, 1., -1.)):
                    profile.mapping[channel] = [item[0], float(item[1])]
        for key, kind in (('axis_active', bool), ('axis_reverse', bool), ('axis_speed', float)):
            values = data.get(key)
            if isinstance(values, list) and len(values) == 6:
                if kind is bool and all(isinstance(v, bool) for v in values):
                    setattr(profile, key, list(values))
                elif kind is float and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
                    setattr(profile, key, [max(.1, min(4., float(v))) for v in values])
        buttons = data.get('buttons')
        if isinstance(buttons, dict):
            assigned = {str(k): v for k, v in buttons.items() if isinstance(v, str) and v in ACTION_NAMES}
            if assigned:          # nothing assigned yet: keep the defaults (Fit, Top, Right, Front, Esc)
                profile.buttons = assigned
        return profile

    @classmethod
    def load(cls, settings):
        return cls.from_json(settings.value('spacemouse/profile', ''))

    def save(self, settings):
        settings.setValue('spacemouse/profile', self.to_json())
        settings.sync()


# ----------------------------------------------------------------------------- processing
def shape_axes(raw, profile):
    """Dead zone, response curve and (optionally) dominant axis for six raw values."""
    shaped = []
    dead = max(0, min(int(profile.deadzone), int(RAW_RANGE) - 1))
    for value in raw:
        magnitude = abs(float(value))
        if magnitude <= dead:
            shaped.append(0.)
            continue
        normal = min(1.5, (magnitude - dead) / (RAW_RANGE - dead))
        shaped.append(math.copysign(normal ** profile.curve, value))
    if profile.dominant and any(shaped):
        keep = max(range(6), key=lambda i: abs(shaped[i]))
        shaped = [v if i == keep else 0. for i, v in enumerate(shaped)]
    # per-axis settings: switch off, reverse, own speed
    return [v * profile.axis_speed[i] * (-1. if profile.axis_reverse[i] else 1.) * (1. if profile.axis_active[i] else 0.)
            for i, v in enumerate(shaped)]


def to_motion(shaped, profile):
    """Shaped axes -> what the view should do (each channel about -1 .. 1 at full deflection)."""
    motion = {}
    for channel in CHANNELS:
        index, sign = profile.mapping.get(channel, DEFAULT_MAPPING[channel])
        motion[channel] = shaped[int(index)] * float(sign)
    motion['pan_x'] *= profile.pan
    motion['pan_y'] *= profile.pan
    motion['zoom'] *= profile.zoom
    motion['tilt'] *= profile.rotate
    motion['spin'] *= profile.rotate
    return motion


def dominant_axis(samples, minimum=60.):
    """From raw samples gathered during one gesture: (axis index, sign) of the strongest, or None."""
    totals = [0.] * 6
    for sample in samples:
        for index, value in enumerate(sample):
            totals[index] += value
    index = max(range(6), key=lambda i: abs(totals[i]))
    peak = max((abs(s[index]) for s in samples), default=0.)
    if peak < minimum:
        return None
    return index, (1. if totals[index] >= 0 else -1.)


# ----------------------------------------------------------------------------- Windows reader
if WINDOWS:
    from ctypes import wintypes

    class _MSG(ctypes.Structure):
        _fields_ = [('hwnd', wintypes.HWND), ('message', wintypes.UINT), ('wParam', wintypes.WPARAM),
                    ('lParam', wintypes.LPARAM), ('time', wintypes.DWORD), ('pt_x', wintypes.LONG), ('pt_y', wintypes.LONG)]

    class _RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [('usUsagePage', wintypes.USHORT), ('usUsage', wintypes.USHORT),
                    ('dwFlags', wintypes.DWORD), ('hwndTarget', wintypes.HWND)]

    class _DEVICEINFO(ctypes.Structure):          # RID_DEVICE_INFO, HID member of the union
        _fields_ = [('cbSize', wintypes.DWORD), ('dwType', wintypes.DWORD), ('dwVendorId', wintypes.DWORD),
                    ('dwProductId', wintypes.DWORD), ('dwVersionNumber', wintypes.DWORD),
                    ('usUsagePage', wintypes.USHORT), ('usUsage', wintypes.USHORT), ('_pad', ctypes.c_byte * 8)]

WM_INPUT = 0x00FF
WHEEL_MESSAGES = (0x020A, 0x020E)        # WM_MOUSEWHEEL, WM_MOUSEHWHEEL
RID_INPUT = 0x10000003
RIDI_DEVICEINFO = 0x2000000B
RIDEV_INPUTSINK = 0x00000100
RIM_TYPEHID = 2


class RawInputReader(QAbstractNativeEventFilter):
    """Receives SpaceMouse HID reports as WM_INPUT messages of the main window."""

    def __init__(self, window_id, on_report, parent_app):
        super().__init__()
        self.window_id = int(window_id)
        self.on_report = on_report          # callable(product_id, report bytes)
        self.devices = {}                   # raw handle -> (vendor, product)
        self.available = False
        self.app = parent_app
        self.user32 = None
        self.block_wheel = lambda: False    # True while the device is moving: the driver's fake wheel clicks are dropped

    def start(self):
        if not WINDOWS:
            return False
        try:
            user32 = ctypes.windll.user32
            user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(_RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
            user32.RegisterRawInputDevices.restype = wintypes.BOOL
            user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT), wintypes.UINT]
            user32.GetRawInputData.restype = wintypes.UINT
            user32.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT)]
            user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
            # Like FreeCAD: no target window and no flags, so Windows delivers the reports to whichever of our
            # windows has the keyboard focus (a stored HWND can go stale when Qt recreates the native window).
            device = _RAWINPUTDEVICE(0x01, 0x08, 0, None)
            if not user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
                return False
        except Exception:
            return False
        self.user32 = user32
        self.app.installNativeEventFilter(self)
        self.available = True
        return True

    def stop(self):
        if self.available:
            try:
                self.app.removeNativeEventFilter(self)
            except Exception:
                pass
        self.available = False

    def product_of(self, handle):
        if handle in self.devices:
            return self.devices[handle]
        info = _DEVICEINFO()
        info.cbSize = ctypes.sizeof(info)
        size = wintypes.UINT(ctypes.sizeof(info))
        result = (0, 0)
        if self.user32.GetRawInputDeviceInfoW(wintypes.HANDLE(handle), RIDI_DEVICEINFO, ctypes.byref(info), ctypes.byref(size)) != 0xFFFFFFFF:
            result = (int(info.dwVendorId), int(info.dwProductId))
        self.devices[handle] = result
        return result

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) not in (b'windows_generic_MSG', b'windows_dispatcher_MSG'):
                return False, 0
            msg = _MSG.from_address(int(message))
            if msg.message in WHEEL_MESSAGES and self.block_wheel():
                return True, 0      # 3DxWare answers an unknown program with mouse-wheel clicks: each was a 15 % zoom jump
            if msg.message != WM_INPUT:
                return False, 0
            size = wintypes.UINT(0)
            header = 8 + 2 * ctypes.sizeof(ctypes.c_void_p)
            handle = wintypes.HANDLE(msg.lParam)
            if self.user32.GetRawInputData(handle, RID_INPUT, None, ctypes.byref(size), header) != 0:
                return False, 0
            buffer = ctypes.create_string_buffer(size.value)
            if self.user32.GetRawInputData(handle, RID_INPUT, buffer, ctypes.byref(size), header) != size.value:
                return False, 0
            decoded = decode_rawinput(buffer.raw[:size.value])
            if decoded is None or decoded[0] != RIM_TYPEHID:
                return False, 0
            vendor, product = self.product_of(decoded[1])
            if vendor not in VENDOR_IDS:
                return False, 0
            for report in decoded[2]:
                self.on_report(product, report)
        except Exception:
            return False, 0
        return False, 0           # never swallow the message: Qt and the driver still see it


# ----------------------------------------------------------------------------- Linux reader
class _SpnavMotion(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('x', ctypes.c_int), ('y', ctypes.c_int), ('z', ctypes.c_int),
                ('rx', ctypes.c_int), ('ry', ctypes.c_int), ('rz', ctypes.c_int),
                ('period', ctypes.c_uint), ('data', ctypes.c_void_p)]


class _SpnavButton(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('press', ctypes.c_int), ('bnum', ctypes.c_int)]


class _SpnavEvent(ctypes.Union):
    _fields_ = [('type', ctypes.c_int), ('motion', _SpnavMotion), ('button', _SpnavButton)]


class SpnavReader(QObject):
    """spacenavd through libspnav; events arrive on a QSocketNotifier."""

    def __init__(self, on_motion, on_button, parent=None):
        super().__init__(parent)
        self.on_motion = on_motion          # callable(six axes in HID order)
        self.on_button = on_button          # callable(index, pressed)
        self.available = False
        self.library = None
        self.notifier = None

    def start(self):
        if WINDOWS:
            return False
        for name in ('libspnav.so.0', 'libspnav.so'):
            try:
                library = ctypes.CDLL(name)
                break
            except OSError:
                library = None
        if library is None:
            return False
        try:
            library.spnav_open.restype = ctypes.c_int
            library.spnav_fd.restype = ctypes.c_int
            library.spnav_poll_event.argtypes = [ctypes.POINTER(_SpnavEvent)]
            library.spnav_poll_event.restype = ctypes.c_int
            if library.spnav_open() == -1:
                return False
            fd = library.spnav_fd()
        except Exception:
            return False
        self.library = library
        self.notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
        self.notifier.activated.connect(self.poll)
        self.available = True
        return True

    def stop(self):
        if self.notifier is not None:
            self.notifier.setEnabled(False)
        if self.library is not None and self.available:
            try:
                self.library.spnav_close()
            except Exception:
                pass
        self.available = False

    def poll(self, *_):
        event = _SpnavEvent()
        latest = None
        while self.library.spnav_poll_event(ctypes.byref(event)):
            if event.type == 1:      # SPNAV_EVENT_MOTION
                m = event.motion
                latest = spnav_to_axes(m.x, m.y, m.z, m.rx, m.ry, m.rz)
            elif event.type == 2:    # SPNAV_EVENT_BUTTON
                self.on_button(int(event.button.bnum), bool(event.button.press))
        if latest is not None:
            self.on_motion(latest)


# ----------------------------------------------------------------------------- controller
class SpaceMouseController(QObject):
    """Owns the reader, filters the motion and moves the workspace camera.

    ``workspace`` needs ``apply_navigation(motion, dt)``; ``actions`` maps the names in
    ACTION_NAMES to callables. ``changed`` is emitted at the display rate with the raw
    axes, for the live bars of the settings dialog.
    """
    changed = Signal(list)
    button_pressed = Signal(int)
    status_changed = Signal(str)

    TICK_MS = 16
    SMOOTH_SECONDS = .07      # time constant of the motion smoothing
    STALE_SECONDS = .25       # no packet for this long: treat the cap as released

    def __init__(self, window, workspace, actions, settings, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.workspace = workspace
        self.actions = dict(actions)
        self.settings = settings
        self.profile = Profile.load(settings)
        self.raw = [0.] * 6
        self.smooth = {channel: 0. for channel in CHANNELS}
        self.rotation_locked = False
        self.rotate_only = False
        self.last_packet = 0.
        self.last_tick = time.perf_counter()
        self.product = None
        self.reader = None
        self.listening = None           # callable(button index) while a button is being assigned
        self.recording = None           # list collecting raw samples during calibration
        self.last_button = None
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)      # the coarse default snaps to the 15.6 ms Windows tick: uneven frames
        self.timer.setInterval(self.TICK_MS)
        self.timer.timeout.connect(self.tick)

    # -- lifecycle
    def start(self):
        platform = os.environ.get('QT_QPA_PLATFORM', '')
        forced = os.environ.get('SLOTHCAD_SPACEMOUSE_FORCE') == '1'
        if platform in ('offscreen', 'minimal') and not forced:
            return False
        if WINDOWS:
            from PySide6.QtWidgets import QApplication
            self.reader = RawInputReader(self.window.winId(), self.feed_report, QApplication.instance())
            self.reader.block_wheel = self.device_active
        else:
            self.reader = SpnavReader(self.feed_axes, self.feed_button, self)
        ok = self.reader.start()
        if ok:
            self.timer.start()
        return ok

    def stop(self):
        self.timer.stop()
        if self.reader is not None:
            self.reader.stop()

    @property
    def connected(self):
        return bool(self.reader is not None and self.reader.available)

    def device_name(self):
        return PRODUCTS.get(self.product, 'SpaceMouse' if self.product else '')

    def toggle_rotation_lock(self):
        """The Rotate button: the view only pans and zooms until it is pressed again."""
        self.rotation_locked = not self.rotation_locked
        if self.rotation_locked:
            self.rotate_only = False
        self.status_changed.emit('Rotation locked' if self.rotation_locked else 'Rotation free')
        return self.rotation_locked

    def toggle_rotate_only(self):
        """The other Rotate button: the cap only turns the view (no pan, no zoom) until pressed again."""
        self.rotate_only = not self.rotate_only
        if self.rotate_only:
            self.rotation_locked = False
        return self.rotate_only

    def device_active(self):
        """The cap is (or was a moment ago) deflected."""
        return self.profile.enabled and (any(abs(v) > 5 for v in self.raw) or time.perf_counter() - self.last_packet < .4)

    # -- input
    def feed_report(self, product, report):
        """One HID report from the Windows reader."""
        self.product = product or self.product
        parsed = parse_report(report)
        if parsed is None:
            return
        kind = parsed[0]
        if kind == 'motion':
            self.raw[0:3] = [float(v) for v in parsed[1]]
            self.raw[3:6] = [float(v) for v in parsed[2]]
            self.touch()
        elif kind == 'translation':
            self.raw[0:3] = [float(v) for v in parsed[1]]
            self.touch()
        elif kind == 'rotation':
            self.raw[3:6] = [float(v) for v in parsed[1]]
            self.touch()
        elif kind == 'buttons':
            self.feed_buttons(parsed[1])

    def feed_axes(self, axes):
        self.raw = [float(v) for v in axes]
        self.touch()

    def touch(self):
        self.last_packet = time.perf_counter()
        if self.recording is not None:
            self.recording.append(list(self.raw))

    def feed_buttons(self, mask):
        previous = getattr(self, '_mask', 0)
        self._mask = mask
        changed = mask ^ previous
        for bit in range(32):
            if changed >> bit & 1:
                self.feed_button(bit + 1, bool(mask >> bit & 1))

    def feed_button(self, index, pressed):
        if not pressed:
            return
        self.last_button = index
        self.button_pressed.emit(index)
        if self.listening is not None:
            callback, self.listening = self.listening, None
            callback(index)
            return
        action = self.profile.buttons.get(str(index))
        function = self.actions.get(action) if action else None
        if function is not None and self.profile.enabled:
            function()

    # -- per frame
    def tick(self):
        now = time.perf_counter()
        dt = max(1e-4, min(.1, now - self.last_tick))
        self.last_tick = now
        if now - self.last_packet > self.STALE_SECONDS:
            self.raw = [0.] * 6
        self.changed.emit(list(self.raw))
        active = self.profile.enabled and self.window.isActiveWindow()
        target = to_motion(shape_axes(self.raw, self.profile), self.profile) if active else {}
        if self.rotation_locked:
            target['tilt'] = target['spin'] = 0.
        if self.rotate_only:
            target['pan_x'] = target['pan_y'] = target['zoom'] = 0.
        # Low-pass filter: packets arrive unevenly, the view must not stutter with them.
        alpha = 1. - math.exp(-dt / self.SMOOTH_SECONDS)
        smooth = self.smooth
        for channel in CHANNELS:
            smooth[channel] += (target.get(channel, 0.) - smooth[channel]) * alpha
        if any(abs(v) > 1e-4 for v in smooth.values()):
            self.workspace.apply_navigation(dict(smooth), dt)
        else:
            for channel in CHANNELS:
                smooth[channel] = 0.

    # -- calibration
    def record(self, seconds, finished):
        """Collect raw samples for a short while, then call ``finished(samples)``."""
        self.recording = []
        def done():
            samples, self.recording = self.recording or [], None
            finished(samples)
        QTimer.singleShot(int(seconds * 1000), done)

    def listen_for_button(self, callback):
        self.listening = callback

    def save(self):
        self.profile.save(self.settings)
