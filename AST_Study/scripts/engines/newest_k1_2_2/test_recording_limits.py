import queue
import threading
import unittest
from types import SimpleNamespace

from lecture_stream import MAX_RECORDING_SECONDS
from live_streams import StreamWorker


class RecordingLimitTest(unittest.TestCase):
    def test_four_and_a_half_hour_boundary_stops_before_sending_extra_audio(self):
        for provider in ('soniox', 'daglo'):
            with self.subTest(provider=provider):
                events = []
                worker = StreamWorker.__new__(StreamWorker)
                worker.name = provider
                worker.args = SimpleNamespace(max_stream_seconds=MAX_RECORDING_SECONDS)
                worker.failed = threading.Event()
                worker.finished = threading.Event()
                worker.queue = queue.Queue(maxsize=10)
                # Simulate the tail of a long recording without waiting or opening a socket.
                worker.offered_bytes = 270 * 60 * 32000 - 3200
                worker.events = SimpleNamespace(emit=lambda kind, name, **data: events.append((kind, data)))
                worker.offer(bytes(3200))
                self.assertFalse(worker.finished.is_set())
                self.assertEqual(worker.queue.qsize(), 1)
                worker.offer(bytes(3200))
                self.assertTrue(worker.finished.is_set())
                self.assertEqual(worker.queue.qsize(), 1)
                self.assertEqual(worker.offered_bytes, 270 * 60 * 32000)
                self.assertIn('16200', events[0][1]['text'])


if __name__ == '__main__':
    unittest.main()
