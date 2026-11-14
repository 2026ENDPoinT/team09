"""Bounded, near-live comparison. stdin is shared 16 kHz mono PCM16, NOT a filename.

One continuous recording feeds short cloud windows and grouped local windows.
No hidden downloads, speech trimming, paid retries, or extra correction requests.
Cloud-only operation needs only Python's standard library.
"""
import argparse
from array import array
import base64
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import wave
import uuid

from asr_compare import api_key, cloud_transcribe, wav_bytes, normalize_pcm
from live_streams import StreamWorker

ROOT = Path(__file__).resolve().parent.parent
MODELS = {'local': 'faster-whisper', 'mini': 'gpt-4o-mini-transcribe',
          'full': 'gpt-4o-transcribe', 'soniox': 'stt-rt-v5', 'daglo': 'Realtime STT'}
RATE = 16000
DAILY_LIMIT = 0.195  # $0.005 safety margin below the user's $0.20 daily test cap.
PRIOR_ALLOWANCE = 0.015  # Covers known pre-v2 tests (~$0.010773) plus headroom.
REQUEST_RESERVATION = 0.0025  # Held until a successful response has valid usage.


def usage_cost(model, usage):
    """Provider usage estimate, NOT an invoice. Unknown/malformed usage stays reserved."""
    if model not in (MODELS['mini'], MODELS['full']) or not isinstance(usage, dict) or usage.get('type') != 'tokens':
        return None
    counts = [usage.get('input_tokens'), usage.get('output_tokens')]
    if any(type(value) is not int or value < 0 for value in counts) or sum(counts) == 0:
        return None
    input_rate, output_rate = (1.25, 5) if model == MODELS['mini'] else (2.5, 10)
    return round((counts[0]*input_rate + counts[1]*output_rate)/1e6, 10)


class LevelBalancer:
    """Optional bounded level experiment, shared by ALL lanes. No trimming.

Operate on 100 ms blocks, smooth gain, max +12 dB, and never exceed -1 dBFS peak.
This is not noise removal and can amplify quiet noise; OFF by default.
"""
    def __init__(self):
        self.gain = None

    def process(self, pcm):
        import math
        samples = array('h', pcm)
        if sys.byteorder != 'little':
            samples.byteswap()
        _, info = normalize_pcm(pcm)
        peak = max((abs(x) for x in samples), default=0)
        headroom = max(0, -1 - 20 * math.log10(max(1, peak) / 32768))
        start = min(info['gain_db'] if self.gain is None else self.gain, headroom)
        self.gain = min(headroom, start + .2*(info['gain_db']-start))
        result = array('h', (max(-32768, min(32767, round(x * 10 ** (
            (start + (self.gain-start)*(i+1)/len(samples))/20)))) for i, x in enumerate(samples)))
        if sys.byteorder != 'little':
            result.byteswap()
        return result.tobytes()


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int
    core_start: int
    end: int
    pcm: bytes
    captured: float


class Segmenter:
    """Cut after a pause (>=2 s core), otherwise at 4 s. Keep 0.5 s left context.

Silence only chooses boundaries; not one source sample is removed. The very last
tail is emitted even if tiny. Overlap text remains explicit in the comparison UI.
"""
    def __init__(self, silence_db=-42, pause_ms=500, min_seconds=2, max_seconds=4, context_seconds=0.5):
        if not (-80 <= silence_db <= -10 and 200 <= pause_ms <= 2000
                and 1 <= min_seconds <= max_seconds <= 8 and 0 <= context_seconds <= 2):
            raise ValueError('Invalid segmentation settings')
        self.silence_db = silence_db
        self.pause_frames = round(pause_ms * RATE / 1000)
        self.min_frames = round(min_seconds * RATE)
        self.max_frames = round(max_seconds * RATE)
        self.context_bytes = round(context_seconds * RATE) * 2
        self.pending = bytearray()
        self.context = b''
        self.core_start = 0
        self.silence = 0
        self.index = 0

    def feed(self, pcm):
        if len(pcm) % 2:
            raise ValueError('Incomplete PCM sample')
        self.pending.extend(pcm)
        samples = array('h', pcm)
        if sys.byteorder != 'little':
            samples.byteswap()
        quiet = sum(v * v for v in samples) / max(1, len(samples)) < (32768 * 10 ** (self.silence_db / 20)) ** 2
        self.silence = self.silence + len(samples) if quiet else 0
        count = len(self.pending) // 2
        if count >= self.max_frames or (count >= self.min_frames and self.silence >= self.pause_frames):
            return self.flush()
        return None

    def flush(self):
        if not self.pending:
            return None
        self.index += 1
        end = self.core_start + len(self.pending) // 2
        chunk = Chunk(self.index, self.core_start - len(self.context) // 2,
                      self.core_start, end, self.context + bytes(self.pending), time.monotonic())
        self.context = chunk.pcm[-self.context_bytes:] if self.context_bytes else b''
        self.core_start = end
        self.pending.clear()
        self.silence = 0
        return chunk


