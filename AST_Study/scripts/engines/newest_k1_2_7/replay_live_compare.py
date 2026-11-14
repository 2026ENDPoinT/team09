"""Developer validation: replay an existing authorized WAV at capture speed.

This validates the live worker without recording or sending new microphone audio.
Default local-only. Paid runs additionally require --allow-upload.
"""
import argparse
import base64
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave

from asr_compare import inspect_audio


def main():
    # Windows redirected consoles may default to cp949, which cannot print model punctuation.
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', default='local')
    parser.add_argument('--allow-upload', action='store_true')
    parser.add_argument('--balance-levels', action='store_true')
    parser.add_argument('--max-seconds', type=int, default=8)
    args = parser.parse_args()
    duration, digest = inspect_audio(args.audio)
    print(f'Replay source {duration:.3f}s SHA256 {digest}', flush=True)
    command = [sys.executable, '-u', '-X', 'utf8', str(Path(__file__).with_name('live_compare.py')),
               '--models', args.models, '--output', str(args.output), '--max-seconds', str(args.max_seconds)]
    if args.allow_upload:
        command.append('--allow-upload')
    if args.balance_levels:
        command.append('--balance-levels')
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ready = threading.Event()
    def read():
        for line in process.stdout:
            fields = line.decode('utf-8').strip().split('\t')
            if len(fields) < 3:
                continue
            kind, model, end = fields[:3]
            message = base64.b64decode(fields[3]).decode('utf-8') if len(fields) == 4 else ''
            print(kind, model, end, message, flush=True)
            if kind == 'READY':
                ready.set()
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    if not ready.wait(100):
        process.terminate()
        raise RuntimeError('Worker not ready; no audio sent')
    start = time.monotonic()
    count = 0
    try:
        with wave.open(str(args.audio), 'rb') as source:
            while pcm := source.readframes(1600):
                count += len(pcm)//2
                # A microphone read returns only after these samples exist.
                time.sleep(max(0, start + count/16000-time.monotonic()))
                process.stdin.write(pcm)
                process.stdin.flush()
    finally:
        process.stdin.close()
    code = process.wait(timeout=145)
    reader.join(2)
    return code


if __name__ == '__main__':
    sys.exit(main())
