import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_hierarchy_projection_cache as cache


class ProjectionCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'document'
        self.root = self.folder / 'generated/new-concept-v99'
        self.cache = self.root / 'fixture'
        self.cache.mkdir(parents=True)
        self.pdf = self.folder / 'source.pdf'
        self.pdf.write_bytes(b'original-pdf-fixture')
        self.blocks = self.cache / 'blocks.json'
        self.blocks.write_text('[{"id":"b","text":"원래 출처"}]')
        self.result = {'strategy': 'new-concept-v99', 'documentId': 'doc',
                       'sourceFingerprint': 'fp', 'scope': 'document', 'page': 0,
                       'hierarchy': {'version': 'study-hierarchy-5'},
                       'sections': [{'body': '유료 설명을 보존해요.'}],
                       'runUsage': {'usageBasedUsd': .03, 'requests': 2}}
        self.document = {'documentId': 'doc', 'fingerprint': 'fp',
                         'pages': [{'label': '8'}, {'label': '9'}]}
        self.projection = copy.deepcopy(self.result)
        self.projection['hierarchy'] = {'version': 'study-hierarchy-7', 'displayRevision':cache.DISPLAY_REVISION, 'nodes': []}
        self.saved = self.cache / 'result.json'
        self.saved.write_text(json.dumps(self.result, ensure_ascii=False))
        self.paid = self.folder / 'generated/paid-responses/original.json'
        self.paid.parent.mkdir()
        self.paid.write_text('{"originalPaidResponse":true}')
        self.usage = self.folder / 'usage/original.json'
        self.usage.parent.mkdir()
        self.usage.write_text('{"estimatedUsd":0.03}')

    def save(self, **options):
        return cache.store(self.folder, self.cache, self.result, self.document,
                           self.blocks, self.projection, **options)

    def test_old_display_revision_is_not_a_current_projection(self):
        self.projection['hierarchy'].pop('displayRevision')
        self.assertFalse(self.save())

    def load(self):
        return cache.lookup(self.folder, self.cache, self.result, self.document)

    def test_hit_is_detached_and_only_derived_sidecar_is_written(self):
        originals = {p: p.read_bytes() for p in [self.pdf, self.blocks, self.saved, self.paid, self.usage]}
        before_result = copy.deepcopy(self.result)
        before_projection = copy.deepcopy(self.projection)
        self.assertTrue(self.save(expected_pdf_stamp=cache.stamp(self.pdf),
                                  expected_blocks_stamp=cache.stamp(self.blocks)))
        first = self.load()
        self.assertEqual(first, self.projection)
        self.assertIsNot(first, self.projection)
        first['sections'][0]['body'] = 'changed detached result'
        self.assertEqual(self.load(), self.projection)
        self.assertEqual(self.result, before_result)
        self.assertEqual(self.projection, before_projection)
        self.assertTrue(all(path.read_bytes() == value for path, value in originals.items()))
        self.assertTrue((self.cache / cache.FILENAME).is_file())

    def test_different_result_document_labels_strategy_and_scope_are_misses(self):
        self.assertTrue(self.save())
        for field, value in [('documentId', 'other'), ('scope', 'page'), ('page', 8),
                             ('sourceFingerprint', 'changed'), ('sections', [{'body': 'new'}]),
                             ('runUsage', {'usageBasedUsd': .04}), ('strategy', 'other')]:
            result = copy.deepcopy(self.result)
            result[field] = value
            self.assertIsNone(cache.lookup(self.folder, self.cache, result, self.document), field)
        for field, value in [('documentId', 'other'), ('fingerprint', 'other'),
                             ('pages', [{'label': 'different'}, {'label': '9'}])]:
            document = copy.deepcopy(self.document)
            document[field] = value
            self.assertIsNone(cache.lookup(self.folder, self.cache, self.result, document), field)
        self.assertEqual(self.load(), self.projection)

    def test_canonical_input_key_accepts_reordered_object_keys(self):
        self.assertTrue(self.save())
        result = dict(reversed(list(self.result.items())))
        self.assertEqual(cache.lookup(self.folder, self.cache, result, self.document), self.projection)

    def test_pdf_change_invalidates_even_when_mtime_is_restored(self):
        self.assertTrue(self.save())
        before = self.pdf.stat()
        self.pdf.write_bytes(b'altered-pdf--fixture')
        os.utime(self.pdf, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.pdf.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertNotEqual(cache.stamp(self.pdf)[4], before.st_ctime_ns)
        self.assertIsNone(self.load())

    def test_blocks_change_invalidates_even_when_mtime_is_restored(self):
        self.assertTrue(self.save())
        before = self.blocks.stat()
        self.blocks.write_text('[{"id":"b","text":"수정 출처"}]')
        os.utime(self.blocks, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertIsNone(self.load())

    def test_new_preferred_blocks_invalidates_fallback_projection(self):
        fallback = self.root / 'older/blocks.json'
        fallback.parent.mkdir()
        fallback.write_text(self.blocks.read_text())
        self.blocks.unlink()
        self.assertTrue(cache.store(self.folder, self.cache, self.result, self.document,
                                    fallback, self.projection))
        self.assertEqual(self.load(), self.projection)
        before = cache.stamp(fallback)
        self.blocks.write_text('[{"id":"b","text":"new preferred source"}]')
        self.assertEqual(cache.stamp(fallback), before)
        self.assertIsNone(self.load())

    def test_new_updated_and_removed_candidates_invalidate_without_changing_selected_source(self):
        self.assertTrue(self.save())
        selected = cache.stamp(self.blocks)
        other = self.root / 'newer/blocks.json'
        other.parent.mkdir()
        other.write_text('[]')
        self.assertIsNone(self.load())
        self.assertTrue(self.save())
        self.assertEqual(self.load(), self.projection)
        previous = other.stat()
        other.write_text('[{"id":"different"}]')
        os.utime(other, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        self.assertIsNone(self.load())
        self.assertTrue(self.save())
        other.unlink()
        self.assertEqual(cache.stamp(self.blocks), selected)
        self.assertIsNone(self.load())

    def test_expected_layout_guard_covers_source_selection_to_store_race(self):
        self.assertTrue(self.save())
        before = (self.cache / cache.FILENAME).read_bytes()
        expected = cache.layout_stamp(self.folder, self.cache, self.result)
        self.assertIsNotNone(expected)
        self.assertTrue(self.save(expected_layout_stamp=expected))
        other = self.root / 'appeared/blocks.json'
        other.parent.mkdir()
        other.write_text('[]')
        self.assertFalse(self.save(expected_layout_stamp=expected))
        self.assertEqual((self.cache / cache.FILENAME).read_bytes(), before)
        self.assertFalse(self.save(expected_layout_stamp=None))
        self.assertIsNone(cache.layout_stamp(self.folder, None, self.result))

    def test_layout_change_during_write_or_lookup_is_a_miss(self):
        self.assertTrue(self.save())
        original = (self.cache / cache.FILENAME).read_bytes()
        other = self.root / 'appeared/blocks.json'
        other.parent.mkdir()
        real_canonical = cache._canonical
        def change_after_encode(value):
            encoded = real_canonical(value)
            if isinstance(value, dict) and 'projectionSha256' in value:
                other.write_text('[]')
            return encoded
        with patch.object(cache, '_canonical', side_effect=change_after_encode):
            self.assertFalse(self.save())
        self.assertEqual((self.cache / cache.FILENAME).read_bytes(), original)
        self.assertFalse(list(self.cache.glob('.display-hierarchy-*.tmp')))
        other.unlink()
        self.assertEqual(self.load(), self.projection)
        real_projection = cache._projection
        def change_after_read(value):
            other.write_text('[]')
            return real_projection(value)
        with patch.object(cache, '_projection', side_effect=change_after_read):
            self.assertIsNone(self.load())

    def test_layout_snapshot_and_cache_hit_never_parse_source_files(self):
        self.assertTrue(self.save())
        with (patch.object(Path, 'read_text', side_effect=AssertionError('No source JSON parse')),
              patch.object(Path, 'read_bytes', side_effect=AssertionError('No source file read'))):
            self.assertIsNotNone(cache.layout_stamp(self.folder, self.cache, self.result))
            self.assertEqual(self.load(), self.projection)

    def test_expected_source_guards_reject_inflight_changes_without_overwriting_cache(self):
        self.assertTrue(self.save())
        before = (self.cache / cache.FILENAME).read_bytes()
        pdf_stamp = cache.stamp(self.pdf)
        blocks_stamp = cache.stamp(self.blocks)
        self.pdf.write_bytes(b'different PDF')
        self.assertFalse(self.save(expected_pdf_stamp=pdf_stamp))
        self.blocks.write_text('[]')
        self.assertFalse(self.save(expected_blocks_stamp=blocks_stamp))
        self.assertEqual((self.cache / cache.FILENAME).read_bytes(), before)

    def test_source_change_during_write_skips_replace_and_cleans_temporary(self):
        self.assertTrue(self.save())
        original = (self.cache / cache.FILENAME).read_bytes()
        real_canonical = cache._canonical
        def change_after_encode(value):
            data = real_canonical(value)
            if isinstance(value, dict) and 'projectionSha256' in value:
                self.pdf.write_bytes(b'changed while encoding')
            return data
        with patch.object(cache, '_canonical', side_effect=change_after_encode):
            self.assertFalse(self.save())
        self.assertEqual((self.cache / cache.FILENAME).read_bytes(), original)
        self.assertFalse(list(self.cache.glob('.display-hierarchy-*.tmp')))

    def test_code_rule_change_invalidates(self):
        self.assertTrue(self.save())
        with patch.object(cache, '_rules_sha', return_value='different-local-rules'):
            self.assertIsNone(self.load())
        self.assertEqual(self.load(), self.projection)

    def test_corruption_duplicate_keys_checksum_and_old_version_fail_closed(self):
        self.assertTrue(self.save())
        path = self.cache / cache.FILENAME
        raw = path.read_bytes()
        for value in [b'{', b'[]', b'{"version":1,"version":1}',
                      b'{"version":NaN}', b'null']:
            path.write_bytes(value)
            self.assertIsNone(self.load())
        path.write_bytes(raw)
        envelope = json.loads(raw)
        for field, value in [('version', True), ('version', 99), ('hierarchyVersion', 'old'),
                             ('projectionSha256', 'broken'), ('blocksStamp', [0, 0, 0, 0, 0])]:
            altered = copy.deepcopy(envelope)
            altered[field] = value
            path.write_text(json.dumps(altered))
            self.assertIsNone(self.load(), field)
        altered = copy.deepcopy(envelope)
        altered['projection']['sections'][0]['body'] = 'corrupt stored explanation'
        path.write_text(json.dumps(altered))
        self.assertIsNone(self.load())

    def test_only_blocks_inside_this_document_strategy_are_eligible(self):
        self.assertTrue(self.save())
        path = self.cache / cache.FILENAME
        envelope = json.loads(path.read_text())
        other = self.folder / 'generated/other/blocks.json'
        other.parent.mkdir()
        other.write_text('[]')
        detached = Path(self.temp.name) / 'outside/blocks.json'
        detached.parent.mkdir()
        detached.write_text('[]')
        for value in [str(other), str(detached), '../outside/blocks.json', str(self.saved)]:
            altered = copy.deepcopy(envelope)
            altered['blocksPath'] = value
            altered['blocksStamp'] = list(cache.stamp(other))
            path.write_text(json.dumps(altered))
            self.assertIsNone(self.load())
        self.assertFalse(cache.store(self.folder, self.cache, self.result, self.document, detached, self.projection))
        self.assertFalse(cache.store(self.folder, detached.parent, self.result, self.document, self.blocks, self.projection))

    def test_symlinked_blocks_and_cache_cannot_escape_strategy_root(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'blocks.json').write_text('[]')
        link = self.root / 'link'
        link.symlink_to(outside, target_is_directory=True)
        self.assertFalse(cache.store(self.folder, self.cache, self.result, self.document, link / 'blocks.json', self.projection))
        self.assertFalse(cache.store(self.folder, link, self.result, self.document, self.blocks, self.projection))
        self.assertTrue(self.save())
        path = self.cache / cache.FILENAME
        copy_path = outside / 'saved-projection.json'
        copy_path.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy_path)
        self.assertIsNone(self.load())

    def test_read_write_and_serialization_failures_never_escape(self):
        self.assertIsNone(self.load())
        self.assertIsNone(cache.lookup(self.folder, None, self.result, self.document))
        self.assertFalse(cache.store(self.folder, None, self.result, self.document, self.blocks, self.projection))
        with patch.object(cache.os, 'replace', side_effect=OSError('fixture write error')):
            self.assertFalse(self.save())
        self.assertFalse(list(self.cache.glob('.display-hierarchy-*.tmp')))
        self.assertTrue(self.save())
        with patch.object(cache.os, 'open', side_effect=OSError('fixture read error')):
            self.assertIsNone(self.load())
        invalid = copy.deepcopy(self.projection)
        invalid['nan'] = float('nan')
        self.assertFalse(cache.store(self.folder, self.cache, self.result, self.document, self.blocks, invalid))

    def test_envelope_size_bound_and_hierarchy_version(self):
        with patch.object(cache, 'MAX_BYTES', 10):
            self.assertFalse(self.save())
        self.assertTrue(self.save())
        with patch.object(cache, 'MAX_BYTES', 10):
            self.assertIsNone(self.load())
        old = copy.deepcopy(self.projection)
        old['hierarchy']['version'] = 'study-hierarchy-6'
        self.assertFalse(cache.store(self.folder, self.cache, self.result, self.document, self.blocks, old))
        with patch.object(cache, '_ACTIVE_HIERARCHY_VERSION', 'study-hierarchy-8'):
            self.assertFalse(self.save())
            self.assertIsNone(self.load())


if __name__ == '__main__':
    unittest.main()
