"""Local cache upgrades must recover source tables without buying new output."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_new_concept_ver99_study as study
import pdf_saved_tables as tables
from pdf_saved_tables import restore_saved_tables


class SavedTableTests(unittest.TestCase):
    def setUp(self):
        tables._MEMO.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.cache = self.folder/'generated/new-concept-v99/cache'
        self.cache.mkdir(parents=True)
        self.document = {'documentId': 'sample', 'fingerprint': 'source-v1'}
        self.block = {'id': 'figure', 'page': 2, 'kind': 'visual', 'text': '',
                      'bbox': [0, 0, 1, 1], 'hasVisual': True, 'visualKinds': ['raster']}
        evidence = [{'sourceId': 'figure', 'page': 2}]
        body = '기관마다 기능을 나누어 맡아요.\n\n각 기관의 기능을 살펴요.'
        part = {'title': '기관의 기능', 'body': body, 'evidence': evidence}
        card = {'name': '기관의 기능', 'definition': '기관마다 기능을 나누어 맡아요.',
                'explanation': '각 기관의 기능을 살펴요.', 'evidence': evidence}
        self.result = {'documentId': 'sample', 'sourceFingerprint': 'source-v1',
                       'strategy': 'new-concept-v99', 'model': 'gpt-6-luna',
                       'scope': 'document', 'page': 0, 'processingComplete': True,
                       'sections': [{'parts': [part], 'body': body}],
                       'concepts': [{'name': '기관', 'entries': [card]}]}
        self.raw = {'concepts': [{'title': '기관의 기능',
                                 'definition': '기관마다 기능을 나누어 맡아요.',
                                 'explanation': '각 기관의 기능을 살펴요.',
                                 'easyExplanation': '여러 부위가 힘을 합쳐요.',
                                 'blockIds': ['figure']}],
                    'tables': [{'conceptTitle': '기관의 기능', 'headers': ['부위', '기능'],
                                'rows': [[f'기관{i}', f'기능{i}'] for i in range(14)],
                                'blockIds': ['figure']}],
                    'uncertainBlocks': [], 'excludedBlocks': []}
        self.job = {'id': 'job', 'blocks': [self.block]}
        self.write()

    def write(self):
        for name, value in [('result.json', self.result), ('blocks.json', [self.block]),
                            ('manifest.json', {'jobs': [self.job]}),
                            ('response-job.json', self.raw)]:
            (self.cache/name).write_text(json.dumps(value), encoding='utf-8')

    def restore(self, result=None, document=None):
        return restore_saved_tables(self.folder, document or self.document,
                                    result or self.result, study.attach_comparison_tables)

    def test_long_table_appears_everywhere_without_editing_source_or_existing_prose(self):
        before = {p.name: p.read_bytes() for p in self.cache.iterdir()}
        original = copy.deepcopy(self.result)
        value = self.restore()
        self.assertEqual(value['savedTableRestoration']['additionalApiRequests'], 0)
        self.assertEqual(value['savedTableRestoration']['tables'][0]['rows'], 14)
        for text in [value['sections'][0]['body'], value['sections'][0]['parts'][0]['body'],
                     value['concepts'][0]['entries'][0]['explanation']]:
            self.assertIn('| 기관13 | 기능13 |', text)
        self.assertTrue(value['sections'][0]['parts'][0]['body'].startswith(
            original['sections'][0]['parts'][0]['body']))
        self.assertEqual(self.result, original)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.cache.iterdir()})
        self.assertEqual(self.restore(value), value)

    def test_v3_saved_formula_table_recovers_long_cells_and_absolute_values_for_free(self):
        from pdf_table_cells import markdown_cell
        self.result['savedTableVersion']='saved-source-tables-v3-multiple'
        long_formula=r'\(\sin x=x-\frac{x^{3}}{3!}+\frac{x^{5}}{5!}-\cdots\) '+('일반항과 수렴 조건을 함께 살펴요. '*10)
        rows=[['사인',long_formula],['수렴 반지름',r'\(|x-a|<R\)']]
        self.raw['tables'][0].update(headers=['관계','전개와 조건'],rows=rows)
        self.write();before={p.name:p.read_bytes() for p in self.cache.iterdir()}
        with patch.object(ai.Provider,'complete',side_effect=AssertionError('No API for saved tables')):
            value=self.restore()
        for body in (value['sections'][0]['parts'][0]['body'],
                     value['concepts'][0]['entries'][0]['explanation']):
            self.assertIn(markdown_cell(long_formula),body)
            self.assertIn(markdown_cell(rows[1][1]),body)
        self.assertEqual(value['savedTableVersion'],tables.VERSION)
        self.assertEqual(value['savedTableRestoration']['additionalApiRequests'],0)
        self.assertEqual(self.restore(value),value)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.cache.iterdir()})

    def test_five_and_more_columns_restore_without_losing_or_rebuying_cells(self):
        original=copy.deepcopy(self.result)
        for width in (5,9):
            with self.subTest(columns=width):
                headers=['부위']+[f'기능{i}' for i in range(width-1)]
                rows=[[f'기관{row}']+[f'값{row}-{column}' for column in range(width-1)]
                      for row in range(3)]
                self.raw['tables'][0].update(headers=headers,rows=rows)
                self.write()
                before={p.name:p.read_bytes() for p in self.cache.iterdir()}
                value=self.restore()
                header='| '+' | '.join(headers)+' |'
                final_row='| '+' | '.join(rows[-1])+' |'
                self.assertEqual(value['savedTableRestoration']['additionalApiRequests'],0)
                for text in (value['sections'][0]['body'],
                             value['sections'][0]['parts'][0]['body'],
                             value['concepts'][0]['entries'][0]['explanation']):
                    self.assertEqual(text.count(header),1)
                    self.assertIn(final_row,text)
                self.assertEqual(self.result,original)
                self.assertEqual(before,{p.name:p.read_bytes() for p in self.cache.iterdir()})
                self.assertEqual(self.restore(value),value)

    def test_v1_marker_does_not_block_v2_recovery_of_a_missing_five_column_table(self):
        self.result['savedTableVersion'] = 'saved-source-tables-v1'
        headers = ['기관', '위치', '구조', '기능', '특징']
        rows = [[f'기관{row}'] + [f'값{row}-{column}' for column in range(4)]
                for row in range(3)]
        self.raw['tables'][0].update(headers=headers, rows=rows)
        self.write()
        original = copy.deepcopy(self.result)
        before = {p.name: p.read_bytes() for p in self.cache.iterdir()}
        with patch.object(ai.Provider, 'complete',
                          side_effect=AssertionError('saved-table repair cannot buy output')) as paid:
            value = self.restore()
            self.assertEqual(value['savedTableVersion'], tables.VERSION)
            self.assertEqual(value['savedTableRestoration']['additionalApiRequests'], 0)
            for text in (value['sections'][0]['body'],
                         value['sections'][0]['parts'][0]['body'],
                         value['concepts'][0]['entries'][0]['explanation']):
                self.assertEqual(text.count('| ' + ' | '.join(headers) + ' |'), 1)
                for row in rows:
                    self.assertIn('| ' + ' | '.join(row) + ' |', text)
            # Repeated presentation reads do not duplicate the recovered cells.
            self.assertEqual(self.restore(value), value)
            paid.assert_not_called()
        self.assertEqual(self.result, original)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.cache.iterdir()})

    def mixed_v1_result(self):
        part = {'title': '다른 기관', 'body': '다른 기관도 기능을 나누어 맡아요.',
                'evidence': [{'sourceId': 'figure', 'page': 2}]}
        self.result['sections'][0]['parts'].append(part)
        self.result['sections'][0]['body'] += '\n\n' + part['body']
        self.result['concepts'][0]['entries'].append({'name': part['title'],
            'definition': part['body'], 'explanation': '각 기능을 비교해요.',
            'evidence': copy.deepcopy(part['evidence'])})
        self.raw['concepts'].append({**copy.deepcopy(self.raw['concepts'][0]), 'title': part['title']})
        self.raw['tables'].append({'conceptTitle': part['title'],
            'headers': ['기관', '위치', '구조', '기능', '특징'],
            'rows': [['가', '나', '다', '라', '마'], ['바', '사', '아', '자', '차']],
            'blockIds': ['figure']})
        self.write()

        def old_renderer(items, *args):
            study.attach_comparison_tables([item for item in items if len(item['headers']) <= 4], *args)

        with patch.object(tables, 'VERSION', 'saved-source-tables-v1'):
            return restore_saved_tables(self.folder, self.document, self.result, old_renderer)

    def test_mixed_v1_partial_repair_keeps_existing_table_and_recovers_only_missing_table(self):
        mixed = self.mixed_v1_result()
        original = copy.deepcopy(mixed)
        before = {p.name: p.read_bytes() for p in self.cache.iterdir()}
        self.assertIn('| 부위 | 기능 |', mixed['sections'][0]['parts'][0]['body'])
        self.assertNotIn('| 기관 | 위치 |', mixed['sections'][0]['parts'][1]['body'])
        with patch.object(ai.Provider, 'complete', side_effect=AssertionError('no paid repair')) as paid, \
             patch.object(tables, '_read', wraps=tables._read) as read:
            value = self.restore(mixed)
            reads = read.call_count
            self.assertEqual(self.restore(mixed), value)
            self.assertEqual(read.call_count, reads)
            paid.assert_not_called()
        self.assertEqual(value['savedTableVersion'], tables.VERSION)
        self.assertEqual(value['savedTableRestoration']['additionalApiRequests'], 0)
        self.assertEqual(len(value['savedTableRestoration']['tables']), 1)
        self.assertEqual(value['sections'][0]['parts'][0], mixed['sections'][0]['parts'][0])
        self.assertEqual(value['concepts'][0]['entries'][0], mixed['concepts'][0]['entries'][0])
        for text in (value['sections'][0]['body'], value['sections'][0]['parts'][1]['body'],
                     value['concepts'][0]['entries'][1]['explanation']):
            self.assertEqual(text.count('| 기관 | 위치 | 구조 | 기능 | 특징 |'), 1)
            self.assertIn('| 바 | 사 | 아 | 자 | 차 |', text)
        self.assertEqual(self.restore(value), value)
        self.assertEqual(mixed, original)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.cache.iterdir()})

    def test_mixed_v1_requires_every_old_append_to_match_verified_source_exactly(self):
        mixed = self.mixed_v1_result()
        # Populate the positive memo before attempting changed section prose.
        self.assertIn('| 기관 | 위치 |', self.restore(mixed)['sections'][0]['parts'][1]['body'])
        for change in ('prose', 'old_cell', 'card', 'section', 'evidence', 'marker'):
            with self.subTest(change=change):
                current = copy.deepcopy(mixed)
                if change == 'prose': current['sections'][0]['parts'][0]['body'] += ' 수정된 설명이에요.'
                elif change == 'old_cell':
                    current['sections'][0]['parts'][0]['body'] = current['sections'][0]['parts'][0]['body'].replace('기능0', '새로운 주장')
                    current['sections'][0]['body'] = current['sections'][0]['body'].replace('기능0', '새로운 주장')
                    current['concepts'][0]['entries'][0]['explanation'] = current['concepts'][0]['entries'][0]['explanation'].replace('기능0', '새로운 주장')
                elif change == 'card': current['concepts'][0]['entries'][0]['explanation'] += ' 별도 수정'
                elif change == 'section': current['sections'][0]['body'] += ' 별도 수정'
                elif change == 'evidence': current['sections'][0]['parts'][0]['evidence'][0]['bbox'] = [0, 0, .2, .2]
                else: current.pop('savedTableVersion')
                original = copy.deepcopy(current)
                value = self.restore(current)
                self.assertNotIn('| 기관 | 위치 |', value['sections'][0]['parts'][1]['body'])
                self.assertEqual(value['sections'], current['sections'])
                self.assertEqual(value['concepts'], current['concepts'])
                self.assertEqual(current, original)

    def test_unknown_reference_or_malformed_row_cannot_restore(self):
        for change in ['reference', 'rectangle', 'duplicate', 'title']:
            with self.subTest(change=change):
                value = copy.deepcopy(self.raw)
                if change == 'reference': value['tables'][0]['blockIds'] = ['outside']
                elif change == 'rectangle': value['tables'][0]['rows'][3] = ['one cell']
                elif change == 'duplicate': value['tables'][0]['rows'][3] = value['tables'][0]['rows'][2]
                else: value['tables'][0]['conceptTitle'] = '다른 기관'
                (self.cache/'response-job.json').write_text(json.dumps(value))
                self.assertNotIn('savedTableRestoration', self.restore())

    def test_document_or_output_mismatch_cannot_borrow_same_position_ids(self):
        for change in ['source', 'document', 'prose', 'evidence_geometry']:
            with self.subTest(change=change):
                current = copy.deepcopy(self.result)
                doc = copy.deepcopy(self.document)
                if change == 'source': current['sourceFingerprint'] = doc['fingerprint'] = 'source-v2'
                elif change == 'document': current['documentId'] = doc['documentId'] = 'different'
                elif change == 'evidence_geometry': current['sections'][0]['parts'][0]['evidence'][0]['bbox'] = [0, 0, .2, .2]
                else: current['sections'][0]['parts'][0]['body'] += ' 다른 내용이에요.'
                self.assertNotIn('savedTableRestoration', self.restore(current, doc))

    def test_job_geometry_must_match_saved_source_block(self):
        job = copy.deepcopy(self.job)
        job['blocks'][0]['bbox'] = [0, 0, .2, .2]
        (self.cache/'manifest.json').write_text(json.dumps({'jobs': [job]}))
        self.assertNotIn('savedTableRestoration', self.restore())

    def test_repeated_title_and_source_is_ambiguous(self):
        self.result['sections'][0]['parts'].append(copy.deepcopy(self.result['sections'][0]['parts'][0]))
        self.write()
        self.assertNotIn('savedTableRestoration', self.restore())

    def test_existing_table_stays_exactly_as_saved(self):
        table = '\n\n| 부위 | 기능 |\n| --- | --- |\n| 이미 | 있음 |'
        self.result['sections'][0]['parts'][0]['body'] += table
        self.result['sections'][0]['body'] += table
        self.result['concepts'][0]['entries'][0]['explanation'] += table
        self.write()
        value = self.restore()
        self.assertEqual(value['savedTableRestoration']['additionalApiRequests'], 0)
        for current, original in [
                (value['sections'][0]['parts'][0]['body'], self.result['sections'][0]['parts'][0]['body']),
                (value['concepts'][0]['entries'][0]['explanation'], self.result['concepts'][0]['entries'][0]['explanation'])]:
            self.assertTrue(current.startswith(original))
            self.assertEqual(current.count('| 이미 | 있음 |'), 1)
            self.assertIn('| 기관13 | 기능13 |', current)

    def test_second_distinct_table_restores_beside_a_healthy_first_without_duplicates(self):
        first = {'conceptTitle': '기관의 기능', 'headers': ['밝기', '세포'],
                 'rows': [['밝음', '원뿔'], ['어두움', '막대']], 'blockIds': ['figure']}
        self.raw['tables'] = [first, self.raw['tables'][0], copy.deepcopy(first)]
        markdown = '| 밝기 | 세포 |\n| --- | --- |\n| 밝음 | 원뿔 |\n| 어두움 | 막대 |'
        self.result['sections'][0]['parts'][0]['body'] += '\n\n'+markdown
        self.result['sections'][0]['body'] += '\n\n'+markdown
        self.result['concepts'][0]['entries'][0]['explanation'] += '\n\n'+markdown
        self.write();before = {p.name:p.read_bytes() for p in self.cache.iterdir()}
        original = copy.deepcopy(self.result)
        value = self.restore()
        self.assertEqual(len(value['savedTableRestoration']['tables']), 1)
        self.assertEqual(value['savedTableRestoration']['tables'][0]['rows'], 14)
        for text in (value['sections'][0]['body'], value['sections'][0]['parts'][0]['body'],
                     value['concepts'][0]['entries'][0]['explanation']):
            self.assertEqual(text.count(markdown), 1)
            self.assertEqual(text.count('| 기관13 | 기능13 |'), 1)
        self.assertEqual(self.restore(value), value)
        self.assertEqual(self.result, original)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.cache.iterdir()})

    def test_v2_partial_append_is_proved_before_restoring_a_second_table_same_concept(self):
        first = {'conceptTitle': '기관의 기능', 'headers': ['밝기', '세포'],
                 'rows': [['밝음', '원뿔'], ['어두움', '막대']], 'blockIds': ['figure']}
        self.raw['tables'].insert(0, first);self.write()
        markdown = '| 밝기 | 세포 |\n| --- | --- |\n| 밝음 | 원뿔 |\n| 어두움 | 막대 |'
        old = copy.deepcopy(self.result)
        old['savedTableVersion'] = 'saved-source-tables-v2'
        old['sections'][0]['parts'][0]['body'] += '\n\n'+markdown
        old['sections'][0]['body'] += '\n\n'+markdown
        old['concepts'][0]['entries'][0]['explanation'] += '\n\n'+markdown
        before = {p.name:p.read_bytes() for p in self.cache.iterdir()}
        original = copy.deepcopy(old)
        with patch.object(ai.Provider, 'complete', side_effect=AssertionError('no paid repair')) as paid:
            value = self.restore(old)
            paid.assert_not_called()
        self.assertEqual(value['savedTableVersion'], tables.VERSION)
        self.assertEqual(len(value['savedTableRestoration']['tables']), 1)
        for text in (value['sections'][0]['body'], value['sections'][0]['parts'][0]['body'],
                     value['concepts'][0]['entries'][0]['explanation']):
            self.assertEqual(text.count(markdown), 1)
            self.assertEqual(text.count('| 기관13 | 기능13 |'), 1)
        self.assertEqual(old, original)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.cache.iterdir()})
        # An earlier marker does not license edits to paid source tables/prose.
        changed = copy.deepcopy(old)
        changed['sections'][0]['parts'][0]['body'] += ' 다른 주장'
        self.assertNotIn('| 기관13 | 기능13 |', self.restore(changed)['sections'][0]['parts'][0]['body'])

    def test_previous_marker_with_multiple_verified_appends_is_not_duplicated(self):
        self.raw['tables'].append({'conceptTitle': '기관의 기능', 'headers': ['밝기', '세포'],
                                  'rows': [['밝음', '원뿔'], ['어두움', '막대']],
                                  'blockIds': ['figure']})
        self.write()
        repaired = self.restore()
        old = copy.deepcopy(repaired);old['savedTableVersion'] = 'saved-source-tables-v2'
        # Force an uncached provenance comparison against the historical result.
        tables._MEMO.clear()
        value = self.restore(old)
        self.assertEqual(value['savedTableVersion'], tables.VERSION)
        self.assertEqual(value['sections'], old['sections'])
        self.assertEqual(value['concepts'], old['concepts'])

    def test_traversal_job_id_is_not_used(self):
        self.job['id'] = '../job'
        self.write()
        self.assertNotIn('savedTableRestoration', self.restore())

    def test_memo_reuses_patches_without_rereading_or_retaining_full_prose(self):
        with patch.object(tables, '_read', wraps=tables._read) as read:
            first = self.restore()
            reads = read.call_count
            second = self.restore()
            self.assertGreater(reads, 0)
            self.assertEqual(read.call_count, reads)
        self.assertEqual(first, second)
        memo = next(iter(tables._MEMO.values()))
        self.assertNotIn('result', memo)
        self.assertEqual(len(memo['patches']), 1)
        second['sections'][0]['parts'][0]['body'] += ' 화면별 수정'
        self.assertEqual(self.restore(), first)

    def test_negative_memo_is_invalidated_when_existing_reply_changes(self):
        good = copy.deepcopy(self.raw)
        self.raw['tables'][0]['rows'][3] = ['invalid']
        self.write()
        with patch.object(tables, '_read', wraps=tables._read) as read:
            self.assertNotIn('savedTableRestoration', self.restore())
            reads = read.call_count
            self.assertNotIn('savedTableRestoration', self.restore())
            self.assertEqual(read.call_count, reads)
            (self.cache/'response-job.json').write_text(json.dumps(good))
            self.assertIn('savedTableRestoration', self.restore())
            self.assertGreater(read.call_count, reads)

    def test_changed_manifest_or_saved_result_cannot_reuse_old_positive_memo(self):
        self.assertIn('savedTableRestoration', self.restore())
        self.job['blocks'] = [{**self.block, 'bbox': [0, 0, .1, .1]}]
        self.write()
        self.assertNotIn('savedTableRestoration', self.restore())
        self.job['blocks'] = [self.block]
        self.write()
        self.assertIn('savedTableRestoration', self.restore())
        saved = copy.deepcopy(self.result)
        saved['sourceFingerprint'] = 'other-source'
        (self.cache/'result.json').write_text(json.dumps(saved))
        self.assertNotIn('savedTableRestoration', self.restore())

    def test_new_cache_candidate_invalidates_negative_memo(self):
        (self.cache/'response-job.json').unlink()
        self.assertNotIn('savedTableRestoration', self.restore())
        self.cache = self.cache.parent/'new-cache'
        self.cache.mkdir()
        self.write()
        self.assertIn('savedTableRestoration', self.restore())

    def test_memo_has_a_bounded_result_count(self):
        for index in range(tables.MEMO_LIMIT + 3):
            result = copy.deepcopy(self.result)
            result['sections'][0]['parts'][0]['body'] += str(index)
            self.restore(result)
        self.assertEqual(len(tables._MEMO), tables.MEMO_LIMIT)


if __name__ == '__main__':
    unittest.main()
