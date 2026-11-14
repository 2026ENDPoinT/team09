"""Opt-in file transcription benchmark. No keys, audio or transcripts in telemetry.

Cloud needs --allow-upload AND the provider's key in .env or the environment. Stdlib only
for cloud; faster-whisper is imported only for local runs. Input is never modified.
"""
import argparse
from array import array
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave

ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/audio/transcriptions",
    "openai": "https://api.openai.com/v1/audio/transcriptions",
}
MODELS = {
    "groq": {"whisper-large-v3", "whisper-large-v3-turbo"},
    "openai": {"gpt-4o-mini-transcribe", "gpt-4o-transcribe"},
}
from synesis_paths import credentials_file
DOTENV_PATH = credentials_file()


def api_key(variable, dotenv_path=DOTENV_PATH):
    """Prefer the process environment, then read one matching key from local .env."""
    value = os.environ.get(variable, "").strip()
    if value or not dotenv_path.is_file():
        return value
    for line in dotenv_path.read_text(encoding="utf-8-sig").splitlines():
        name, separator, raw_value = line.partition("=")
        if separator and name.strip() == variable:
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            return value.strip()
    return ""


def inspect_audio(path):
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("16 kHz mono 16-bit PCM WAV required; select a recording made by this app.")
        frames = source.getnframes()
        if frames == 0:
            raise ValueError("Empty WAV.")
        remaining = frames
        while remaining:
            data = source.readframes(min(remaining, 16000 * 60))
            if not data or len(data) % 2:
                raise ValueError("Truncated WAV; repair its header before testing.")
            remaining -= len(data) // 2
    with open(path, "rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return frames / 16000, digest


def multipart(fields, audio):
    boundary = "synesis-" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                      f'{value}\r\n').encode("utf-8"))
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
                  'Content-Type: audio/wav\r\n\r\n').encode("ascii"))
    parts.extend([audio, f'\r\n--{boundary}--\r\n'.encode("ascii")])
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward audio or bearer tokens to a redirected host.
        return None


def cloud_transcribe(engine, model, language, prompt, audio, key, usage_sink=None):
    fields = {"model": model, "response_format": "json"}
    if language != "auto":
        fields["language"] = language
    if prompt:
        fields["prompt"] = prompt
    payload, content_type = multipart(fields, audio)
    request = urllib.request.Request(ENDPOINTS[engine], data=payload, headers={
        "Authorization": "Bearer " + key, "Content-Type": content_type,
        "User-Agent": "SYNESIS-ASR-Comparison/1.0",
    })
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        # Provider bodies may contain private data. Never log them or retry billable
        # requests automatically: a timed-out request might already be charged.
        raise RuntimeError(f"{engine} HTTP {error.code}; check key, quota and provider status. No automatic retry.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("Cloud connection failed/timed out. No automatic retry; the request may have been billed.") from None
    except (ValueError, UnicodeError):
        raise RuntimeError("Invalid provider response; no automatic retry.") from None
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise RuntimeError("Provider response has no text field.")
    if usage_sink is not None and isinstance(result.get('usage'), dict):
        usage_sink.update(result['usage'])
    return result["text"].strip()


def request_cloud(args, report, payload, key, start, end):
    usage = {}
    request = {'start': start, 'end': end, 'audio_seconds': end - start, 'usage': usage}
    report.setdefault('cloud_requests', []).append(request)
    request['status'] = 'attempted'
    prompt = args.prompt
    if args.engine == 'openai':
        instruction = ('녹음의 처음부터 끝까지 모든 발화를 순서대로 그대로 받아쓰세요. 문장을 요약하거나 생략하지 마세요. 들리지 않는 말은 만들지 마세요.'
                       if args.language == 'ko' else
                       'Transcribe every audible utterance in order, in its original language. Do not summarize or omit speech. Do not invent inaudible words.')
        prompt = instruction + ('\n' + prompt if prompt else '')
    report['effective_prompt'] = prompt
    text = cloud_transcribe(args.engine, args.model, args.language, prompt, payload, key, usage_sink=usage)
    request['status'] = 'returned'
    if args.engine == 'openai' and usage.get('type') == 'tokens':
        input_rate, output_rate = (1.25, 5.0) if 'mini' in args.model else (2.5, 10.0)
        request['estimated_cost_usd'] = (usage.get('input_tokens', 0) * input_rate + usage.get('output_tokens', 0) * output_rate) / 1_000_000
        request['pricing_source'] = 'https://developers.openai.com/api/docs/pricing (2026-09-26; estimate, not billing reconciliation)'
    return text


def wav_bytes(pcm):
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(16000)
        target.writeframes(pcm)
    return out.getvalue()


def emit_segment(report, start, end, text, **metadata):
    item = {"start": start, "end": end, "text": text, **metadata}
    report["segments"].append(item)
    print(f"[{start:.2f}–{end:.2f}s] {text or '[빈 결과: 무음 또는 인식 누락 — 녹음 확인 필요]'}", flush=True)


def warning(report, message):
    report.setdefault("warnings", []).append(message)
    print("확인 필요: " + message, flush=True)


def normalize_pcm(pcm):
    """Bounded constant gain per chunk; preserve samples and never clip or trim."""
    samples = array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max((abs(x) for x in samples), default=0)
    rms = math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))
    rms_db = 20 * math.log10(max(1, rms) / 32768)
    # Avoid amplifying near-silence. This is a level check, not speech detection.
    gain = max(0, min(12, -20 - rms_db, -1 - 20 * math.log10(max(1, peak) / 32768))) if rms_db > -65 else 0
    scale = 10 ** (gain / 20)
    adjusted = array("h", (round(x * scale) for x in samples))
    if sys.byteorder != "little":
        adjusted.byteswap()
    return adjusted.tobytes(), {"gain_db": round(gain, 3), "input_rms_dbfs": round(rms_db, 3)}