class LocalWindowAggregator:
    """Group complete short core windows for slower CPU inference, without gaps."""
    def __init__(self, target_seconds=6, context_seconds=0.5):
        self.target_bytes = round(target_seconds * RATE) * 2
        self.context_bytes = round(context_seconds * RATE) * 2
        self.pending = bytearray()
        self.context = b''
        self.core_start = 0
        self.index = 0

    def feed(self, short_chunk):
        if short_chunk.core_start != self.core_start + len(self.pending) // 2:
            raise ValueError('Local windows must cover consecutive core samples')
        self.pending.extend(short_chunk.pcm[(short_chunk.core_start-short_chunk.start)*2:])
        if len(self.pending) >= self.target_bytes:
            return self.flush()
        return None

    def flush(self):
        if not self.pending:
            return None
        self.index += 1
        end = self.core_start + len(self.pending) // 2
        chunk = Chunk(self.index, self.core_start - len(self.context) // 2,
                      self.core_start, end, self.context + bytes(self.pending), time.monotonic())
        self.context = chunk.pcm[-self.context_bytes:] if self.context_bytes else b''
        self.core_start = end
        self.pending.clear()
        return chunk


class Budget:
    """Conservative local test allowance, not an account-wide billing hard limit.

    Reserve $0.0025 PER request; settle successful valid usage only. Keep $0.015
    daily headroom for earlier/manual tests. An exclusive process lock prevents two
    live labs racing. OS releases the lock on crashes; reservations stay persisted.
    Corrupt state fails closed.
"""
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = directory / 'live-budget.lock'
        self.lock_file = self.lock_path.open('a+b')
        try:
            if self.lock_file.tell() == 0:
                self.lock_file.write(b'0')
                self.lock_file.flush()
            self.lock_file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise RuntimeError('Another live cloud test is running; no concurrent paid test allowed') from None
        self.mutex = threading.Lock()
        self.directory = directory
        self.receipts = {}

    @staticmethod
    def save(path, data):
        temp = path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as target:
            json.dump(data, target, indent=2)
            target.flush()
            os.fsync(target.fileno())
        temp.replace(path)

    @staticmethod
    def settle_entry(data, entry, usage):
        cost = usage_cost(entry['model'], usage)
        if cost is None or entry.get('status') == 'settled':
            return False
        # Retain original reservation for audit; only the charge against the cap changes.
        previous = entry.get('accounted_usd', entry['reserved_usd'])
        entry.update(status='settled', usage=usage, estimated_cost_usd=cost, accounted_usd=cost)
        data['reserved_usd'] = round(data['reserved_usd'] - previous + cost, 10)
        return True

    def settle(self, request_id, usage):
        with self.mutex:
            path = self.receipts[request_id]  # Original request day, even across midnight.
            data = json.loads(path.read_text('utf-8'))
            entry = next(e for e in data['requests'] if e.get('request_id') == request_id)
            if self.settle_entry(data, entry, usage):
                self.save(path, data)
            return data['reserved_usd']

    def reserve(self, model, seconds, request_id=None):
        if seconds > 10 or seconds <= 0:
            raise ValueError('Budget only permits requests up to 10 seconds including context')
        with self.mutex:
            day = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
            # Preserve existing v2 request/settlement history when the cap changes.
            # PRIOR_ALLOWANCE conservatively covers known earlier tests.
            path = self.directory / (day + '-v2.json')
            data = json.loads(path.read_text('utf-8')) if path.exists() else {'reserved_usd': PRIOR_ALLOWANCE,
                'policy': 'total-test-cap-0.20', 'prior_allowance_usd': PRIOR_ALLOWANCE, 'requests': []}
            used = float(data['reserved_usd'])
            if not PRIOR_ALLOWANCE <= used <= DAILY_LIMIT or used + REQUEST_RESERVATION > DAILY_LIMIT + 1e-9:
                raise RuntimeError('오늘 비용 한도 도달 · 정산 추정액과 미확정 예약액 기준 · 녹음은 계속됨')
            request_id = request_id or uuid.uuid4().hex
            if any(e.get('request_id') == request_id for e in data['requests']):
                raise ValueError('Duplicate budget request id')
            data['reserved_usd'] = round(used + REQUEST_RESERVATION, 10)
            data['policy'] = 'total-test-cap-0.20'
            data['requests'].append({'model': model, 'seconds': seconds, 'reserved_usd': REQUEST_RESERVATION,
                                     'request_id': request_id, 'status': 'reserved',
                                     'time': datetime.now(timezone.utc).isoformat()})
            self.save(path, data)  # persisted BEFORE the billable call
            self.receipts[request_id] = path
            return data['reserved_usd']

    def close(self):
        self.lock_file.close()


