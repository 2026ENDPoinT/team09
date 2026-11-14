"""Explicit, short paid connectivity check for Soniox and Daglo.

Never prints keys or transcripts. Replays at microphone speed so streaming
providers receive a realistic cadence. Run only with --allow-paid-test.
"""
import argparse
from pathlib import Path
from types import SimpleNamespace
import time
import wave

from live_streams import StreamWorker


class Summary:
    def __init__(self):
        self.counts = {}
        self.last_status = {}
        self.status_history = {}

    def emit(self, kind, model='all', frame_end=0, text='', **details):
        self.counts[(model, kind)] = self.counts.get((model, kind), 0) + 1
        if kind in ('STATUS', 'ERROR', 'DONE'):
            self.last_status[model] = text
            self.status_history.setdefault(model, []).append((kind, text))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('audio', type=Path)
    parser.add_argument('--allow-paid-test', action='store_true')
    parser.add_argument('--seconds', type=float, default=6)
    parser.add_argument('--models', choices=['soniox', 'daglo', 'both'], default='both')
    args = parser.parse_args()
    if not args.allow_paid_test or not 0 < args.seconds <= 10:
        parser.error('Explicit --allow-paid-test and 0 < --seconds <= 10 required')
    summary = Summary()
    settings = SimpleNamespace(allow_upload=True, language='ko', prompt='')
    names = ('soniox', 'daglo') if args.models == 'both' else (args.models,)
    workers = [StreamWorker(name, settings, summary) for name in names]
    for worker in workers:
        worker.ready.wait(10)
    if any(worker.failed.is_set() for worker in workers):
        for worker in workers:
            worker.finished.set()
        raise SystemExit('준비 실패: ' + repr(summary.last_status))
    with wave.open(str(args.audio), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise SystemExit('16 kHz mono PCM16 WAV required')
        for _ in range(round(args.seconds * 10)):
            block = source.readframes(1600)
            if not block:
                break
            for worker in workers:
                worker.offer(block)
            time.sleep(.1)
    for worker in workers:
        worker.finished.set()
    for worker in workers:
        worker.thread.join(25)
    for worker in workers:
        print(worker.name, 'events=', summary.counts.get((worker.name, 'STREAM'), 0),
              'state=', summary.last_status.get(worker.name, '응답 없음'),
              'running=', worker.thread.is_alive())
        print('status_history=', summary.status_history.get(worker.name, []))


if __name__ == '__main__':
    main()