def prepare_leveled_audio(args, report):
    """Local level balancing, preserving every frame; no extra cloud requests."""
    path = args.report.with_name(args.report.name + '.leveled.wav')
    gain_db = None
    gains = []
    with wave.open(str(args.audio), 'rb') as source, path.open('xb') as file:
        with wave.open(file, 'wb') as target:
            target.setparams(source.getparams())
            while pcm := source.readframes(1600):
                samples = array('h', pcm)
                if sys.byteorder != 'little':
                    samples.byteswap()
                _, levels = normalize_pcm(pcm)
                desired = levels['gain_db']
                peak = max((abs(x) for x in samples), default=0)
                headroom = max(0, -1 - 20 * math.log10(max(1, peak) / 32768))
                start_gain = min(desired if gain_db is None else gain_db, headroom)
                gain_db = min(headroom, start_gain + .2 * (desired - start_gain))
                adjusted = array('h', (max(-32768, min(32767, round(value * 10 ** (
                    (start_gain + (gain_db - start_gain) * (i + 1) / len(samples)) / 20))))
                    for i, value in enumerate(samples)))
                if sys.byteorder != 'little':
                    adjusted.byteswap()
                target.writeframesraw(adjusted.tobytes())
                gains.append(gain_db)
    duration, digest = inspect_audio(path)
    if duration != report['audio_seconds']:
        raise ValueError('Prepared audio length differs from source; recognition stopped.')
    report['prepared_audio'] = {'path': str(path.resolve()), 'sha256': digest, 'audio_seconds': duration,
                                'min_gain_db': round(min(gains), 3), 'max_gain_db': round(max(gains), 3)}
    print(f"로컬 음량 균형: {duration:.3f}초 유지 · 최대 +{max(gains):.1f} dB · {path}", flush=True)
    return path


def checked_chunks(args, report):
    """Cover every source frame; overlap boundaries by 0.5 s on each side."""
    with wave.open(str(args.audio), "rb") as source:
        frames = source.getnframes()
        core_start, index = 0, 0
        while core_start < frames:
            core_end = min(frames, core_start + 6 * 16000)
            if frames - core_end < 2 * 16000:
                core_end = frames
            start, end = max(0, core_start - 8000), min(frames, core_end + 8000)
            source.setpos(start)
            pcm, levels = normalize_pcm(source.readframes(end - start))
            payload = wav_bytes(pcm)
            artifact = args.report.with_name(args.report.name + f".input-{index + 1:03d}.wav")
            with artifact.open("xb") as target:
                target.write(payload)
            item = {"start": start / 16000, "end": end / 16000,
                    "core_start": core_start / 16000, "core_end": core_end / 16000,
                    "input_file": str(artifact.resolve()), "input_sha256": hashlib.sha256(payload).hexdigest(),
                    **levels}
            report.setdefault("input_chunks", []).append(item)
            print(f"입력 {index + 1}: {item['start']:.2f}–{item['end']:.2f}s · 보정 +{levels['gain_db']:.1f} dB", flush=True)
            yield item, payload
            core_start, index = core_end, index + 1


