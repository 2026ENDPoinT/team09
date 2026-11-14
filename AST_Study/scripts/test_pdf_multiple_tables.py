"""Every source-owned comparison survives, including visual-owned table arrays."""
import copy
import unittest

import pdf_new_concept_ver99_study as study
from pdf_study_cache_reuse import constrained_format
from pdf_visual_teaching import decode, encode_format


class MultipleTableTests(unittest.TestCase):
    def fixture(self):
        owner = 'v2p2f0'
        job = {'id': 'table-fixture', 'title': '기관 기능', 'blocks': [
            {'id': owner, 'page': 2, 'kind': 'visual', 'text': '밝음과 어두움',
             'hasVisual': True, 'bbox': [.1, .1, .9, .9]}]}
        concept = {'title': '기관 기능',
                   'sourceSetup': {'observedRelations': [], 'boundaryChecks': [], 'interpretation': ''},
                   'segments': [
                       {'kind': 'definition', 'text': '기관들은 여러 기능을 나누어 맡아요.', 'blockIds': [owner]},
                       {'kind': 'explanation', 'text': '세포는 밝기에 따라 형태와 색 또는 명암을 구별해요.', 'blockIds': [owner]},
                       {'kind': 'easyExplanation', 'text': '표에서 부위와 그 기능을 한 쌍으로 읽어요.', 'blockIds': [owner]}],
                   'standardKnowledgeUsed': False}
        tables = [
            {'conceptTitle': '기관 기능', 'headers': ['밝기', '세포'],
             'rows': [['밝음', '원뿔'], ['어두움', '막대']], 'blockIds': [owner]},
            {'conceptTitle': '기관 기능', 'headers': ['부위', '기능'],
             'rows': [[f'기관{i}', f'기능{i}'] for i in range(14)], 'blockIds': [owner]},
            {'conceptTitle': '기관 기능', 'headers': ['부위', '기능'],
             'rows': [['다른기관A', '다른기능A'], ['다른기관B', '다른기능B']], 'blockIds': [owner]}]
        raw = {'concepts': [concept], 'tables': tables, 'sequences': [],
               'excludedBlocks': [], 'uncertainBlocks': []}
        doc = {'documentId': 'fixture', 'pages': [{'label': '1'}, {'label': '2'}]}
        return job, raw, doc

    def assert_all_tables(self, unit):
        for text in (unit['summary']['parts'][0]['body'], unit['concepts'][0]['explanation']):
            self.assertEqual(text.count('| 밝기 | 세포 |'), 1)
            self.assertEqual(text.count('| 기관13 | 기능13 |'), 1)
            self.assertEqual(text.count('| 다른기관B | 다른기능B |'), 1)
            self.assertEqual(text.count('| 부위 | 기능 |'), 2)

    def test_three_tables_same_concept_and_repeated_table_all_keep_correct_source_binding(self):
        job, raw, doc = self.fixture();raw['tables'].append(copy.deepcopy(raw['tables'][0]))
        before = copy.deepcopy((job, raw, doc))
        unit = study.validate(raw, job, doc)
        self.assert_all_tables(unit)
        self.assertEqual(unit['concepts'][0]['evidence'][0]['sourceId'], 'v2p2f0')
        self.assertEqual((job, raw, doc), before)
        # Presentation repair/replay is idempotent even when called again.
        from pdf_new_concept_ver99_checks import prepare_response
        prepared = prepare_response(raw)
        parts, cards = unit['summary']['parts'], unit['concepts']
        before_display = copy.deepcopy((parts, cards))
        study.attach_comparison_tables(prepared['tables'], prepared['concepts'], parts, cards,
                                       {b['id']:b for b in job['blocks']})
        self.assertEqual((parts, cards), before_display)

    def test_visual_owned_multiple_tables_flatten_then_render_all_rows_without_fabricated_owner(self):
        job, raw, doc = self.fixture()
        _, ownership = encode_format(constrained_format(study.STUDY_FORMAT, job), job)
        concept = copy.deepcopy(raw['concepts'][0])
        concept['tables'] = [{k:copy.deepcopy(v) for k,v in t.items() if k!='conceptTitle'}
                             for t in raw['tables']]
        concept['sequences'] = []
        wire = {name: [] for name in ('concepts','tables','sequences','excludedBlocks','uncertainBlocks')}
        wire['visualTeaching'] = {'v2p2f0': {'concepts':[concept], 'excludedBlocks':[], 'uncertainBlocks':[]}}
        before = copy.deepcopy(wire)
        canonical = decode(wire, ownership)
        self.assertEqual([t['conceptTitle'] for t in canonical['tables']], ['기관 기능']*3)
        self.assert_all_tables(study.validate(canonical, job, doc))
        self.assertEqual(wire, before)

    def test_invalid_or_unbound_table_does_not_block_later_valid_tables(self):
        job, raw, doc = self.fixture()
        invalid = copy.deepcopy(raw['tables'][0]);invalid['blockIds'] = ['outside']
        malformed = copy.deepcopy(raw['tables'][0]);malformed['rows'][0] = ['non-rectangular']
        raw['tables'] = [invalid, malformed]+raw['tables']
        self.assert_all_tables(study.validate(raw, job, doc))


if __name__ == '__main__':
    unittest.main()
