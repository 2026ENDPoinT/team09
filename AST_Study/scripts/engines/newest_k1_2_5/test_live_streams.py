import unittest
import json
import queue
import threading
from types import SimpleNamespace
from unittest.mock import patch

import websocket

from live_streams import StreamWorker, SonioxServerError, _retryable_soniox_error, _safe_diagnostic, daglo_messages


class DagloProtocolTest(unittest.TestCase):
    def test_config_audio_and_response_wire(self):
        Config, Request, Response = daglo_messages()
        config = Request(config=Config(language_code='mixed', interim_results=True))
        self.assertEqual(Request.FromString(config.SerializeToString()).WhichOneof('streaming_request'), 'config')
        audio = Request(audio_content=b'\x00\x01')
        self.assertEqual(Request.FromString(audio.SerializeToString()).audio_content, b'\x00\x01')
        response = Response.FromString(b'\x0a\x08\x0a\x02Hi\x10\x01\x1a\x00')
        self.assertEqual(response.result.transcript, 'Hi')
        self.assertTrue(response.result.is_final)


class SonioxDiagnosticTest(unittest.TestCase):
    def test_server_retry_uses_status_code(self):
        self.assertTrue(_retryable_soniox_error(
            SonioxServerError({'error_code': 500}, 'progress'), websocket))
        self.assertTrue(_retryable_soniox_error(
            SonioxServerError({'error_code': 429}, 'progress'), websocket))
        self.assertFalse(_retryable_soniox_error(
            SonioxServerError({'error_code': 401}, 'progress'), websocket))

    def test_structured_diagnostic_has_frames_without_secrets(self):
        worker = StreamWorker.__new__(StreamWorker)
        worker.args = SimpleNamespace(structured=True)
        worker.name = 'soniox'
        received = []
        worker.events = SimpleNamespace(emit=lambda *args, **fields: received.append(fields))
        try:
            raise RuntimeError('random-private-key')
        except RuntimeError as error:
            worker.diagnostic('test', error)
        serialized = json.dumps(received)
        self.assertNotIn('random-private-key', serialized)
        self.assertIn('RuntimeError', serialized)
        self.assertIn('test_live_streams.py', serialized)

    def test_backpressure_records_progress_and_requests_reconnect(self):
        worker = StreamWorker.__new__(StreamWorker)
        worker.args = SimpleNamespace(structured=True, max_stream_seconds=120)
        worker.name = 'soniox'
        worker.failed = threading.Event()
        worker.finished = threading.Event()
        worker.restart_requested = threading.Event()
        worker.queue = queue.Queue(maxsize=1)
        worker.queue.put_nowait(b'\x00\x00')
        worker.offered_bytes = 32000
        worker.sent_bytes = 16000
        worker.send_started_at = None
        worker.last_response_at = None
        worker.confirmed_ms = 400
        worker.gap_start_ms = None
        worker.had_gap = False
        worker.last_backpressure_diag_at = 0
        received = []
        worker.events = SimpleNamespace(emit=lambda *args, **fields: received.append((args, fields)))

        worker.offer(b'\x00\x00')

        self.assertFalse(worker.failed.is_set())
        self.assertTrue(worker.restart_requested.is_set())
        self.assertEqual(worker.gap_start_ms, 400)
        self.assertEqual(received[0][0][0], 'DIAGNOSTIC')
        self.assertEqual(received[0][1]['stage'], 'soniox.backpressure')
        self.assertEqual(received[0][1]['queuedBlocks'], 1)
        self.assertEqual(received[0][1]['offeredMs'], 1000)
        self.assertEqual(received[0][1]['sentMs'], 500)
        self.assertEqual(worker.queue.get_nowait()[0], 1000)

    def test_network_drop_retries_new_soniox_connection_and_marks_gap(self):
        worker = StreamWorker.__new__(StreamWorker)
        worker.args = SimpleNamespace(allow_upload=True, structured=True, language='auto', prompt='')
        worker.name = 'soniox'
        worker.ready = threading.Event()
        worker.failed = threading.Event()
        worker.finished = threading.Event()
        worker.restart_requested = threading.Event()
        worker.finished.set()
        worker.queue = queue.Queue()
        worker.queue.put_nowait((0, bytes(3200)))
        worker.queue.put_nowait((100, bytes(3200)))
        worker.offered_bytes = 6400
        worker.confirmed_ms = 0
        worker.gap_start_ms = None
        worker.had_gap = False
        worker.reconnect_attempt = 0
        events = []
        worker.events = SimpleNamespace(emit=lambda kind, name, **data: events.append((kind, data)))
        attempts = []

        def fake_soniox(key, first, blocks):
            attempts.append(first[0])
            if len(attempts) == 1:
                raise OSError('offline')

        worker.soniox = fake_soniox
        with patch('live_streams.api_key', return_value='test-key'):
            worker.run()
        self.assertEqual(attempts, [0, 100])
        self.assertFalse(worker.failed.is_set())
        self.assertEqual([(data['startMs'], data['endMs']) for kind, data in events if kind == 'GAP'], [(0, 200)])
        self.assertIn('RECONNECTING', [kind for kind, _ in events])

    def _run_response(self, opcode, payload, calls=None):
        class FakeSocket:
            def send(self, value):
                pass

            def send_binary(self, value):
                if calls is not None:
                    calls.append('audio')

            def settimeout(self, value):
                if calls is not None:
                    calls.append(('socket_timeout', value))

            def recv_data(self, control_frame=False):
                if calls is not None:
                    calls.append('receive')
                return opcode, payload

            def close(self):
                pass

        worker = StreamWorker.__new__(StreamWorker)
        worker.args = SimpleNamespace(language='ko', prompt='')
        worker.failed = threading.Event()
        worker.restart_requested = threading.Event()
        worker.queue = queue.Queue()
        worker.name = 'soniox'
        worker.gap_start_ms = None
        worker.confirmed_ms = 0
        worker.events = SimpleNamespace(emit=lambda *args, **kwargs: None)
        with patch('websocket.create_connection', return_value=FakeSocket()) as connect:
            with self.assertRaises(RuntimeError) as caught:
                worker.soniox('test-key', (0, b'\x00\x00'), iter(()))
            self.assertEqual(connect.call_args.kwargs['timeout'], 5)
        return str(caught.exception)

    def test_server_error_exposes_code_type_and_request_id_only(self):
        payload = json.dumps({'error_code': 402, 'error_type': 'payment_required',
                              'error_message': 'secret-key echoed here',
                              'request_id': 'abc-123'}).encode()
        message = self._run_response(websocket.ABNF.OPCODE_TEXT, payload)
        self.assertIn('error_code=402', message)
        self.assertIn('error_type=payment_required', message)
        self.assertIn('request_id=abc-123', message)
        self.assertNotIn('secret-key', message)

    def test_close_frame_exposes_code_without_reason(self):
        message = self._run_response(websocket.ABNF.OPCODE_CLOSE,
                                     (1008).to_bytes(2, 'big') + b'secret-key echoed here')
        self.assertIn('close_code=1008', message)
        self.assertNotIn('secret-key', message)

    def test_provider_identifier_cannot_be_free_text(self):
        self.assertEqual(_safe_diagnostic('key: secret'), 'invalid')

    def test_first_audio_is_sent_before_receiving(self):
        calls = []
        self._run_response(websocket.ABNF.OPCODE_CLOSE, (1000).to_bytes(2, 'big'), calls)
        self.assertEqual(calls[0], 'audio')
        self.assertIn(('socket_timeout', 5), calls)
