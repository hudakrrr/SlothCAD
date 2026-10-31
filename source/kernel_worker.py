"""Persistent worker process for long, self-contained CAD kernel jobs (exports, drawings, analysis).

The CAD kernel keeps Python's GIL for the whole of a kernel call (writing a STEP file of a big
body takes seconds), and with PySide every event the interface handles needs the GIL too, so a
long kernel call in *any* thread of the app freezes the window. Jobs that only need shapes in and
a file or numbers out therefore run here, in a separate process that is started once and reused.

Protocol (binary, stdin/stdout): every message is a 4-byte little-endian length followed by a
pickle. Requests are ``{'op': name, 'args': {...}}``; replies are ``{'progress': (done, total,
text)}`` any number of times, then ``{'result': value}`` or ``{'error': text, 'model': bool}``.
Shapes travel as BREP bytes (see ``kernel_process.shape_bytes``).
"""
import io
import os
import pickle
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _read(stream):
    head = stream.read(4)
    if len(head) < 4:
        return None
    size, = struct.unpack('<I', head)
    data = stream.read(size)
    return pickle.loads(data) if len(data) == size else None


def _write(stream, message):
    data = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(struct.pack('<I', len(data)) + data)
    stream.flush()


def _shape(data):
    import cadquery as cq
    return cq.Shape.importBrep(io.BytesIO(data))


def _items(raw):
    return [(name, _shape(data), tuple(rgb)) for name, data, rgb in raw]


def _compound(shapes):
    import cadquery as cq
    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def export(args, progress):
    from exchange import export_items_file
    progress(0, 0, 'Reading shapes…')
    items = _items(args['items'])
    progress(0, 0, 'Writing ' + args['label'] + ' file…')
    export_items_file(items, args['path'], args['tolerance'], args['angular_tolerance'], args.get('colors', True))


def drawing(args, progress):
    from drawing import export_dxf, export_svg
    progress(0, 0, 'Reading shapes…')
    shape = _compound([item[1] for item in _items(args['items'])])
    progress(0, 0, 'Projecting views…')
    o = args['options']
    if args['svg']:
        return export_svg(args['path'], shape, o['views'], o['hidden'], o['scale'], args['title'])
    return export_dxf(args['path'], shape, o['views'], o['hidden'], o['scale'], o['dimensions'], args['title'])


def mass(args, progress):
    from analysis import mass_properties
    shapes = [_shape(data) for data in args['shapes']]
    progress(0, 0, 'Computing mass properties…')
    return mass_properties(shapes, args.get('density', 1.))


def interference(args, progress):
    from analysis import interferences
    named = [(name, _shape(data)) for name, data in args['shapes']]
    progress(0, 0, 'Checking interference…')
    return interferences(named)


OPERATIONS = {'ping': lambda args, progress: True, 'export': export, 'drawing': drawing, 'mass': mass,
              'interference': interference}


def main():
    requests = sys.stdin.buffer
    replies = sys.stdout.buffer
    sys.stdout = sys.stderr          # stray prints from libraries must not corrupt the protocol
    import cadquery  # noqa: F401  (load the kernel up front, while nobody waits for it)
    from legacy_model import ModelError
    while True:
        message = _read(requests)
        if message is None or message.get('op') == 'quit':
            break
        progress = lambda done, total, text='': _write(replies, {'progress': (int(done), int(total), str(text))})
        try:
            result = OPERATIONS[message['op']](message.get('args') or {}, progress)
            _write(replies, {'result': result})
        except Exception as error:
            _write(replies, {'error': str(error) or type(error).__name__, 'model': isinstance(error, ModelError)})


if __name__ == '__main__':
    main()
