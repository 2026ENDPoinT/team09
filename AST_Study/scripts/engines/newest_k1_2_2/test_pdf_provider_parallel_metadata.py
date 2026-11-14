"""Parallel request metadata must share the durable ledger's write lock."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import pdf_ai


class ProviderParallelMetadataTests(unittest.TestCase):
    def test_sending_metadata_waits_for_a_sibling_ledger_snapshot(self):
        first_at_slot = threading.Event()
        second_snapshot = threading.Event()
        first_transport = threading.Event()
        observed_snapshot = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            provider = None

            def transport(body):
                self.assertFalse(provider._lock._is_owned(), 'network work must not hold the ledger lock')
                if threading.current_thread().name.endswith('_0'):
                    first_transport.set()
                return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}

            provider = pdf_ai.Provider(Path(directory), True, 1, transport=transport)
            original_write = pdf_ai.write_json

            def snapshot(path, value):
                rows = provider.ledger['requests']
                if (path == provider.ledger_path and len(rows) == 2
                        and not observed_snapshot.is_set() and 'sentAtMs' not in rows[1]):
                    observed_snapshot.set()
                    self.assertTrue(provider._lock._is_owned())
                    second_snapshot.set()
                    # The first worker is released from admission while this
                    # sibling still owns the ledger snapshot. Its metadata and
                    # transport must wait until serialization releases the lock.
                    self.assertFalse(first_transport.wait(.2))
                    self.assertNotIn('sentAtMs', rows[0])
                original_write(path, value)

            @contextmanager
            def slot(**options):
                if threading.current_thread().name.endswith('_0'):
                    first_at_slot.set()
                    if not second_snapshot.wait(2):
                        raise AssertionError('second request never reached its ledger snapshot')
                yield None

            def complete(label):
                provider.context = {'kind': 'quiz_questions', 'quizUnitId': label}
                return provider.complete({'task': 'quiz_questions', 'unit': label}, max_output=20)

            with patch.object(pdf_ai, 'api_slot', slot), patch.object(pdf_ai, 'write_json', snapshot):
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix='metadata') as pool:
                    first = pool.submit(complete, 'one')
                    self.assertTrue(first_at_slot.wait(2))
                    second = pool.submit(complete, 'two')
                    self.assertEqual(first.result(timeout=3), {'ok': True})
                    self.assertEqual(second.result(timeout=3), {'ok': True})
            self.assertTrue(observed_snapshot.is_set())
            self.assertTrue(first_transport.is_set())
            self.assertEqual([r['state'] for r in provider.ledger['requests']], ['settled', 'settled'])
            self.assertTrue(all(r['maxOutputTokens'] == 20 for r in provider.ledger['requests']))


if __name__ == '__main__':
    unittest.main()
