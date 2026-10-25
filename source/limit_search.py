"""The largest fillet/chamfer size a selection can take, found once per selection.

``model.maximum_edge_size`` asks the kernel for up to ~20 trial builds one after the other, each of
which holds Python's interpreter lock, so the window cannot even repaint while it runs. Here the
trial sizes are tested by a few worker processes at once (several sizes per round, narrowing the
bracket by a factor of ``workers + 1`` each round), which is both several times faster and keeps
the interface alive. Small models, a missing worker or any failure fall back to the original search.
"""
import atexit
import itertools
import json
import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import model

WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'limit_worker.py')
MIN_FACES = 40          # smaller bodies are searched in-process: a trial costs milliseconds there
TRIAL_TIMEOUT = 90.     # seconds a round may take before unfinished sizes count as "does not build"
IDLE_SECONDS = 180.     # workers hold a kernel each; give the memory back when unused
PRECISION = .01         # relative width of the final bracket


def _python():
    """python.exe next to pythonw.exe: the windowless interpreter has no usable stdio."""
    executable = sys.executable
    if os.path.basename(executable).lower() == 'pythonw.exe':
        candidate = os.path.join(os.path.dirname(executable), 'python.exe')
        if os.path.exists(candidate):
            return candidate
    return executable


def worker_count():
    if os.environ.get('SLOTHCAD_LIMIT_WORKERS', '').isdigit():
        return max(0, int(os.environ['SLOTHCAD_LIMIT_WORKERS']))
    return max(2, min(4, (os.cpu_count() or 2) // 3))


class _Worker:
    def __init__(self):
        # Below normal priority: the search must never take processor time from the camera.
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)
        extra = {}
        if os.name != 'nt':
            extra['preexec_fn'] = lambda: os.nice(10)
        self.process = subprocess.Popen([_python(), '-u', WORKER_SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, bufsize=1, creationflags=flags, **extra)
        self.replies = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            if line.startswith('@@'):
                try:
                    self.replies.put(json.loads(line[2:]))
                except ValueError:
                    pass
        self.replies.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def alive(self):
        return self.process.poll() is None

    def stop(self):
        try:
            self.process.kill()
        except Exception:
            pass
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except Exception:
                pass


class Pool:
    def __init__(self):
        self.lock = threading.RLock()
        self.workers = []
        self.timer = None

    def ensure(self, count):
        with self.lock:
            self.workers = [w for w in self.workers if w.alive()]
            while len(self.workers) < count:
                self.workers.append(_Worker())
            self._touch()
            return list(self.workers)

    def _touch(self):
        if self.timer is not None:
            self.timer.cancel()
        self.timer = threading.Timer(IDLE_SECONDS, self.shutdown)
        self.timer.daemon = True
        self.timer.start()

    def shutdown(self):
        with self.lock:
            for worker in self.workers:
                try:
                    worker.send({'op': 'quit'})
                except Exception:
                    pass
                worker.stop()
            self.workers = []
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None

    def run_round(self, jobs, op='try'):
        """``jobs``: list of message dicts. Returns {id: bool}. Sizes that time out are False."""
        workers = self.ensure(max(1, min(len(jobs), worker_count())))
        with self.lock:
            self._touch()
        pending = {}
        for index, job in enumerate(jobs):
            worker = workers[index % len(workers)]
            worker.send(dict({'op': 'try'}, **job))
            pending.setdefault(id(worker), [worker, 0])[1] += 1
        results = {}
        deadline = time.monotonic() + TRIAL_TIMEOUT
        for worker, count in pending.values():
            for _ in range(count):
                remaining = deadline - time.monotonic()
                try:
                    reply = worker.replies.get(timeout=max(.05, remaining))
                except queue.Empty:
                    self.shutdown()          # a trial that never finishes: start over next time
                    break
                if reply is None:
                    break
                results[reply.get('id')] = bool(reply.get('ok'))
        return results


POOL = Pool()
atexit.register(POOL.shutdown)


def warm_up():
    """Start the worker processes in the background so the first search does not wait for them."""
    count = worker_count()
    if count <= 0:
        return
    threading.Thread(target=lambda: _quiet(POOL.ensure, count), daemon=True).start()


def _quiet(function, *args):
    try:
        return function(*args)
    except Exception:
        return None


def _search(result, kind, references, hint, progress, on_partial=None, options=None):
    """Parallel bracket search. Returns (largest working size, bounded)."""
    if not references:
        raise model.ModelError('Select at least one edge.')
    shape = result.val()
    box = shape.BoundingBox()
    diagonal = math.sqrt(float(box.xlen) ** 2 + float(box.ylen) ** 2 + float(box.zlen) ** 2)
    cap = max(1e-6, diagonal * 1.01)
    tiny = max(1e-7, cap * 1e-8)
    # The picks already carry their geometry (centre, length, direction, end points); the worker
    # finds the edges from that. Resolving them here would hold the interpreter lock for seconds.
    plain = [{key: value for key, value in reference.items() if key not in ('anchor', 'topology_role', 'body_id')}
             for reference in references]
    handle, path = tempfile.mkstemp(suffix='.brep', prefix='slothcad-limit-')
    os.close(handle)
    try:
        shape.exportBrep(path)
        key = uuid.uuid4().hex
        width = max(2, worker_count())
        counter = itertools.count()
        tested = {}

        def report(text):
            if progress is not None:
                progress(min(len(tested), 32), 32, text)

        def test(sizes, mode='single'):
            sizes = [s for s in sizes if s not in tested]
            jobs = [dict(id=next(counter), key=key, path=path, refs=plain, kind=kind, size=float(s), mode=mode, options=options or {}) for s in sizes]
            if jobs:
                report(f'Checking {kind} limit · {sizes[0]:g} mm')
                answers = POOL.run_round(jobs)
                for job in jobs:
                    tested[job['size']] = answers.get(job['id'], False)
            return None

        start = min(cap, max(tiny, float(hint) if math.isfinite(float(hint)) and float(hint) > 0 else min(1., cap)))
        # Round 1..n: geometric ladder around the hint until a working size lies below a failing one.
        low_k, high_k = -(width // 2), width - width // 2
        low = high = None
        for _ in range(12):
            ladder = [min(cap, max(tiny, start * 2. ** k)) for k in range(low_k, high_k)]
            test(sorted(set(ladder)))
            ordered = sorted(tested)
            failing = next((s for s in ordered if not tested[s]), None)
            if failing is not None:
                below = [s for s in ordered if s < failing and tested[s]]
                if below:
                    low, high = max(below), failing
                    break
                if failing <= tiny * 1.0001:
                    report(f'No valid {kind} size found')
                    return 0., True
                low_k, high_k = low_k - width, low_k          # nothing works yet: go smaller
                continue
            top = ordered[-1]
            if top >= cap * .999999:
                report(f'{kind.title()} limit is at least {cap:g} mm')
                return float(cap), False
            low_k, high_k = high_k, high_k + width            # everything works so far: go larger
        if low is None:
            raise RuntimeError('limit search did not converge')
        if on_partial is not None:
            on_partial(float(low))          # a size known to build: the arrow can be capped at once
        for _ in range(8):
            if (high - low) <= max(PRECISION * high, 1e-9):
                break
            points = [low + (high - low) * (i + 1) / (width + 1) for i in range(width)]
            test(points)
            for point in points:
                if tested.get(point):
                    low = max(low, point)
            if on_partial is not None:
                on_partial(float(low))
            above = [p for p in points if not tested.get(p) and p > low]
            if above:
                high = min(high, min(above))
        # The search above asked "does one operation on all edges build?". The real feature has
        # more strategies (other edge orders, repaired copy), so a few sizes above the answer are
        # tried the full way; whatever still builds raises the limit.
        extra = [min(cap, low * f) for f in (1.15, 1.4, 1.8)]
        extra = sorted({s for s in extra if s > low * 1.0001})
        if extra:
            before = dict(tested)
            for s in extra:
                tested.pop(s, None)
            test(extra, mode='full')
            for s in extra:
                if tested.get(s):
                    low = max(low, s)
                else:
                    break
        report(f'Maximum {kind} size ≈ {low:g} mm')
        return float(low), True
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def maximum_edge_size(result, kind, references, hint=1.0, progress=None, on_partial=None, options=None):
    """Drop-in replacement for ``model.maximum_edge_size``; same result, searched in parallel."""
    if result is None:
        raise model.ModelError('Create a body first.')
    count = worker_count()
    if count > 0 and not os.environ.get('SLOTHCAD_LIMIT_SERIAL'):
        try:
            if len(result.val().Faces()) >= MIN_FACES:
                return _search(result, kind, references, hint, progress, on_partial, options)
        except model.ModelError:
            raise
        except Exception:
            POOL.shutdown()
    return model.maximum_edge_size(result, kind, references, hint=hint, progress=progress, options=options)


def history_limits(prefix, trial, field, sign, diagonal, current, on_partial=None):
    """(lowest, highest) value of ``field`` for which ``prefix + [trial]`` still builds.

    ``None`` on a side means every value up to ``diagonal`` builds. The history before the trial
    feature is rebuilt once in each worker process; values are then tested several at a time.
    Returns ``NotImplemented`` when the workers are unavailable (the caller searches in-process).
    """
    count = worker_count()
    if count <= 0 or os.environ.get('SLOTHCAD_LIMIT_SERIAL'):
        return NotImplemented
    handle, path = tempfile.mkstemp(suffix='.json', prefix='slothcad-history-')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            from expressions import active_parameters
            json.dump(dict(features=prefix, parameters=dict(active_parameters())), out, default=str)
        with open(path, 'rb') as source:
            import hashlib
            key = hashlib.sha1(source.read()).hexdigest()
        counter = itertools.count()
        width = max(2, count)

        def test(values):
            jobs = []
            for value in values:
                feature = json.loads(json.dumps(trial, default=str))
                feature[field] = value * sign
                jobs.append(dict(id=next(counter), op='history', key=key, path=path, feature=feature, value=value))
            answers = POOL.run_round(jobs, op='history')
            return {job['value']: answers.get(job['id'], False) for job in jobs}

        def reach(direction):
            """Largest working magnitude in one direction, or None when all builds up to diagonal."""
            start = max(1., current, diagonal / 50.)
            ladder = []
            value = start
            while value <= diagonal:
                ladder.append(value)
                value *= 2.
            good, bad = 0., None
            for begin in range(0, len(ladder), width):
                chunk = ladder[begin:begin + width]
                answers = test([direction * v for v in chunk])
                for v in chunk:
                    if answers.get(direction * v):
                        good = v
                    else:
                        bad = v
                        break
                if bad is not None:
                    break
            if bad is None:
                return None
            if on_partial is not None:
                on_partial(direction, good)
            for _ in range(6):
                if bad - good <= max(.01 * bad, 1e-6):
                    break
                points = [good + (bad - good) * (i + 1) / (width + 1) for i in range(width)]
                answers = test([direction * p for p in points])
                for point in points:
                    if answers.get(direction * point):
                        good = max(good, point)
                above = [p for p in points if not answers.get(direction * p) and p > good]
                if above:
                    bad = min(bad, min(above))
                if on_partial is not None:
                    on_partial(direction, good)
            return good

        return reach(-1.), reach(1.)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