def check_local_gaps(args, report):
    intervals = sorted((s['start'], s['end']) for s in report['segments'] if s['text'])
    cursor = 0
    gaps = []
    for start, end in intervals + [(report['audio_seconds'], report['audio_seconds'])]:
        if start - cursor >= 1.5:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    with wave.open(str(args.audio), 'rb') as source:
        for start, end in gaps:
            source.setpos(int(start * 16000))
            remaining = int((end - start) * 16000)
            count, squared = 0, 0
            while remaining > 0:
                values = array('h', source.readframes(min(16000, remaining)))
                if not values:
                    break
                if sys.byteorder != 'little':
                    values.byteswap()
                count += len(values)
                remaining -= len(values)
                squared += sum(value * value for value in values)
            rms = math.sqrt(squared / max(1, count))
            if 20 * math.log10(max(1, rms) / 32768) > -65:
                warning(report, f"{start:.2f}–{end:.2f}초에 소리가 있지만 자막이 없습니다. 말인지 잡음인지 녹음과 대조하세요.")
    report['coverage_status'] = 'timing_checked_not_accuracy_verified'


def check_repetitions(report):
    seen = set()
    for segment in report['segments']:
        if segment.get('overlapping_context'):
            continue
        text = ''.join(c.lower() for c in segment['text'] if c.isalnum())
        if len(text) >= 15 and text in seen:
            warning(report, f"{segment['start']:.2f}초 부근: 같은 문장이 반복됐습니다. 실제 반복인지 인식 오류인지 확인하세요.")
        seen.add(text)


def run_cloud(args, report):
    if not args.allow_upload:
        raise ValueError("Cloud upload requires explicit --allow-upload consent.")
    if args.model not in MODELS[args.engine]:
        raise ValueError("Unsupported cloud model.")
    variable = "GROQ_API_KEY" if args.engine == "groq" else "OPENAI_API_KEY"
    key = api_key(variable)
    if not key:
        raise ValueError(f"Set {variable} in the project's .env file or launch environment. Never paste it into chat.")
    if any(character.isspace() for character in key) or not key.isascii():
        raise ValueError(f"Invalid {variable} format; check it locally without sharing the value.")
    if args.input_mode == "checked":
        report['coverage_status'] = 'unverified_provider_has_no_word_timestamps'
        for item, payload in checked_chunks(args, report):
            try:
                text = request_cloud(args, report, payload, key, item['start'], item['end'])
            except Exception:
                report['failed_interval'] = {'start': item['start'], 'end': item['end']}
                raise
            emit_segment(report, item['start'], item['end'], text,
                         timestamp_type='request_interval_not_word_alignment', overlapping_context=True)
            if not text:
                warning(report, f"{item['start']:.2f}–{item['end']:.2f}초: 빈 응답")
            report['processed_seconds'] = item['core_end']
        print('표시된 시간은 전송 구간입니다. 구간 사이 겹치는 말은 대조용으로 보존하며, 전체 받아쓰기 여부는 검증되지 않았습니다.', flush=True)
        return
    path = prepare_leveled_audio(args, report) if args.input_mode == 'leveled' else args.audio
    with wave.open(str(path), "rb") as source:
        offset = 0
        while pcm := source.readframes(16000 * args.chunk_seconds):
            start, end = offset / 32000, (offset + len(pcm)) / 32000
            print(f"Uploading {start:.1f}–{end:.1f}s to {args.engine}...", flush=True)
            try:
                text = request_cloud(args, report, wav_bytes(pcm), key, start, end)
            except Exception:
                report["failed_interval"] = {"start": start, "end": end}
                raise
            emit_segment(report, start, end, text, timestamp_type="request_interval_not_word_alignment")
            if not text:
                warning(report, f"{start:.2f}–{end:.2f}초: 빈 응답")
            offset += len(pcm)
            report["processed_seconds"] = end


