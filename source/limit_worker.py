"""Worker process for ``limit_search``: tries fillet/chamfer sizes on a body it was handed.

Run as ``python limit_worker.py``. One JSON message per input line, one ``@@``-prefixed JSON
reply per message on stdout (anything else a library prints goes to stderr).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    reply_stream = sys.stdout
    sys.stdout = sys.stderr
    import cadquery as cq
    import model
    from references import match_shape

    cache = {}
    history = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = {'id': message.get('id')}
        try:
            operation = message.get('op')
            if operation == 'ping':
                reply['ok'] = True
            elif operation == 'quit':
                break
            elif operation == 'history':
                # Does the feature history build with this trial feature appended? The history before
                # it is built once per search and kept; only the trial feature is rebuilt.
                key = message['key']
                if key not in history:
                    history.clear()
                    with open(message['path'], encoding='utf-8') as handle:
                        document = json.load(handle)
                    # Older jobs held just the feature list; newer ones carry the parameter table too.
                    features, parameters = (document['features'], document.get('parameters')) if isinstance(document, dict) else (document, None)
                    history[key] = (features, model.build_state(features, parameters=parameters), parameters)
                features, state, parameters = history[key]
                try:
                    model.build_state(features + [message['feature']], start_state=state, start_index=len(features), parameters=parameters)
                    reply['ok'] = True
                except Exception:
                    reply['ok'] = False
            elif operation == 'try':
                key = message['key']
                if key not in cache:
                    cache.clear()
                    shape = cq.Shape.importBrep(message['path'])
                    cache[key] = cq.Workplane('XY').newObject([shape])
                result = cache[key]
                available = list(result.val().Edges())
                picked = []
                for reference in message['refs']:
                    edge, _ = match_shape(result, reference, 'edge', available)
                    picked.append(edge)
                    available = [e for e in available if not e.isSame(edge)]
                try:
                    if message.get('mode') == 'single':
                        # One operation on all edges, judged only where it changed the body: the cheap
                        # answer to "does this size build?" (no fallback orderings, no repairs).
                        solid = result.findSolid()
                        size = float(message['size'])
                        options = message.get('options') or {}
                        ratio = options.get('ratio')
                        if message['kind'] == 'fillet':
                            raw = solid.fillet(size, picked) if ratio is None else model._variable_fillet(solid, picked, size, size * ratio)
                        elif ratio is None:
                            raw = solid.chamfer(size, None, picked)
                        elif options.get('flip'):
                            raw = solid.chamfer(size * ratio, size, picked)
                        else:
                            raw = solid.chamfer(size, size * ratio, picked)
                        reply['ok'] = bool(model._edge_trial_is_valid_fast(result, result.newObject([raw])))
                    else:
                        trial = model.apply_edge_operation(result, picked, message['kind'], float(message['size']), quick=True,
                                                           **(message.get('options') or {}))
                        reply['ok'] = trial is not None and trial.val() is not None
                except Exception:
                    reply['ok'] = False
            else:
                reply['error'] = 'unknown operation'
        except Exception as error:
            reply['error'] = str(error)
        reply_stream.write('@@' + json.dumps(reply) + '\n')
        reply_stream.flush()


if __name__ == '__main__':
    main()
