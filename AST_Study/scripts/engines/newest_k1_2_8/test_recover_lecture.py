import io
import os
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from unittest.mock import patch

from recover_lecture import audio_duration_ms, recover_one, recovered_segments


class RecoveryTest(unittest.TestCase):
    def test_recovered_tokens_keep_recording_clock_and_clip_context(self):
        tokens = [
            {'text': '앞', 'start_ms': 0, 'end_ms': 100},
            {'text': '다시.', 'start_ms': 850, 'end_ms': 1100, 'speaker': '1'},
            {'text': '뒤', 'start_ms': 2100, 'end_ms': 2200},
        ]
        segments = list(recovered_segments(tokens, 1250, 2000, 3000, 4))
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]['id'], 'recovered-4-0')
        self.assertEqual(segments[0]['startMs'], 2100)
        self.assertEqual(segments[0]['speakerId'], 'async:4:1')
        self.assertEqual(segments[0]['text'], '다시.')

    def test_gap_only_upload_and_cleanup(self):
        class Session:
            def __init__(self):
                self.deleted = []

            def delete(self, url, timeout):
                self.deleted.append(url)

        with tempfile.TemporaryDirectory() as folder:
            audio = os.path.join(folder, 'capture.wav')
            with wave.open(audio, 'wb') as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(16000)
                target.writeframes(bytes(32000 * 4))
            self.assertEqual(audio_duration_ms(audio), 4000)
            replies = iter([
                {'id': 'file-id'}, {'id': 'job-id'}, {'status': 'completed'},
                {'tokens': [{'text': '복구.', 'start_ms': 800, 'end_ms': 1000}]},
            ])
            session = Session()
            output = io.StringIO()
            with patch('recover_lecture.api', side_effect=lambda *args, **kwargs: next(replies)):
                with redirect_stdout(output):
                    recover_one(session, audio, 1000, 2000, 0)
            self.assertIn('"startMs": 1050', output.getvalue())
            self.assertIn('"status": "recovered"', output.getvalue())
            self.assertEqual(len(session.deleted), 2)


if __name__ == '__main__':
    unittest.main()
