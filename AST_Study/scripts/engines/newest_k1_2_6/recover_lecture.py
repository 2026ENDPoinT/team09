"""Re-recognize only unconfirmed Soniox intervals after a lecture recording."""

import argparse
import json
import os
import sys
import tempfile
import time
import wave
import uuid

from soniox_billing import request_started, request_state

import requests

from asr_compare import api_key


BASE = 'https://api.soniox.com/v1'
SAMPLE_RATE = 16000


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def audio_duration_ms(path):
    with wave.open(path, 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError('unsupported_wav_format')
        return source.getnframes() * 1000 // SAMPLE_RATE


def crop_audio(source_path, start_ms, end_ms, target_path):
    with wave.open(source_path, 'rb') as source:
        start_frame = start_ms * SAMPLE_RATE // 1000
        end_frame = end_ms * SAMPLE_RATE // 1000
        source.setpos(start_frame)
        pcm = source.readframes(end_frame - start_frame)
    with wave.open(target_path, 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        target.writeframes(pcm)


def api(session, method, path, **kwargs):
    response = session.request(method, BASE + path, timeout=(10, 60), **kwargs)
    if not response.ok:
        raise RuntimeError('http_' + str(response.status_code))
    return response.json() if response.content else {}


def recovered_segments(tokens, crop_start_ms, gap_start_ms, gap_end_ms, serial):
    selected = []
    for raw in tokens:
        if raw.get('translation_status') == 'translation' or raw.get('text') in ('<end>', '<fin>'):
            continue
        if not raw.get('text') or not isinstance(raw.get('start_ms'), (int, float)):
            continue
        start = crop_start_ms + int(raw['start_ms'])
        end = crop_start_ms + int(raw.get('end_ms', raw['start_ms']))
        if not gap_start_ms <= (start + end) / 2 < gap_end_ms:
            continue
        selected.append({**{k: raw[k] for k in ('text', 'speaker', 'confidence', 'language') if k in raw},
                         'start_ms': max(gap_start_ms, start),
                         'end_ms': min(gap_end_ms, max(start, end))})
    segments = []
    group = []
    for token in selected:
        if group and (token.get('speaker') != group[-1].get('speaker')
                      or token['start_ms'] - group[-1]['end_ms'] > 1200
                      or token['end_ms'] - group[0]['start_ms'] > 15000):
            segments.append(group)
            group = []
        group.append(token)
        if token['text'].rstrip().endswith(('.', '?', '!', '。', '？', '！')):
            segments.append(group)
            group = []
    if group:
        segments.append(group)
    for index, group in enumerate(segments):
        speaker = group[0].get('speaker')
        yield {'kind': 'SEGMENT', 'id': f'recovered-{serial}-{index}',
               'startMs': group[0]['start_ms'], 'endMs': group[-1]['end_ms'],
               'speakerId': f'async:{serial}:{speaker}' if speaker is not None else None,
               'speakerNumber': None, 'text': ''.join(t['text'] for t in group),
               'timing': 'provider_tokens_recovered', 'tokens': group}


def recover_one(session, source_path, start_ms, end_ms, serial, billing_ledger=None):
    duration_ms = audio_duration_ms(source_path)
    if end_ms > duration_ms:
        raise ValueError('audio_shorter_than_gap')
    crop_start = max(0, start_ms - 750)
    crop_end = min(duration_ms, end_ms + 750)
    file_id = transcription_id = None
    with tempfile.TemporaryDirectory(prefix='synesis-stt-recovery-') as folder:
        crop_path = os.path.join(folder, 'gap.wav')
        crop_audio(source_path, crop_start, crop_end, crop_path)
        try:
            with open(crop_path, 'rb') as audio:
                uploaded = api(session, 'POST', '/files', files={'file': ('gap.wav', audio, 'audio/wav')})
            file_id = uploaded['id']
            reference = 'synesis-recovery-' + uuid.uuid4().hex
            request_started(billing_ledger, reference, 'stt-async-v5')
            request_state(billing_ledger, reference, 'submitted')
            job = api(session, 'POST', '/transcriptions', json={
                'model': 'stt-async-v5', 'file_id': file_id,
                'enable_speaker_diarization': True,
                'client_reference_id': reference,
            })
            transcription_id = job['id']
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                state = api(session, 'GET', '/transcriptions/' + transcription_id)
                if state['status'] == 'completed':
                    request_state(billing_ledger, reference, 'completed')
                    break
                if state['status'] == 'error':
                    raise RuntimeError('soniox_job_error')
                time.sleep(3)
            else:
                raise TimeoutError('soniox_job_timeout')
            result = api(session, 'GET', '/transcriptions/' + transcription_id + '/transcript')
            for segment in recovered_segments(result.get('tokens', []), crop_start, start_ms, end_ms, serial):
                emit(segment)
            emit({'kind': 'RECOVERY', 'startMs': start_ms, 'endMs': end_ms,
                  'status': 'recovered', 'model': 'stt-async-v5'})
        finally:
            for path in (('/transcriptions/' + transcription_id) if transcription_id else None,
                         ('/files/' + file_id) if file_id else None):
                if path:
                    try:
                        session.delete(BASE + path, timeout=(10, 30))
                    except requests.RequestException:
                        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--billing-ledger')
    parser.add_argument('--audio', required=True)
    parser.add_argument('--fallback', required=True)
    args = parser.parse_args()
    gaps = json.load(sys.stdin)
    key = api_key('SONIOX_API_KEY')
    if not key:
        for gap in gaps:
            emit({'kind': 'RECOVERY', 'startMs': gap['startMs'], 'endMs': gap['endMs'],
                  'status': 'failed', 'errorType': 'missing_key'})
        return 1
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + key
    failed = False
    for serial, gap in enumerate(gaps):
        start_ms, end_ms = int(gap['startMs']), int(gap['endMs'])
        if end_ms <= start_ms:
            continue
        try:
            try:
                input_covers_gap = audio_duration_ms(args.audio) >= end_ms
            except (FileNotFoundError, EOFError, wave.Error):
                input_covers_gap = False
            source = args.audio if input_covers_gap else args.fallback
            recover_one(session, source, start_ms, end_ms, serial, args.billing_ledger)
        except Exception as error:
            failed = True
            emit({'kind': 'RECOVERY', 'startMs': start_ms, 'endMs': end_ms,
                  'status': 'failed', 'errorType': type(error).__name__,
                  'errorCode': str(error) if str(error).startswith('http_') else None})
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
