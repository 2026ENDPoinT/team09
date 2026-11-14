"""Main recorder's continuous PCM transport. No file re-upload or automatic retry.

stdin: mono PCM16/16 kHz. stdout: safe NDJSON events. Keys remain in .env.
Network opens only after audio arrives. Final tokens are upserts, not repeated text.
"""
import argparse
import json
import sys
import threading

def uncaught_error(error_type, error, tb):
    # Startup/import failures also need evidence; never echo exception messages.
    import os
    frames = []
    while tb is not None and len(frames) < 32:
        frames.append({'file': os.path.basename(tb.tb_frame.f_code.co_filename),
                       'function': tb.tb_frame.f_code.co_name, 'line': tb.tb_lineno})
        tb = tb.tb_next
    print(json.dumps({'kind': 'ERROR', 'text': 'Python 처리 오류 · 진단 로그 확인',
                      'stage': 'python.uncaught', 'errorType': error_type.__name__, 'frames': frames}), flush=True)


if __name__ == '__main__':
    sys.excepthook = uncaught_error

from live_streams import StreamWorker

MAX_RECORDING_SECONDS = (4 * 60 + 30) * 60


class Transcript:
    def __init__(self, output):
        self.output = output
        self.speakers = {}
        self.tokens = []
        self.serial = 0
        self.daglo_end = 0
        self.last_segment = None

    def label(self, speaker, assign=False):
        if speaker is None or str(speaker) == '':
            return None
        speaker = str(speaker)
        if assign and speaker not in self.speakers:
            self.speakers[speaker] = len(self.speakers) + 1
        return self.speakers.get(speaker)

    def segment(self):
        if not self.tokens:
            return
        first, last = self.tokens[0], self.tokens[-1]
        event = {'kind': 'SEGMENT', 'id': str(self.serial),
                     'startMs': first['start_ms'], 'endMs': last['end_ms'],
                     'speakerId': first.get('speaker'),
                     'speakerNumber': self.label(first.get('speaker'), True),
                     'text': ''.join(t['text'] for t in self.tokens),
                     'timing': 'provider_tokens', 'tokens': self.tokens.copy()}
        if event != self.last_segment:
            self.output(event)
            self.last_segment = event

    def soniox(self, tokens, finished=False, offset_ms=0, connection_id=None):
        interim = []
        for raw in tokens:
            text = raw.get('text', '')
            if text in ('<end>', '<fin>'):
                if raw.get('is_final'):
                    self.segment()
                    self.tokens = []
                continue
            if not text or raw.get('translation_status') == 'translation':
                continue
            token = {k: raw[k] for k in ('text', 'start_ms', 'end_ms', 'speaker', 'confidence', 'language') if k in raw}
            if 'start_ms' in token:
                token['start_ms'] += offset_ms
            if 'end_ms' in token:
                token['end_ms'] += offset_ms
            if 'speaker' in token and connection_id is not None:
                token['speaker'] = connection_id + ':' + str(token['speaker'])
            if not raw.get('is_final'):
                interim.append(token)
                continue
            # Untimed punctuation belongs to the preceding timed token, not receipt time.
            previous_end = self.tokens[-1]['end_ms'] if self.tokens else 0
            if 'speaker' not in token and self.tokens and not text.strip(' .,!?:;。？！'):
                token['speaker'] = self.tokens[-1].get('speaker')
            token['start_ms'] = int(token.get('start_ms', previous_end))
            token['end_ms'] = max(token['start_ms'], int(token.get('end_ms', token['start_ms'])))
            if self.tokens and (token.get('speaker') != self.tokens[-1].get('speaker')
                                or token['start_ms'] - previous_end > 1200
                                or token['end_ms'] - self.tokens[0]['start_ms'] > 15000):
                self.segment()
                self.tokens = []
            if not self.tokens:
                self.serial += 1
            self.label(token.get('speaker'), True)
            self.tokens.append(token)
            if text.rstrip().endswith(('.', '?', '!', '。', '？', '！')):
                self.segment()
                self.tokens = []
        self.segment()
        lines = []
        last_speaker = object()
        for token in interim:
            speaker = token.get('speaker')
            if speaker != last_speaker:
                number = self.label(speaker)
                lines.append(('화자 ' + str(number) if number else '화자 확인 중') + ': ')
                last_speaker = speaker
            lines[-1] += token['text']
        self.output({'kind': 'PARTIAL', 'text': '\n'.join(lines)})
        if finished:
            self.tokens = []

    def daglo(self, text, is_final, processed_ms):
        if is_final and text:
            self.serial += 1
            end = max(self.daglo_end, processed_ms)
            self.output({'kind': 'SEGMENT', 'id': str(self.serial), 'startMs': self.daglo_end,
                         'endMs': end, 'speakerId': None, 'speakerNumber': None, 'text': text,
                         'timing': 'processed_duration_estimate', 'tokens': []})
            self.daglo_end = end
        self.output({'kind': 'PARTIAL', 'text': '' if is_final else '화자 미지정: ' + text})


class Events:
    def __init__(self):
        self.lock = threading.Lock()
        self.transcript = Transcript(self.write)

    def write(self, event):
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def emit(self, kind, provider, **data):
        with self.lock:
            if kind == 'TOKENS':
                self.transcript.soniox(data['tokens'], data.get('finished', False),
                                       data.get('offsetMs', 0), data.get('connectionId'))
            elif kind == 'DAGLO_RESULT':
                self.transcript.daglo(data['text'], data['is_final'], data['processed_ms'])
            else:
                self.write({'kind': kind, 'provider': provider, **data})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--billing-ledger')
    parser.add_argument('--provider', choices=('soniox', 'daglo'), required=True)
    args = parser.parse_args()
    args.allow_upload, args.structured, args.diarization = True, True, True
    args.language, args.prompt = 'auto', ''
    args.max_stream_seconds = MAX_RECORDING_SECONDS
    events = Events()
    worker = StreamWorker(args.provider, args, events)
    if not worker.ready.wait(20) or worker.failed.is_set():
        return 1
    events.emit('READY', args.provider, text='키·라이브러리 준비 완료 · 서버 연결은 녹음 시작 후')
    while True:
        pcm = sys.stdin.buffer.read(3200)
        if not pcm:
            break
        if worker.failed.is_set():
            return 1
        if len(pcm) % 2:
            events.emit('ERROR', args.provider, text='불완전한 PCM 샘플')
            return 1
        worker.offer(pcm)
    worker.finished.set()
    worker.thread.join(30)
    if worker.thread.is_alive():
        events.emit('ERROR', args.provider, text='최종 자막 대기 시간 초과 · 미완료')
        return 1
    events.emit('FINISHED', args.provider,
                complete=not worker.failed.is_set() and not worker.had_gap)
    return int(worker.failed.is_set())


if __name__ == '__main__':
    raise SystemExit(main())