class Events:
    def __init__(self, folder):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=False)
        self.file = (folder / 'events.jsonl').open('x', encoding='utf-8')
        self.lock = threading.Lock()

    def emit(self, kind, model='all', frame_end=0, text='', **details):
        with self.lock:
            if self.file.closed:
                return  # A timed-out preparation thread may finish after session shutdown.
            event = dict(kind=kind, model=model, end_ms=round(frame_end * 1000 / RATE), text=text, **details)
            self.file.write(json.dumps(event, ensure_ascii=False) + '\n')
            self.file.flush()
            encoded = base64.b64encode(text.encode('utf-8')).decode('ascii')
            print(f'{kind}\t{model}\t{event["end_ms"]}\t{encoded}', flush=True)


class Worker:
    def __init__(self, name, args, events, budget):
        self.name, self.args, self.events, self.budget = name, args, events, budget
        self.queue = queue.Queue(maxsize=3)
        self.ready = threading.Event()
        self.failed = threading.Event()
        self.finished = threading.Event()
        self.thread = threading.Thread(target=self.run, name='stt-' + name, daemon=True)
        self.thread.start()

    def offer(self, chunk):
        if self.failed.is_set():
            self.events.emit('SKIPPED', self.name, chunk.end, '인식 중단 상태 · 해당 구간 미처리', chunk=chunk.index)
            return
        try:
            self.queue.put_nowait(chunk)
        except queue.Full:
            self.failed.set()
            self.events.emit('ERROR', self.name, chunk.end,
                             '처리가 녹음을 따라가지 못함 · 이 모델 중단, 원본 녹음 유지', chunk=chunk.index)

    def run(self):
        current = None
        try:
            self.events.emit('STATUS', self.name, text='모델 준비 중…')
            local = None
            key = None
            if self.name == 'local':
                if not (self.args.local_model / 'model.bin').is_file():
                    raise RuntimeError('로컬 모델 없음 · 체크 해제하면 클라우드만 사용 가능')
                from faster_whisper import WhisperModel
                local = WhisperModel(str(self.args.local_model), device='cpu', compute_type='int8',
                                     cpu_threads=4, local_files_only=True)
            else:
                if not self.args.allow_upload:
                    raise RuntimeError('클라우드 전송 동의 없음')
                key = api_key('OPENAI_API_KEY')
                if not key:
                    raise RuntimeError('.env의 OPENAI_API_KEY가 없음')
            self.events.emit('STATUS', self.name, text=('로컬 모델 로딩 완료 · 녹음 시작 대기' if local is not None
                             else '클라우드 키 설정 확인 · 서버 응답은 첫 요청 시 확인'))
            self.ready.set()
            while not self.failed.is_set():
                try:
                    current = self.queue.get(timeout=0.1)
                except queue.Empty:
                    if self.finished.is_set():
                        break
                    continue
                start_time = time.monotonic()
                self.events.emit('STATUS', self.name, current.end,
                                 f'구간 {current.index} 인식 중 · 대기 {self.queue.qsize()}개')
                usage = {}
                request_id = None
                if local is not None:
                    import numpy as np
                    audio = np.frombuffer(current.pcm, dtype='<i2').astype(np.float32) / 32768
                    segments, _ = local.transcribe(audio, language=None if self.args.language == 'auto' else self.args.language,
                        beam_size=3, vad_filter=False, condition_on_previous_text=False,
                        initial_prompt=self.args.prompt or None)
                    text = ' '.join(segment.text.strip() for segment in segments).strip()
                else:
                    request_id = uuid.uuid4().hex
                    reserved = self.budget.reserve(MODELS[self.name], len(current.pcm) / (RATE * 2), request_id=request_id)
                    self.events.emit('BUDGET', self.name, current.end,
                                     f'오늘 한도 반영액 ${reserved:.4f} / ${DAILY_LIMIT:.3f} · 요청 비용 임시 예약', request_id=request_id)
                    prompt = ('Transcribe every audible utterance in order, in its original language. '
                              'Do not summarize, omit speech, or invent inaudible words.\n' + self.args.prompt)
                    text = cloud_transcribe('openai', MODELS[self.name], self.args.language,
                                            prompt, wav_bytes(current.pcm), key, usage_sink=usage)
                done = time.monotonic()
                delay, processing = done - current.captured, done - start_time
                estimated = usage_cost(MODELS[self.name], usage)
                caption = (f'[{current.start / RATE:.2f}–{current.end / RATE:.2f}초 | '
                           f'입력 수신 후 {delay:.1f}초 · 처리 {processing:.1f}초]\n'
                           + (text or '[빈 결과 · 무음인지 누락인지 녹음 확인 필요]'))
                self.events.emit('RESULT', self.name, current.end, caption, chunk=current.index,
                    start=current.start, core_start=current.core_start, end=current.end,
                    transcript=text, queue_seconds=start_time-current.captured,
                    processing_seconds=processing, lag_seconds=delay,
                    first_sample_to_result_seconds=delay + (current.end-current.start)/RATE,
                    input_sha256=hashlib.sha256(current.pcm).hexdigest(), usage=usage,
                    estimated_cost_usd=estimated, accuracy_verified=False, request_id=request_id)
                # The fourth UI lane consumes plain per-chunk text, not the diagnostic RESULT.
                # It replaces a draft only for this exact core window; no extra API call.
                self.events.emit('CAPTION', self.name, current.end,
                    f'{current.index}\t{round(current.core_start * 1000 / RATE)}\t{text}',
                    chunk=current.index, core_start=current.core_start,
                    transcript=text, source_model=MODELS[self.name], accuracy_verified=False)
                if request_id is not None:
                    accounted = self.budget.settle(request_id, usage)
                    self.events.emit('BUDGET', self.name, current.end,
                        f'오늘 한도 반영액 ${accounted:.4f} / ${DAILY_LIMIT:.3f} · '
                        + ('사용량 정산 완료 (청구 추정)' if estimated is not None else '사용량 불명 · 예약 유지'))
            if not self.failed.is_set():
                self.events.emit('DONE', self.name, text='처리 종료 · 정확도는 녹음과 대조 필요')
        except Exception as error:
            self.failed.set()
            # Only our sanitized exceptions are displayed; library errors expose no
            # provider response, header, environment, or credentials.
            message = str(error) if type(error) is RuntimeError else type(error).__name__ + ' · 설치/모델 경로 확인'
            self.events.emit('ERROR', self.name, current.end if current else 0, message,
                             failed_chunk=current.index if current else None)
        finally:
            self.ready.set()
            if self.failed.is_set():
                self.events.emit('ERROR', self.name, text='이 모델 중단 · 미처리 구간 있음, 재시도 없음')
            while True:
                try:
                    pending = self.queue.get_nowait()
                    self.events.emit('SKIPPED', self.name, pending.end, '모델 중단으로 미처리', chunk=pending.index)
                except queue.Empty:
                    break


