"""Offline invariants for source-identical local preparation reuse."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pdf_pipeline import write_json
import pdf_study_layout_cache as layout_cache


class LayoutCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.source = self.folder / 'source.pdf'
        self.source.write_bytes(b'synthetic source content')
        self.document = {'documentId': hashlib.sha256(self.source.read_bytes()).hexdigest(),
                         'fingerprint': 'local-extraction-v1',
                         'pages': [{'number': n, 'nativeText': f'Original source {n}'}
                                   for n in range(1, 4)]}
        self.calls = []

    def extractor(self, folder, document, targets, cache):
        self.calls.append(tuple(targets))
        blocks = [{'id': f'v2p{n}f0', 'page': n, 'text': document['pages'][n - 1]['nativeText'],
                   'kind': 'text', 'hasVisual': False, 'bbox': [.1, .1, .9, .3],
                   'wordIds': [f'p{n}w0'], 'headingId': None}
                  for n in targets]
        write_json(Path(cache) / 'local-layout.json',
                   {'version': 'test-layout-v1',
                    'pages': [{'page': n, 'words': [{'id': f'p{n}w0', 'text': f'word{n}'}],
                               'fragments': [b for b in blocks if b['page'] == n]}
                              for n in targets], 'excludedPageNumbers': []})
        return blocks

    def extract(self, targets=(1, 2, 3), cache='study-a', **kwargs):
        return layout_cache.extract_layout(
            self.folder, self.document, targets,
            None if cache is None else self.folder / cache,
            extractor=kwargs.pop('extractor', self.extractor),
            layout_version=kwargs.pop('layout_version', 'test-layout-v1'), **kwargs)

    def cache_path(self):
        return next((self.folder / 'generated' / 'local-layout-cache').glob('*.json'))

    def corrupt(self, change):
        path = self.cache_path()
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_two_identical_sources_extract_once_and_restore_original_audit(self):
        first_status, second_status = {}, {}
        first = self.extract(diagnostics=first_status)
        original = copy.deepcopy(first)
        first[0]['planRole'] = 'decoration'
        first[0]['wordIds'].clear()
        second = self.extract(cache='study-b', diagnostics=second_status)
        self.assertEqual(second, original)
        self.assertEqual(self.calls, [(1, 2, 3)])
        self.assertFalse(first_status['hit'])
        self.assertTrue(second_status['hit'])
        audit = json.loads((self.folder / 'study-b' / 'local-layout.json').read_text())
        self.assertNotIn('planRole', audit['pages'][0]['fragments'][0])
        second[0]['wordIds'].clear()
        self.assertEqual(self.extract()[0]['wordIds'], ['p1w0'])

    def test_reading_plan_without_output_cache_can_seed_generation_reuse(self):
        first = self.extract(cache=None)
        self.assertEqual(self.extract(cache='generation'), first)
        self.assertEqual(len(self.calls), 1)

    def test_document_identity_and_extraction_fingerprint_invalidate(self):
        self.extract()
        self.document['documentId'] = 'different-document'
        self.extract()
        self.document['fingerprint'] = 'new-extraction-version'
        self.extract()
        self.assertEqual(len(self.calls), 3)

    def test_actual_source_bytes_invalidate_even_with_identical_metadata(self):
        self.extract()
        previous = self.source.stat()
        self.source.write_bytes(b'Synthetic source content')
        import os
        os.utime(self.source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        self.extract()
        self.assertEqual(len(self.calls), 2)

    def test_layout_version_invalidation_does_not_reuse_original_extraction(self):
        self.extract()
        # The altered test version intentionally cannot cache this extractor's
        # older audit; it must still return fresh output rather than old data.
        self.extract(layout_version='test-layout-v2')
        self.assertEqual(len(self.calls), 2)

    def test_page_range_and_order_have_independent_source_identity(self):
        self.extract(targets=(1, 2))
        self.extract(targets=(2, 1))
        self.extract(targets=(1, 2, 3))
        self.extract(targets=(1, 2))
        self.assertEqual(self.calls, [(1, 2), (2, 1), (1, 2, 3)])

    def test_native_fallback_text_change_invalidates_but_generated_fields_do_not(self):
        self.extract()
        self.document['pages'][0]['nativeText'] = 'Corrected original text'
        self.extract()
        self.document['pages'][0]['generated'] = True
        self.document['pages'][0]['pageAnalysis'] = {'state': 'ready'}
        self.document['runUsage'] = {'usd': .1}
        self.extract()
        self.assertEqual(len(self.calls), 2)

    def test_mutated_canonical_plan_blocks_are_never_read_as_original_source(self):
        root = self.folder / 'study-a'
        write_json(root / 'blocks.json', [{'id': 'forged', 'planRole': 'decoration'}])
        output = self.extract()
        self.assertEqual(output[0]['id'], 'v2p1f0')
        self.assertNotIn('planRole', output[0])

    def test_malformed_json_falls_back_to_the_original_extractor(self):
        self.extract()
        self.cache_path().write_text('{')
        status = {}
        self.extract(diagnostics=status)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(status['hit'])

    def test_corruption_or_incomplete_catalog_falls_back(self):
        changes = [lambda v: v['blocks'][0].update(text='changed'),
                   lambda v: v['blocks'].pop(),
                   lambda v: v.update(complete=False),
                   lambda v: v['audit']['pages'].pop(),
                   lambda v: v['audit']['pages'].append(None),
                   lambda v: v['blocks'][0].update(bbox=[float('nan'), 0, 1, 1]),
                   lambda v: v.update(identity={})]
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                self.extract()
                previous = len(self.calls)
                self.corrupt(change)
                status = {}
                self.extract(diagnostics=status)
                self.assertEqual(len(self.calls), previous + 1)
                self.assertFalse(status['hit'])

    def test_source_change_during_extraction_is_not_committed(self):
        def changing(folder, document, targets, cache):
            value = self.extractor(folder, document, targets, cache)
            self.source.write_bytes(b'changed during extraction')
            return value
        status = {}
        self.extract(extractor=changing, diagnostics=status)
        self.assertEqual(status['reason'], 'source_changed_during_extraction')
        self.assertFalse((self.folder / 'generated' / 'local-layout-cache').exists())

    def test_interrupted_extraction_is_not_committed(self):
        def interrupted(*args):
            raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            self.extract(extractor=interrupted)
        self.assertFalse((self.folder / 'generated' / 'local-layout-cache').exists())

    def test_simultaneous_consumers_share_one_extraction_and_get_independent_blocks(self):
        outputs = []
        def slow(*args):
            time.sleep(.02)
            return self.extractor(*args)
        threads = [threading.Thread(target=lambda: outputs.append(self.extract(extractor=slow)))
                   for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(outputs), 4)
        self.assertEqual(len(self.calls), 1)
        outputs[0][0]['text'] = 'mutated'
        self.assertNotEqual(outputs[1][0]['text'], 'mutated')

    def test_cache_write_failure_does_not_discard_fresh_source(self):
        from pdf_pipeline import write_json as real_write
        def fail_cache(path, value):
            if Path(path).parent.name == 'local-layout-cache':
                raise OSError('read-only derived cache')
            return real_write(path, value)
        with patch('pdf_pipeline.write_json', side_effect=fail_cache):
            output = self.extract()
        self.assertEqual(output[0]['id'], 'v2p1f0')


if __name__ == '__main__':
    unittest.main()
