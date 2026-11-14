import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import asr_compare as asr
from array import array
from types import SimpleNamespace
import math
import wave


class ComparisonContractTests(unittest.TestCase):
    def test_usage_is_preserved_and_does_not_trigger_extra_requests(self):
        def response(*args, usage_sink):
            usage_sink.update(type='tokens', input_tokens=100, output_tokens=50)
            return 'test transcript'
        args = SimpleNamespace(engine='openai', model='gpt-4o-mini-transcribe', language='ko', prompt='')
        report = {}
        with patch.object(asr, 'cloud_transcribe', side_effect=response) as request:
            self.assertEqual(asr.request_cloud(args, report, b'WAV', 'test-key', 0, 5), 'test transcript')
            self.assertEqual(request.call_count, 1)
        self.assertAlmostEqual(report['cloud_requests'][0]['estimated_cost_usd'], 0.000375)
        self.assertNotIn('test-key', json.dumps(report))

    def test_level_balance_preserves_frames_source_and_deterministic_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'audio.wav'
            samples = array('h', [100, -100] * 8000 + [29000, -29000] * 8000)
            original = asr.wav_bytes(samples.tobytes())
            source.write_bytes(original)
            hashes = []
            for name in ('a', 'b'):
                report = {'audio_seconds': 2}
                path = asr.prepare_leveled_audio(SimpleNamespace(audio=source, report=Path(folder) / name), report)
                with wave.open(str(path), 'rb') as audio:
                    self.assertEqual(audio.getnframes(), len(samples))
                    output = array('h', audio.readframes(audio.getnframes()))
                self.assertLessEqual(max(abs(v) for v in output), 32767)
                self.assertGreater(abs(output[100]), abs(samples[100]))
                hashes.append(report['prepared_audio']['sha256'])
            self.assertEqual(hashes[0], hashes[1])
            self.assertEqual(source.read_bytes(), original)

    def test_checked_inputs_cover_file_and_match_saved_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'audio.wav'
            samples = array('h', (round(800 * math.sin(i / 10)) for i in range(16000 * 14 + 1)))
            source.write_bytes(asr.wav_bytes(samples.tobytes()))
            original = source.read_bytes()
            report = {}
            chunks = list(asr.checked_chunks(SimpleNamespace(audio=source, report=Path(folder) / 'test.json'), report))
            cursor = 0
            for item, payload in chunks:
                self.assertEqual(item['core_start'], cursor)
                cursor = item['core_end']
                self.assertEqual(Path(item['input_file']).read_bytes(), payload)
                with wave.open(io.BytesIO(payload), 'rb') as audio:
                    self.assertAlmostEqual(audio.getnframes() / 16000, item['end'] - item['start'])
            self.assertEqual(cursor, len(samples) / 16000)
            self.assertEqual(source.read_bytes(), original)

    def test_normalization_is_bounded_without_clipping_or_silence_amplification(self):
        pcm = array('h', [20000, -20000, 100, -100] * 100).tobytes()
        output, levels = asr.normalize_pcm(pcm)
        self.assertEqual(len(output), len(pcm))
        self.assertLessEqual(max(abs(x) for x in array('h', output)), 32768 * 10 ** (-1 / 20) + 1)
        self.assertLessEqual(levels['gain_db'], 12)
        silence = b'\0\0' * 16000
        self.assertEqual(asr.normalize_pcm(silence)[0], silence)

    def test_gap_check_flags_sound_missing_from_transcript(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'audio.wav'
            source.write_bytes(asr.wav_bytes(array('h', [1000, -1000] * 16000 * 2).tobytes()))
            report = {'audio_seconds': 4, 'segments': [{'start': 2, 'end': 4, 'text': 'test'}]}
            asr.check_local_gaps(SimpleNamespace(audio=source), report)
            self.assertEqual(len(report['warnings']), 1)

    def test_api_key_reads_dotenv_without_overriding_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            dotenv = Path(folder) / ".env"
            dotenv.write_text("# local credentials\nOPENAI_API_KEY=\"file-test-key\"\n", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                self.assertEqual(asr.api_key("OPENAI_API_KEY", dotenv), "file-test-key")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "env-test-key"}):
                self.assertEqual(asr.api_key("OPENAI_API_KEY", dotenv), "env-test-key")

    def test_cloud_request_is_transcription_and_preserves_language_and_glossary(self):
        class Opener:
            def open(self, request, timeout):
                self.request = request
                return io.BytesIO(json.dumps({"text": "미분 derivative"}).encode())
        opener = Opener()
        with patch("urllib.request.build_opener", return_value=opener):
            result = asr.cloud_transcribe("groq", "whisper-large-v3", "ko", "미분, derivative", b"WAV", "test-key")
        self.assertEqual(result, "미분 derivative")
        self.assertEqual(opener.request.full_url, asr.ENDPOINTS["groq"])
        body = opener.request.data.decode()
        self.assertIn('name="language"\r\n\r\nko', body)
        self.assertIn("미분, derivative", body)
        self.assertNotIn("test-key", body)

    def test_auto_omits_language_and_errors_do_not_expose_response(self):
        class Opener:
            def open(self, request, timeout):
                assert b'name="language"' not in request.data
                raise urllib.error.HTTPError(request.full_url, 401, "secret-key", {}, io.BytesIO(b"PRIVATE AUDIO"))
        with patch("urllib.request.build_opener", return_value=Opener()):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as failure:
                asr.cloud_transcribe("openai", "gpt-4o-transcribe", "auto", "", b"WAV", "test-key")
        self.assertNotIn("secret", str(failure.exception))
        self.assertNotIn("PRIVATE", str(failure.exception))

    def test_missing_consent_never_uploads_and_preserves_failure_report(self):
        with tempfile.TemporaryDirectory() as folder:
            source, report = Path(folder) / "audio.wav", Path(folder) / "result.json"
            source.write_bytes(asr.wav_bytes(b"\0\0" * 16000))
            original = source.read_bytes()
            with patch.object(asr, "cloud_transcribe") as cloud:
                code = asr.main(["--audio", str(source), "--engine", "groq", "--model", "whisper-large-v3",
                                 "--report", str(report)])
                cloud.assert_not_called()
            self.assertEqual(code, 1)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["state"], "failed")

    def test_chunk_coverage_empty_and_failed_intervals(self):
        with tempfile.TemporaryDirectory() as folder:
            source, report = Path(folder) / "audio.wav", Path(folder) / "result.json"
            source.write_bytes(asr.wav_bytes(b"\0\0" * 16000 * 61))
            args = ["--audio", str(source), "--engine", "groq", "--model", "whisper-large-v3",
                    "--allow-upload", "--chunk-seconds", "30", "--report", str(report)]
            with patch.dict(os.environ, {"GROQ_API_KEY": "fake"}), patch.object(
                    asr, "cloud_transcribe", side_effect=["첫 구간", "", RuntimeError("network failed")]) as cloud:
                self.assertEqual(asr.main(args), 1)
                self.assertEqual(cloud.call_count, 3)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["processed_seconds"], 60)
            self.assertEqual(data["failed_interval"], {"start": 60, "end": 61})
            self.assertEqual(data["segments"][1]["text"], "")
            self.assertEqual(asr.main(args), 2)  # never overwrite existing benchmark


if __name__ == "__main__":
    unittest.main()