def run_local(args, report):
    if not Path(args.model).is_dir():
        raise ValueError("Local model folder missing. Run scripts/setup-asr.ps1 first; no automatic download during recognition.")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ValueError("faster-whisper not installed. Run scripts/setup-asr.ps1 and select .venv/Scripts/python.exe.") from None
    print("Loading faster-whisper (CPU int8)...", flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
    if args.input_mode == 'checked':
        from faster_whisper.audio import decode_audio
        for item, payload in checked_chunks(args, report):
            segments, _ = model.transcribe(
                decode_audio(io.BytesIO(payload)), language=None if args.language == 'auto' else args.language,
                task='transcribe', beam_size=5, initial_prompt=args.prompt or None,
                condition_on_previous_text=False, vad_filter=args.vad,
                vad_parameters={'min_silence_duration_ms': 700, 'speech_pad_ms': 400}, word_timestamps=True)
            count = 0
            for segment in segments:
                count += 1
                emit_segment(report, item['start'] + segment.start, min(item['end'], item['start'] + segment.end),
                             segment.text.strip(), avg_logprob=segment.avg_logprob,
                             no_speech_prob=segment.no_speech_prob, overlapping_context=True)
                if segment.avg_logprob < -1:
                    warning(report, f"{item['start']:.2f}초 입력 구간의 인식 신뢰도가 낮습니다.")
            if not count:
                warning(report, f"{item['start']:.2f}–{item['end']:.2f}초: 모델이 자막을 반환하지 않았습니다.")
            report['processed_seconds'] = item['core_end']
        check_local_gaps(args, report)
        print('겹치는 구간의 텍스트는 대조용으로 모두 보존했습니다. 시간 점검은 정확도 보장이 아닙니다.', flush=True)
        return
    print(f"Transcribing; language={args.language}, VAD={args.vad}. Long recordings may take time.", flush=True)
    path = prepare_leveled_audio(args, report) if args.input_mode == 'leveled' else args.audio
    segments, info = model.transcribe(
        str(path), language=None if args.language == "auto" else args.language,
        task="transcribe", beam_size=5, initial_prompt=args.prompt or None,
        condition_on_previous_text=False, vad_filter=args.vad,
        vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 400},
        word_timestamps=True,
    )
    report["recognition_language"] = info.language
    report["language_source"] = "auto_detection" if args.language == "auto" else "user_hint"
    report["language_probability"] = info.language_probability if args.language == "auto" else None
    report["duration_after_vad"] = info.duration_after_vad
    language_note = (f"auto probability {info.language_probability:.3f}" if args.language == "auto"
                     else "user hint; not a detection confidence")
    print(f"Language: {info.language} ({language_note}); audio after VAD: {info.duration_after_vad:.2f}s", flush=True)
    for segment in segments:
        emit_segment(report, segment.start, segment.end, segment.text.strip(),
                     avg_logprob=segment.avg_logprob, no_speech_prob=segment.no_speech_prob,
                     words=[{"start": w.start, "end": w.end, "word": w.word, "probability": w.probability}
                            for w in (segment.words or [])])
    if not report["segments"]:
        emit_segment(report, 0, report["audio_seconds"], "")
    report["processed_seconds"] = report["audio_seconds"]
    check_local_gaps(args, report)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--engine", choices=["local", "groq", "openai"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", choices=["ko", "auto", "en", "es"], default="ko")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--vad", action="store_true")
    parser.add_argument("--allow-upload", action="store_true")
    parser.add_argument("--input-mode", choices=['original', 'leveled', 'checked'], default='original')
    parser.add_argument("--chunk-seconds", type=int, choices=[30, 60, 300], default=60)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    # CREATE_NEW before model loading/network prevents accidental report overwrite.
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        target = args.report.open("x", encoding="utf-8")
    except FileExistsError:
        print("Report already exists; choose a new report path.", file=sys.stderr)
        return 2
    started = time.monotonic()
    report = {"engine": args.engine, "model": args.model, "language": args.language,
              "vad": args.vad if args.engine == "local" else "provider controlled",
              "prompt": args.prompt, "audio": str(args.audio.resolve()), "segments": [],
              "processed_seconds": 0, "state": "running", "post_correction": False,
              "chunk_seconds": args.chunk_seconds if args.engine != "local" else None}
    report.update(input_mode=args.input_mode, coverage_status='unverified', warnings=[])
    code = 0
    try:
        report["audio_seconds"], report["audio_sha256"] = inspect_audio(args.audio)
        print(f"원본: {report['audio_seconds']:.3f}초 · SHA256 {report['audio_sha256']} · 방식 {args.input_mode}", flush=True)
        if args.engine == "local":
            run_local(args, report)
        else:
            run_cloud(args, report)
        check_repetitions(report)
        report["state"] = "processed_with_warnings" if report['warnings'] else "processed_unverified"
        print('처리 종료 — 받아쓰기 정확도는 녹음과 대조해서 확인하세요.', flush=True)
    except KeyboardInterrupt:
        report["state"] = "cancelled"
        code = 130
    except Exception as error:
        report["state"] = "failed"
        # All provider exceptions above have already been reduced to safe messages.
        report["error"] = str(error)
        print("ERROR: " + str(error), file=sys.stderr, flush=True)
        code = 1
    finally:
        requests = report.get('cloud_requests', [])
        if requests and all('estimated_cost_usd' in r for r in requests):
            report['estimated_cost_usd'] = sum(r['estimated_cost_usd'] for r in requests)
            print(f"API 사용량 기준 비용 추정: ${report['estimated_cost_usd']:.6f} (실제 청구와 차이 가능)", flush=True)
        report["elapsed_seconds"] = time.monotonic() - started
        report["rtf_including_load"] = report["elapsed_seconds"] / max(report.get("audio_seconds", 0), 0.001)
        with target:
            json.dump(report, target, ensure_ascii=False, indent=2)
        print(f"Report: {args.report}\nState: {report['state']}; elapsed {report['elapsed_seconds']:.2f}s", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
