"""Read-only, source-exact repair of boundary sentences in completed caches."""
import copy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_new_concept_ver99_study as study
import pdf_saved_boundaries as boundaries
import pdf_saved_tables as tables


class SavedBoundaryTests(unittest.TestCase):
    sentence = '이는 그림에 제시된 관측 수치이며, 그 자체로 실제 결과를 뜻하지는 않아요.'

    def setUp(self):
        boundaries._MEMO.clear()
        tables._MEMO.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.cache = self.folder/'generated/new-concept-v99/cache'
        self.cache.mkdir(parents=True)
        self.document = {'documentId': 'fixture', 'fingerprint': 'source-v1',
                         'pages': [{'number': 1, 'label': '1'}]}
        self.block = {'id': 'a', 'page': 1, 'kind': 'visual', 'text': '',
                      'bbox': [0, 0, 1, 1], 'hasVisual': True, 'visualKinds': ['raster']}
        self.job = {'id': 'job', 'title': '관측과 결과', 'blocks': [self.block]}
        self.raw = {'concepts': [{'title': '관측과 결과', 'segments': [
            {'kind': 'definition', 'text': '관측 수치는 관찰한 값을 나타내요.', 'blockIds': ['a']},
            {'kind': 'explanation', 'text': '값은 10으로 표시돼요. ' + self.sentence, 'blockIds': ['a']},
            {'kind': 'explanation', 'text': '비교할 때는 조건을 맞춰요. 같은 단위도 확인해요.', 'blockIds': ['a']},
            {'kind': 'easyExplanation', 'text': '보인 값과 실제 결과를 구별해요.', 'blockIds': ['a']},
        ]}], 'tables': [], 'sequences': [], 'uncertainBlocks': [], 'excludedBlocks': []}
        old = study.validate(self.raw, self.job, self.document, preserve_boundaries=False)
        self.result = study.assemble(self.document, 'new-concept-v99', 'document', 0,
                                     [1], [self.job], {0: old}, [], [])
        self.write()
        usage = self.folder/'usage'
        usage.mkdir()
        (usage/'existing.json').write_text('{"requests": []}')
        guard = patch.object(ai.Provider, 'complete', side_effect=AssertionError('no paid repair'))
        self.paid = guard.start()
        self.addCleanup(guard.stop)
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('no network'))
        guard.start()
        self.addCleanup(guard.stop)

    def write(self):
        for name, value in (('result.json', self.result), ('blocks.json', [self.block]),
                            ('manifest.json', {'jobs': [self.job]}), ('response-job.json', self.raw)):
            (self.cache/name).write_text(json.dumps(value, ensure_ascii=False))

    def restore(self, result=None, document=None, validator=None):
        return boundaries.restore_saved_boundaries(self.folder, document or self.document,
            self.result if result is None else result, validator or study.validate,
            study.attach_comparison_tables)

    def snapshot(self):
        return {str(p): p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}

    def test_append_exact_supported_sentence_preserves_old_prose_everywhere_and_files(self):
        original = copy.deepcopy(self.result)
        files = self.snapshot()
        value = self.restore()
        self.assertEqual(value['savedBoundaryRestoration']['additionalApiRequests'], 0)
        self.assertEqual(value['savedBoundaryRestoration']['items'][0]['sourceIds'], ['a'])
        self.assertEqual(value['savedBoundaryRestoration']['items'][0]['sentences'], [self.sentence])
        for old, new in ((original['sections'][0]['body'], value['sections'][0]['body']),
                         (original['sections'][0]['parts'][0]['body'], value['sections'][0]['parts'][0]['body']),
                         (original['concepts'][0]['entries'][0]['explanation'], value['concepts'][0]['entries'][0]['explanation'])):
            self.assertEqual(new, old + '\n\n' + self.sentence)
        self.assertEqual(value['sections'][0]['parts'][0]['evidence'],
                         original['sections'][0]['parts'][0]['evidence'])
        self.assertEqual(self.result, original)
        self.assertEqual(self.snapshot(), files)
        self.paid.assert_not_called()

    def test_memo_and_already_repaired_values_do_not_replay_or_duplicate(self):
        with patch.object(boundaries, '_read', wraps=boundaries._read) as read:
            first = self.restore()
            reads = read.call_count
            self.assertEqual(self.restore(), first)
            self.assertEqual(read.call_count, reads)
            self.assertEqual(self.restore(first), first)
            self.assertEqual(read.call_count, reads)
        self.assertEqual(first['sections'][0]['parts'][0]['body'].count(self.sentence), 1)
        self.assertNotIn('result', next(iter(boundaries._MEMO.values())))

    def test_changed_prose_evidence_source_or_section_cannot_borrow_raw(self):
        self.restore()  # Positive memo cannot be reused for edited views.
        for change in ('prose', 'evidence', 'source', 'section', 'card'):
            with self.subTest(change=change):
                value = copy.deepcopy(self.result)
                doc = copy.deepcopy(self.document)
                if change == 'prose': value['sections'][0]['parts'][0]['body'] += ' 다른 주장'
                elif change == 'evidence': value['sections'][0]['parts'][0]['evidence'][0]['bbox'] = [0, 0, .2, .2]
                elif change == 'source': value['sourceFingerprint'] = doc['fingerprint'] = 'other-source'
                elif change == 'section': value['sections'][0]['body'] += ' 별도 내용'
                else: value['concepts'][0]['entries'][0]['explanation'] += ' 별도 내용'
                original = copy.deepcopy(value)
                restored = self.restore(value, doc)
                self.assertNotIn('savedBoundaryRestoration', restored)
                self.assertEqual(value, original)

    def test_source_geometry_uncertainty_and_invalid_math_are_not_bypassed(self):
        for change in ('geometry', 'uncertain', 'math'):
            with self.subTest(change=change):
                raw = copy.deepcopy(self.raw)
                job = copy.deepcopy(self.job)
                if change == 'geometry': job['blocks'][0]['bbox'] = [0, 0, .2, .2]
                elif change == 'uncertain': raw['uncertainBlocks'] = [{'blockId': 'a', 'reason': '판독 불가'}]
                else: raw['concepts'][0]['segments'][1]['text'] = r'\(2+2=5\)예요. ' + self.sentence
                (self.cache/'manifest.json').write_text(json.dumps({'jobs': [job]}))
                (self.cache/'response-job.json').write_text(json.dumps(raw))
                self.assertNotIn('savedBoundaryRestoration', self.restore())

    def test_other_validator_changes_fail_the_exact_roundtrip(self):
        def changed(raw, job, document, **kwargs):
            result = study.validate(raw, job, document, **kwargs)
            if kwargs.get('preserve_boundaries', True):
                result['concepts'][0]['explanation'] += ' 원래 없던 추가 주장'
            return result
        self.assertNotIn('savedBoundaryRestoration', self.restore(validator=changed))

    def test_ambiguous_parts_and_unknown_job_paths_are_skipped(self):
        self.result['sections'][0]['parts'].append(copy.deepcopy(self.result['sections'][0]['parts'][0]))
        self.write()
        self.assertNotIn('savedBoundaryRestoration', self.restore())
        self.result['sections'][0]['parts'].pop()
        self.job['id'] = '../job'
        self.write()
        self.assertNotIn('savedBoundaryRestoration', self.restore())

    def test_source_verified_table_repair_and_boundary_repair_can_coexist(self):
        self.raw['tables'] = [{'conceptTitle': '관측과 결과',
            'headers': ['유형', '가', '나', '다', '라'],
            'rows': [['A', '1', '2', '3', '4'], ['B', '5', '6', '7', '8']], 'blockIds': ['a']}]
        self.write()  # Historical prose lacks both the table and the sentence.
        table_view = tables.restore_saved_tables(self.folder, self.document, self.result,
                                                 study.attach_comparison_tables)
        self.assertIn('| 유형 | 가 | 나 | 다 | 라 |', table_view['sections'][0]['parts'][0]['body'])
        files = self.snapshot()
        value = self.restore(table_view)
        body = value['sections'][0]['parts'][0]['body']
        self.assertEqual(body.count('| 유형 | 가 | 나 | 다 | 라 |'), 1)
        self.assertEqual(body.count(self.sentence), 1)
        self.assertTrue(body.startswith(table_view['sections'][0]['parts'][0]['body']))
        self.assertEqual(files, self.snapshot())

    def test_changed_paid_reply_invalidates_positive_memo_without_rewriting_saved_text(self):
        self.assertIn('savedBoundaryRestoration', self.restore())
        self.raw['concepts'][0]['segments'][1]['text'] = '값은 11로 표시돼요. ' + self.sentence
        self.write()
        self.assertNotIn('savedBoundaryRestoration', self.restore())

    def test_already_present_boundary_and_unseen_dates_are_not_filled_in(self):
        new = study.validate(self.raw, self.job, self.document)
        self.result = study.assemble(self.document, 'new-concept-v99', 'document', 0,
                                    [1], [self.job], {0: new}, [], [])
        self.write()
        value = self.restore()
        self.assertNotIn('savedBoundaryRestoration', value)
        self.assertEqual(value['sections'], self.result['sections'])
        self.assertEqual(value['sections'][0]['parts'][0]['body'].count(self.sentence), 1)
        self.assertNotIn('2026.10.01', json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
