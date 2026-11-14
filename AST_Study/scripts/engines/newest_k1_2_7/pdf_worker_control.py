"""Process-local cancellation; never reused when a new document run starts.

Only an explicit desktop --control-stdin flag enables the input channel. A
cancelled/closed desktop session can stop acknowledged background jobs before
its worker exits. No request is ever regenerated here.
"""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

_CANCEL=threading.Event()
_LOCK=threading.Lock()
_JOBS={}
_REQUESTED=set()
_STARTED=False
_INTENTS={}


def register_intent(key, callback):
    with _LOCK:_INTENTS[key]=callback
    if cancelled():_run(callback)


def cancelled():return _CANCEL.is_set()


def _run(callback):
    try:callback()
    except Exception:pass  # The normal response ledger retains unknown usage.


def cancel():
    _CANCEL.set()
    with _LOCK:
        intents=list(_INTENTS.values())
        work=[(key,fn)for key,fn in _JOBS.items()if key not in _REQUESTED]
        _REQUESTED.update(key for key,_ in work)
    # Persist the user's intent before slow network cleanup or worker termination.
    for callback in intents:_run(callback)
    if work:
        # A separate bounded cleanup lane; no network under either registry or
        # provider locks, and no dependency on the UI reading preview events.
        def cleanup():
            with ThreadPoolExecutor(max_workers=4,thread_name_prefix='study-stop')as pool:
                list(pool.map(_run,[fn for _,fn in work]))
        threading.Thread(target=cleanup,name='study-stop-jobs',daemon=True).start()


def register(key,callback):
    with _LOCK:_JOBS[key]=callback
    if cancelled():cancel()


def unregister(key):
    with _LOCK:_JOBS.pop(key,None)


def start(stream=None):
    global _STARTED
    with _LOCK:
        if _STARTED:return
        _STARTED=True
    def read():
        try:
            for line in (sys.stdin if stream is None else stream):
                if len(line)>4096:continue
                try:message=json.loads(line)
                except (ValueError,TypeError):continue
                if isinstance(message,dict)and message.get('command')=='cancel':cancel();return
        finally:cancel()  # Desktop closed or its control pipe disappeared.
    threading.Thread(target=read,name='study-desktop-control',daemon=True).start()
