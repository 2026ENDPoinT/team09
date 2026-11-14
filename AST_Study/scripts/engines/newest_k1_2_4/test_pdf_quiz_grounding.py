"""Offline regressions for the real lost visual-reference/rewritten-rule defect."""
import copy
import unittest

import pdf_quiz as quiz
from pdf_quiz_grounding import recover_transcriptions, transcription_index
from pdf_quiz_sources import wire_generation_payload
from test_pdf_quiz import fixture, planned


def visual_fixture():
    document, request = fixture(1, ['mcq'], 1)
    box = [.1, .1, .9, .3]
    element = {'elementId': 'cached-element', 'title': '강세 표시 유지',
               'status': 'complete', 'kind': 'text', 'bbox': box, 'uncertainDetails': []}
    document['pages'][0]['pageAnalysis'] = {
        'status': 'ready', 'documentId': 'doc', 'page': 1, 'elements': [element]}
    document['chunks'].append({'id': 'cached-element-transcription-0', 'elementId': 'cached-element',
        'documentId': 'doc', 'source': 'ai_transcription', 'page': 1, 'bbox': box,
        'elementTitle': element['title'],
        'text': '마지막 음절에 강모음 + í, ú가 있으면 복수형에도 강세표시 유지\nbaúl → baúles, país → países'})
    card = request['studyContent']['concepts'][0]
    card['name'] = 'í, ú로 끝나는 명사'
    card['entries'][0].update(definition='í 또는 ú로 끝나는 명사는 -es를 붙인다.',
        explanation='예를 들어 baúl과 país이다.', evidence=[
            {'sourceId': 'v2p1f0', 'documentId': 'doc', 'source': 'region_image',
             'page': 1, 'bbox': [.11, .11, .89, .29]}])
    return document, request


class QuizGroundingTests(unittest.TestCase):
    def test_rewritten_rule_is_replaced_in_planner_and_generation_not_saved_data(self):
        document, request = visual_fixture()
        before = copy.deepcopy((document, request))
        config, outline, catalog, concepts, sources = quiz.context(document, request)
        self.assertEqual((document, request), before)
        self.assertEqual(concepts['c1']['title'], '강세 표시 유지')
        self.assertEqual(catalog[0]['title'], '강세 표시 유지')
        self.assertEqual(outline[0]['concepts'][0]['title'], '강세 표시 유지')
        self.assertNotIn('study:c1:e1', sources)
        plan = planned({'ox': 0, 'mcq': 1, 'word': 0, 'essay': 0}, ['c1'])
        wire, _ = wire_generation_payload(quiz.generation_payload(
            config, outline, plan, plan['allocations'][0], concepts, sources, [], 'offline'))
        self.assertEqual(''.join(q['text'] for q in wire['sources'][0]['quotes']),
                         document['chunks'][-1]['text'])
        self.assertEqual(wire['sources'][0]['sourceKind'], 'ai_transcription')

    def test_missing_or_uncertain_analysis_keeps_saved_explanation_without_inventing_source(self):
        for mutate in (lambda a: a.update(status='pending'),
                       lambda a: a.update(documentId='another-doc'),
                       lambda a: a.update(page=2),
                       lambda a: a['elements'][0].update(status='partial'),
                       lambda a: a['elements'][0].update(uncertainDetails=['읽을 수 없음'])):
            document, request = visual_fixture()
            mutate(document['pages'][0]['pageAnalysis'])
            *_, concepts, sources = quiz.context(document, request)
            self.assertEqual(concepts['c1']['sourceIds'], ['study:c1:e1'])
            self.assertEqual(sources['study:c1:e1']['sourceKind'], 'saved_concept')

    def test_partial_coverage_does_not_discard_unmatched_material(self):
        document, request = visual_fixture()
        request['studyContent']['concepts'][0]['entries'][0]['evidence'].append({
            'sourceId': 'missing', 'source': 'region_image', 'page': 1, 'bbox': [.1,.7,.9,.9]})
        *_, concepts, sources = quiz.context(document, request)
        self.assertEqual(len(concepts['c1']['sourceIds']), 2)
        self.assertIn('study:c1:e1', sources)
        self.assertEqual(concepts['c1']['title'], 'í, ú로 끝나는 명사')

    def test_geometry_does_not_attach_other_topics_or_whole_pages(self):
        for box in ([.1,.7,.9,.9], [0,0,1,1], [0,0,0,1], [0,0,float('nan'),1], None):
            with self.subTest(box=box):
                document, request = visual_fixture()
                ref = request['studyContent']['concepts'][0]['entries'][0]['evidence'][0]
                ref['bbox'] = box
                self.assertEqual(recover_transcriptions([ref], transcription_index(document),1,1,'doc'), ([],False))

    def test_exact_reference_still_requires_same_document_and_selected_page(self):
        document, _ = visual_fixture()
        index = transcription_index(document)
        ref = {'sourceId':'cached-element', 'page':1}
        self.assertTrue(recover_transcriptions([ref],index,1,1,'doc')[1])
        self.assertEqual(recover_transcriptions([ref],index,2,2,'doc'), ([],False))
        ref['documentId'] = 'other'
        self.assertEqual(recover_transcriptions([ref],index,1,1,'doc'), ([],False))

    def test_observation_and_ocr_are_not_promoted_to_primary_transcription(self):
        for kind in ('ai_visual_observation','ocr','native'):
            document, _ = visual_fixture()
            document['chunks'][-1]['source'] = kind
            self.assertEqual(transcription_index(document), {})


if __name__ == '__main__':
    unittest.main()
