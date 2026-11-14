"""Local timing only; never include document contents, credentials or image data."""
import functools
import json
import os
from pathlib import Path
import threading
import time
from contextlib import contextmanager

_lock = threading.Lock()

def record(folder, stage, started, **fields):
    row = dict(version=1, atMs=int(time.time()*1000), pid=os.getpid(),
               thread=threading.current_thread().name, stage=stage,
               durationSeconds=round(time.perf_counter()-started, 6), **fields)
    try:
        from synesis_paths import io_path
        path = Path(folder)/'performance.jsonl'
        with _lock:
            with open(io_path(path), 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=True)+'\n')
    except (OSError, ValueError):
        pass  # Diagnostics must never fail a paid operation.

@contextmanager
def measure(folder, stage, **fields):
    started=time.perf_counter()
    outcome='ok'
    try:
        yield
    except BaseException:
        outcome='error'
        raise
    finally:
        record(folder, stage, started, outcome=outcome, **fields)

def timed(stage):
    def decorate(function):
        @functools.wraps(function)
        def call(folder, *args, **kwargs):
            with measure(folder, stage):
                return function(folder, *args, **kwargs)
        return call
    return decorate
