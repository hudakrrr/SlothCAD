"""Client for ``kernel_worker``: runs long, self-contained kernel jobs in a separate process.

``KERNEL.call(op, args, report)`` blocks the calling thread (normally a ``run_busy`` worker)
while waiting on a pipe, which does not hold Python's GIL, so the interface stays responsive
however long the job takes. The process is started on first use (or by ``warm_up``) and reused;
if it dies it is started again for the next job.
"""
import atexit
import io
import os
import pickle
import struct
import subprocess
import sys
import threading

from legacy_model import ModelError

WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kernel_worker.py')


def shape_bytes(shape):
    """A CadQuery shape (or workplane) as BREP bytes for the worker."""
    shape = shape.val() if hasattr(shape, 'val') else shape
    buffer = io.BytesIO()
    shape.exportBrep(buffer)
    return buffer.getvalue()


def item_bytes(items):
    """``Document.export_items`` output with each shape converted to BREP bytes."""
    return [(str(name), shape_bytes(shape), tuple(float(v) for v in rgb)) for name, shape, rgb in items]


class KernelProcess:
    def __init__(self):
        self.process = None
        self.lock = threading.Lock()

    def _python(self):
        from limit_search import _python
        return _python()

    def _ensure(self):
        if self.process is not None and self.process.poll() is None:
            return self.process
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.process = subprocess.Popen([self._python(), '-u', WORKER_SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0, creationflags=flags)
        return self.process

    def warm_up(self):
        """Start the process ahead of time so the first job does not wait for the kernel to load."""
        def start():
            try:
                with self.lock:
                    self._ensure()
            except Exception:
                pass
        threading.Thread(target=start, name='SlothCAD-kernel-warm-up', daemon=True).start()

    def _send(self, process, message):
        data = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
        process.stdin.write(struct.pack('<I', len(data)) + data)
        process.stdin.flush()

    def _receive(self, process):
        def exact(size):
            chunks = []
            while size:
                chunk = process.stdout.read(size)
                if not chunk:
                    return None
                chunks.append(chunk)
                size -= len(chunk)
            return b''.join(chunks)
        head = exact(4)
        if head is None:
            return None
        data = exact(struct.unpack('<I', head)[0])
        return None if data is None else pickle.loads(data)

    def call(self, op, args=None, report=None):
        with self.lock:
            process = self._ensure()
            try:
                self._send(process, {'op': op, 'args': args or {}})
                while True:
                    message = self._receive(process)
                    if message is None:
                        raise BrokenPipeError
                    if 'progress' in message:
                        if report:
                            report(*message['progress'])
                        continue
                    if 'error' in message:
                        if message.get('model'):
                            raise ModelError(message['error'])
                        raise RuntimeError(message['error'])
                    return message.get('result')
            except (BrokenPipeError, OSError, EOFError, pickle.UnpicklingError):
                self.stop()
                raise ModelError('The background CAD process stopped unexpectedly. Please try again.')

    def stop(self):
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                process.kill()
                process.wait(2)
            except Exception:
                pass


KERNEL = KernelProcess()
atexit.register(KERNEL.stop)
