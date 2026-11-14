"""Offline native cross-process slot check, also runnable with Windows embedded Python."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time


def _worker(directory):
    import pdf_api_slots as slots
    slots.MAX_PARALLEL_REQUESTS = 2
    print('ready', flush=True)
    with slots.api_slot(directory=directory):
        print('entered', flush=True)
        if sys.stdin.readline().strip() != 'release':
            raise RuntimeError('offline slot owner lost its controller')
    print('released', flush=True)


def check_parallel_slots(runtime):
    """Hold two OS locks, prove peers wait, then drain all four real processes."""
    runtime = Path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    events = queue.Queue()
    processes = []
    readers = []
    ready, entered, released = set(), set(), set()
    deadline = time.monotonic() + 60

    def read(index, process):
        for line in process.stdout:
            events.put((index, line.strip()))
        events.put((index, 'closed'))

    def receive(timeout=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('offline parallel slot check timed out')
        index, event = events.get(timeout=max(0, min(remaining, timeout)) if timeout is not None else remaining)
        if event == 'ready': ready.add(index)
        elif event == 'entered': entered.add(index)
        elif event == 'released': released.add(index)
        elif event == 'closed' and index not in released:
            raise RuntimeError('offline parallel slot worker failed')
        return index, event

    def release(index):
        processes[index].stdin.write('release\n')
        processes[index].stdin.flush()

    with tempfile.TemporaryDirectory(prefix='parallel-check-', dir=runtime) as folder:
        try:
            env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
            for index in range(4):
                process = subprocess.Popen([sys.executable, '-B', '-u', str(Path(__file__).resolve()),
                    '--worker', '--directory', folder], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=env,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                processes.append(process)
                reader = threading.Thread(target=read, args=(index, process), daemon=True)
                reader.start();readers.append(reader)
            while len(ready) < 4 or len(entered) < 2: receive()
            # Every contender is running; neither extra process may enter while both locks are held.
            quiet_until = time.monotonic() + .25
            while time.monotonic() < quiet_until:
                try: receive(quiet_until - time.monotonic())
                except queue.Empty: break
            if len(entered) != 2:
                raise RuntimeError('cross-process slot limit was exceeded')
            released_first = min(entered);release(released_first)
            while len(entered) < 3: receive()
            # Release all current owners except the already released process. Each stdin is used once.
            sent = {released_first}
            for index in sorted(entered - sent): release(index);sent.add(index)
            while len(entered) < 4: receive()
            for index in sorted(entered - sent): release(index);sent.add(index)
            while len(released) < 4: receive()
            for process in processes:
                if process.wait(timeout=max(1, deadline-time.monotonic())) != 0:
                    raise RuntimeError('offline parallel slot worker exited unsuccessfully')
        finally:
            for process in processes:
                if process.poll() is None: process.kill()
            for process in processes:
                process.wait(timeout=5)
                if process.stdin: process.stdin.close()
            for reader in readers: reader.join(timeout=2)
            for process in processes:
                if process.stdout: process.stdout.close()
    return {'status':'PASS', 'workers':4, 'slotLimit':2, 'blockedUntilRelease':True,
            'completed':4, 'nativeLock':'msvcrt' if os.name=='nt' else 'fcntl', 'remoteRequests':0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--worker', action='store_true')
    parser.add_argument('--directory', type=Path, required=True);args=parser.parse_args()
    if args.worker: _worker(args.directory)
    else: print(json.dumps(check_parallel_slots(args.directory)), flush=True)