def run(args, source=None):
    events = Events(args.output)
    budget = None
    workers = []
    shared_input = None
    try:
        names = args.models.split(',')
        if not names or len(set(names)) != len(names) or any(n not in MODELS for n in names):
            raise ValueError('Choose distinct local,mini,full,soniox,daglo models')
        if any(n != 'local' for n in names):
            if not args.allow_upload:
                raise RuntimeError('Cloud requires explicit --allow-upload')
            budget = Budget(__import__('synesis_paths').data_root() / 'recordings' / 'live-budget')
        workers = [Worker(n, args, events, budget) if n in ('local', 'mini', 'full')
                   else StreamWorker(n, args, events) for n in names]
        for worker in workers:
            if not worker.ready.wait(90):
                raise RuntimeError('Model preparation timed out; no microphone audio sent')
        if any(w.failed.is_set() for w in workers):
            raise RuntimeError('선택한 모델 중 준비 실패가 있음 · 녹음 시작 불가 · 실패 모델을 해제하거나 설정 확인')
        events.emit('READY', text='준비 완료 · 모든 모델에 같은 음성 전달 · GTCRN 미적용')
        segmenter = Segmenter(args.silence_db, args.pause_ms, args.min_seconds, args.max_seconds, args.context_seconds)
        local_windows = LocalWindowAggregator(context_seconds=args.context_seconds) if 'local' in names else None
        events.emit('CONFIG', text='무음은 경계 선택에만 사용 · 음성 삭제 없음',
                    silence_db=args.silence_db, pause_ms=args.pause_ms,
                    min_seconds=args.min_seconds, max_seconds=args.max_seconds, context_seconds=args.context_seconds)
        digest = hashlib.sha256()
        prepared_digest = hashlib.sha256()
        total = 0
        balancer = LevelBalancer() if args.balance_levels else None
        shared_input = wave.open(str(args.output / 'shared-input.wav'), 'wb')
        shared_input.setnchannels(1); shared_input.setsampwidth(2); shared_input.setframerate(RATE)
        events.emit('PREPROCESS', text='모든 모델에 동일 적용 · 음량 균형 ' + ('켬' if balancer else '끔'),
                    balance_levels=args.balance_levels)

        def dispatch(chunk, targets, prefix):
            if chunk is None:
                return
            payload = wav_bytes(chunk.pcm)
            (args.output / f'input-{prefix}-{chunk.index:05d}.wav').write_bytes(payload)
            events.emit('INPUT', frame_end=chunk.end, text=f'{prefix} 입력 #{chunk.index}',
                        lane=prefix,
                        chunk=chunk.index, start=chunk.start, core_start=chunk.core_start, end=chunk.end,
                        pcm_sha256=hashlib.sha256(chunk.pcm).hexdigest(),
                        buffering_seconds=(chunk.end-chunk.core_start)/RATE)
            for worker in targets:
                worker.offer(chunk)

        fast_workers = [worker for worker in workers if worker.name in ('mini', 'full')]
        local_workers = [worker for worker in workers if worker.name == 'local']
        stream_workers = [worker for worker in workers if worker.name in ('soniox', 'daglo')]

        def dispatch_short(chunk):
            if chunk is None:
                return
            if fast_workers:
                dispatch(chunk, fast_workers, 'fast')
            if local_windows:
                dispatch(local_windows.feed(chunk), local_workers, 'local')

        source = sys.stdin.buffer if source is None else source
        # read exactly 100 ms where possible; preserve short EOF data, including a
        # final incomplete block. WAV/input integrity tests cover this path.
        while pcm := source.read(3200):
            digest.update(pcm)
            total += len(pcm)
            if balancer:
                pcm = balancer.process(pcm)
            prepared_digest.update(pcm)
            shared_input.writeframesraw(pcm)
            for worker in stream_workers:
                worker.offer(pcm)
            dispatch_short(segmenter.feed(pcm))
        dispatch_short(segmenter.flush())
        if local_windows:
            dispatch(local_windows.flush(), local_workers, 'local')
        events.emit('CAPTURE_END', frame_end=total//2, text='마지막 짧은 구간까지 전달 완료',
                    source_pcm_sha256=digest.hexdigest(), source_frames=total//2,
                    shared_input_pcm_sha256=prepared_digest.hexdigest())
        shared_input.close(); shared_input = None
        for worker in workers:
            worker.finished.set()
        deadline = time.monotonic() + 130
        for worker in workers:
            worker.thread.join(max(0, deadline-time.monotonic()))
        if any(w.thread.is_alive() for w in workers):
            events.emit('ERROR', text='종료 대기 시간 초과 · 일부 자막 미완료, 재요청 없음')
            # Outstanding requests are already durably reserved, never refunded.
            # Process exit releases the OS lock even after abnormal termination.
            budget = None
        events.emit('FINISHED', text='녹음과 모델별 결과 저장 완료 · 누락 여부는 수동 확인')
    except Exception as error:
        events.emit('ERROR', text=str(error) if type(error) is RuntimeError else type(error).__name__)
        return 1
    finally:
        for worker in workers:
            worker.finished.set()
        for worker in workers:
            worker.thread.join(1)
        if budget:
            budget.close()
        if shared_input:
            shared_input.close()
        events.file.close()
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', default='local,mini,full')
    parser.add_argument('--local-model', type=Path, default=ROOT/'models/whisper-large-v3-turbo')
    parser.add_argument('--language', choices=['ko', 'auto', 'en', 'es'], default='ko')
    parser.add_argument('--prompt', default='')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-upload', action='store_true')
    parser.add_argument('--balance-levels', action='store_true')
    parser.add_argument('--silence-db', type=float, default=-42)
    parser.add_argument('--pause-ms', type=int, default=500)
    parser.add_argument('--min-seconds', type=float, default=2)
    parser.add_argument('--max-seconds', type=float, default=4)
    parser.add_argument('--context-seconds', type=float, default=0.5)
    sys.exit(run(parser.parse_args()))
