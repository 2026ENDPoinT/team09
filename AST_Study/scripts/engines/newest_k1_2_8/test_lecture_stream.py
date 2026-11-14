import unittest
import json
import queue
import threading
from types import SimpleNamespace
from unittest.mock import patch
import websocket
from lecture_stream import Transcript
from live_streams import StreamWorker


def token(text, start, end, speaker='9', final=True):
    return dict(text=text, start_ms=start, end_ms=end, speaker=speaker, is_final=final)


class TranscriptTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.transcript = Transcript(self.events.append)

    def segments(self):
        return {e['id']: e for e in self.events if e['kind'] == 'SEGMENT'}

    def test_first_appearance_numbering_not_provider_number(self):
        self.transcript.soniox([token('안녕.', 0, 500, '9'), token('네.', 600, 1000, '3'), token('다시.', 1100, 1600, '9')])
        self.assertEqual([e['speakerNumber'] for e in self.segments().values()], [1, 2, 1])
        self.assertEqual([e['speakerId'] for e in self.segments().values()], ['9', '3', '9'])

    def test_reconnected_tokens_use_capture_clock_and_distinct_speaker_ids(self):
        self.transcript.soniox([token('처음.', 0, 100, '1')], offset_ms=0, connection_id='a')
        self.transcript.soniox([token('재개.', 0, 100, '1')], offset_ms=5000, connection_id='b')
        segments = list(self.segments().values())
        self.assertEqual([(s['startMs'], s['endMs']) for s in segments], [(0, 100), (5000, 5100)])
        self.assertEqual([s['speakerId'] for s in segments], ['a:1', 'b:1'])

    def test_upserts_keep_full_utterance_without_duplication(self):
        self.transcript.soniox([token('안녕', 100, 400)])
        self.transcript.soniox([token('하세요', 400, 800), token(' 임시', 800, 1200, final=False)])
        self.transcript.soniox([token('.', 800, 900)], finished=True)
        self.assertEqual(len(self.segments()), 1)
        segment = self.segments()['1']
        self.assertEqual(segment['text'], '안녕하세요.')
        self.assertEqual((segment['startMs'], segment['endMs']), (100, 900))
        self.assertEqual(len(segment['tokens']), 3)

    def test_provisional_speaker_does_not_consume_number(self):
        self.transcript.soniox([token('임시', 0, 300, 'ghost', False)])
        self.transcript.soniox([token('확정', 0, 300, 'real')])
        self.assertEqual(self.segments()['1']['speakerNumber'], 1)
        self.assertNotIn('ghost', self.transcript.speakers)

    def test_markers_and_translation_not_in_transcript(self):
        self.transcript.soniox([token('말', 0, 100), dict(text='<end>', is_final=True),
                                dict(text='translation', is_final=True, translation_status='translation'),
                                token('다음', 200, 300)])
        self.assertEqual([e['text'] for e in self.segments().values()], ['말', '다음'])

    def test_unknown_speaker_and_untimed_punctuation(self):
        self.transcript.soniox([token('말', 100, 200, None), dict(text='.', is_final=True)])
        self.assertIsNone(self.segments()['1']['speakerNumber'])
        self.assertEqual(self.segments()['1']['endMs'], 200)

    def test_partial_updates_do_not_rewrite_unchanged_finals(self):
        self.transcript.soniox([token('말', 0, 200)])
        for i in range(10):
            self.transcript.soniox([token('임시', 200, 400, final=False)])
        self.assertEqual(len([e for e in self.events if e['kind'] == 'SEGMENT']), 1)

    def test_daglo_timing_is_explicit_estimate(self):
        self.transcript.daglo('임시', False, 500)
        self.transcript.daglo('첫째', True, 1500)
        self.transcript.daglo('둘째', True, 2700)
        first, second = self.segments().values()
        self.assertEqual(first['timing'], 'processed_duration_estimate')
        self.assertIsNone(first['speakerNumber'])
        self.assertEqual((second['startMs'], second['endMs']), (1500, 2700))

    def test_untimed_punctuation_inherits_previous_speaker(self):
        self.transcript.soniox([token('안녕', 100, 200, '9'), dict(text='.', is_final=True)])
        self.assertEqual(len(self.segments()), 1)
        self.assertEqual(self.segments()['1']['text'], '안녕.')
        self.assertEqual(self.segments()['1']['speakerNumber'], 1)

    def test_structured_transport_enables_diarization_and_finishes(self):
        sent, events = [], []
        class Socket:
            def send(self, data): sent.append(data)
            def send_binary(self, data): sent.append(data)
            def settimeout(self, value): pass
            def close(self): pass
            def recv_data(self, control_frame=False):
                return websocket.ABNF.OPCODE_TEXT, json.dumps({'tokens': [token('안녕.', 0, 100)], 'finished': True})
        worker = StreamWorker.__new__(StreamWorker)
        worker.args = SimpleNamespace(language='auto', prompt='', structured=True, diarization=True)
        worker.failed = threading.Event()
        worker.restart_requested = threading.Event()
        worker.queue = queue.Queue()
        worker.name = 'soniox'
        worker.gap_start_ms = None
        worker.confirmed_ms = 0
        worker.events = SimpleNamespace(emit=lambda kind, name, **data: events.append((kind, data)))
        with patch('websocket.create_connection', return_value=Socket()):
            worker.soniox('fake-test-key', (0, bytes(3200)), iter(()))
        config = json.loads(sent[0])
        self.assertTrue(config['enable_speaker_diarization'])
        self.assertFalse(config['enable_endpoint_detection'])
        self.assertNotIn('language_hints_strict', config)
        result = [data for kind, data in events if kind == 'TOKENS'][0]
        self.assertEqual(result['tokens'][0]['speaker'], '9')
        self.assertTrue(result['finished'])
        self.assertEqual(sent[-1], '')


if __name__ == '__main__':
    unittest.main()
