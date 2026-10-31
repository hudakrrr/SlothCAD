"""Worker process for importing STEP, IGES and mesh files.

Run as ``python exchange_worker.py <file>``. The CAD kernel holds Python's GIL during long calls
(sewing a mesh can take seconds), so imports run here instead of in a thread of the app: the
user interface stays responsive and the import can be cancelled by ending this process.

Every message is one ``@@``-prefixed JSON line on stdout (anything a library prints goes to
stderr): ``{"stage": text, "start": a, "end": b, "estimate": seconds, "count": n}``
(``{count}`` in the text is replaced by ``n``), ``{"at": fraction}``,
then ``{"result": feature}`` or ``{"error": message}``.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    reply_stream = sys.stdout
    sys.stdout = sys.stderr

    def send(message):
        reply_stream.write('@@' + json.dumps(message) + '\n')
        reply_stream.flush()

    class Progress:
        def __init__(self):
            self.last = -1.

        def stage(self, text, start, end, estimate=0., count=None):
            send({'stage': text, 'start': float(start), 'end': float(end), 'estimate': float(estimate), 'count': count})

        def at(self, fraction):
            # Only send visible steps (0.2 %), so a 60 000 triangle mesh does not flood the pipe.
            if fraction - self.last >= .002 or fraction >= 1:
                self.last = fraction
                send({'at': float(fraction)})

    try:
        send({'stage': 'Starting the CAD kernel…', 'start': 0., 'end': 0., 'estimate': 0.})
        from exchange import import_model
        send({'result': import_model(sys.argv[1], Progress())})
    except Exception as error:
        send({'error': str(error) or type(error).__name__})


if __name__ == '__main__':
    main()
