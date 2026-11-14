"""Whole-PDF summaries gain saved context; ordinary turns keep their original input/call count."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_ai as ai
from pdf_tutor_document_scope import (summary_request, full_review_request, load_guide,
                                      representative_sources, GUIDE_BYTES, SOURCE_BYTES)
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import semantic, chunk


class DocumentScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.doc = {'documentId': 'doc', 'fingerprint': 'v1', 'pages': [{} for _ in range(63)],
                    'chunks': [chunk(f'Original PDF page {n}: source facts about topic {n}.', n, f'p{n}')
                               for n in range(1, 64)]}
        self.study = {'kind': 'ai_generated', 'scope': 'document', 'strategy': 'newest-k1-2-3',
                      'documentId': 'doc', 'sourceFingerprint': 'v1',
                      'overview': {'body': '첫 단원에서 마지막 단원까지 연결하는 강의 전체 흐름이에요.'},
                      'sections': [{'title': f'단원 {i+1}', 'parts': [{'evidence': [{'page': 1+i*2}]}]}
                                   for i in range(28)],
                      'concepts': [{'name': f'개념 {i+1}', 'pages': [1+round(i*62/53)],
                                    'entries': [{'definition': f'개념 {i+1}의 정의예요.',
                                                 'evidence': [{'sourceId': f'v2p{i}', 'page': 1+round(i*62/53)}]}]}
                                   for i in range(54)]}
        self.save(self.study)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, value, strategy='newest-k1-2-3'):
        path = self.folder / 'generated' / strategy / 'latest-document-0.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def ask(self, question, *, memory=None, plan=None, **kwargs):
        provider = Provider([reply('전체 단원 구조와 원문에 따라 설명해요.')],
                            plan or {**semantic('문서 전체 내용'), 'scope': 'pdf'})
        result = ai.tutor(copy.deepcopy(self.doc), question, provider, folder=self.folder,
                          memory=memory, web_fallback=False, study_strategy='newest-k1-2-3', **kwargs)
        self.assertEqual(len(provider.calls), 1)
        return result, provider.calls[0][0]

    def test_scope_only_expands_whole_connected_document_tasks(self):
        for q in ['전체 내용을 3가지로 요약해줘봐.', '이 PDF 전체를 3가지로 요약해줘',
                  '이 자료의 핵심을 정리해줘', '이 PDF 안에서 가장 중요하다 생각하는 내용 3가지 알려줘']:
            with self.subTest(q=q):self.assertTrue(summary_request(q, {}))
        for q in ['DNA 복제의 전체 과정을 정리해줘', '이 PDF에서 DNA 복제의 전체 과정을 정리해줘',
                  '우리 대화 전체 요약', 'PDF로 지금까지 한 대화 전체를 정리해줘',
                  '사진 전체 내용을 정리해줘', '아까 첨부한 자료 전체 요약', '새로운 PDF 전체 요약']:
            with self.subTest(q=q):self.assertFalse(summary_request(q, {}))
        for option in [{'attachment': True}, {'selection': True}, {'explicit_page': 2}]:
            self.assertFalse(summary_request('전체 내용을 요약해줘', {}, **option))
        self.assertFalse(summary_request('전체 내용을 요약해줘', {'scope': 'external'}))
        self.assertFalse(summary_request('2페이지 전체 내용을 요약해줘', {}))

    def test_active_version_and_fingerprint_own_saved_guide(self):
        guide = load_guide(self.folder, self.doc, 'newest-k1-2-3')
        self.assertEqual(len(guide['concepts']), 54)
        self.assertEqual(len(guide['sections']), 28)
        self.assertEqual(guide['concepts'][-1]['name'], '개념 54')
        self.assertIsNone(load_guide(self.folder, self.doc, 'newest-k1-1-1'))
        self.assertIsNone(load_guide(self.folder, {**self.doc, 'fingerprint': 'changed'}, 'newest-k1-2-3'))
        self.assertIsNone(load_guide(self.folder, self.doc, '../newest-k1-2-3'))
        for field, value in [('documentId', 'other'), ('kind', 'partial'), ('scope', 'page'), ('sections', None)]:
            self.save({**self.study, field: value})
            self.assertIsNone(load_guide(self.folder, self.doc, 'newest-k1-2-3'))

    def test_all_topics_survive_budget_reduction_and_sources_stay_original(self):
        study = copy.deepcopy(self.study)
        for c in study['concepts']:c['entries'][0]['definition'] = '긴 정의를 연결해서 설명해요. '*200
        self.save(study)
        guide = load_guide(self.folder, self.doc, 'newest-k1-2-3')
        self.assertLessEqual(len(json.dumps(guide, ensure_ascii=False).encode()), GUIDE_BYTES)
        self.assertEqual(len(guide['conceptNames']), 54)
        self.assertEqual(guide['concepts'][-1]['name'], '개념 54')
        sources = representative_sources(ai.model_sources(self.doc['chunks'], self.doc), guide)
        self.assertEqual(len(sources), 12)
        self.assertEqual([sources[0]['page'], sources[-1]['page']], [1, 63])
        self.assertLessEqual(len(json.dumps(sources, ensure_ascii=False).encode()), SOURCE_BYTES)
        allowed = {c['id']: c['text'] for c in self.doc['chunks']}
        for source in sources:
            self.assertIn(source['sourceId'], allowed)
            self.assertIn(source['text'], allowed[source['sourceId']])
            self.assertFalse(source['sourceId'].startswith('v2'))

    def test_whole_request_gets_full_index_and_representative_evidence_without_an_extra_call(self):
        memory = {'documentId': 'doc', 'sourceTask': {'page': 16, 'item': '3', 'action': 'explain'},
                  'turns': [{'question': '삼염기 코돈을 설명해줘', 'answer': '이전 설명이에요.'}]}
        _, payload = self.ask('전체 내용을 3가지로 요약해줘봐.', memory=memory,
                              plan={**semantic('문서 전체 내용', page=16, followup=True, ask=True), 'scope': 'pdf'})
        self.assertEqual(payload['documentTarget']['kind'], 'currently_connected_pdf')
        self.assertEqual(len(payload['studyGuide']['concepts']), 54)
        self.assertEqual(len(payload['studyGuide']['sections']), 28)
        self.assertEqual(payload['pdfEvidence']['scope'], 'document_overview')
        self.assertFalse(payload['pdfEvidence']['entireDocumentReviewed'])
        self.assertTrue(payload['sources'])
        self.assertIsNone(payload['questionPlan']['page'])
        self.assertFalse(payload['questionPlan']['needsClarification'])
        self.assertNotIn('priorSource', payload)

    def test_oversized_topic_index_falls_back_instead_of_silently_losing_late_topics(self):
        study = copy.deepcopy(self.study)
        study['concepts'] = [{'name': f'개념 {i} ' + '긴 이름 '*30, 'entries': []} for i in range(600)]
        self.save(study)
        self.assertIsNone(load_guide(self.folder, self.doc, 'newest-k1-2-3'))
        _, payload = self.ask('전체 내용을 3가지로 요약해줘')
        self.assertEqual(payload['pdfEvidence']['scope'], 'entire_document')
        self.assertNotIn('studyGuide', payload)

    def test_ordinary_requests_have_identical_inputs_with_feature_disabled_or_enabled(self):
        for q in ['삼염기 코돈에서 정보용량이 무슨 뜻이야?', '그럼 두 개씩 읽으면 왜 부족한 거야?',
                  'DNA 복제와 전사를 비교해서 설명해줘.']:
            with self.subTest(q=q), patch('pdf_ai.whole_document_guide', side_effect=AssertionError('ordinary guide expansion')):
                with patch('pdf_ai.document_summary_request', return_value=False):
                    _, before = self.ask(q)
                _, after = self.ask(q)
                self.assertEqual(before, after)
                self.assertNotIn('documentTarget', after)

    def test_full_review_and_missing_saved_index_keep_complete_reading_path(self):
        question = '이 PDF 전체를 빠짐없이 읽고 요약해줘'
        self.assertTrue(full_review_request(question))
        _, payload = self.ask(question)
        self.assertEqual(payload['pdfEvidence']['scope'], 'entire_document')
        self.assertTrue(payload['pdfEvidence']['entireDocumentReviewed'])
        self.assertEqual(len({s['page'] for s in payload['sources']}), 63)
        self.save({**self.study, 'sourceFingerprint': 'old'})
        _, payload = self.ask('전체 내용을 3가지로 요약해줘')
        self.assertNotIn('studyGuide', payload)
        self.assertEqual(payload['pdfEvidence']['scope'], 'entire_document')

    def test_conversation_summary_never_runs_full_pdf_review(self):
        with patch('pdf_ai.exhaustive_tutor_sources', side_effect=AssertionError('unrequested PDF review')):
            _, payload = self.ask('이 PDF로 지금까지 한 대화 전체를 요약해줘')
        self.assertNotIn('documentTarget', payload)

    def test_desktop_adapter_passes_current_strategy_without_mutating_document(self):
        request = {'question': '전체 내용을 3가지로 요약해줘', 'strategy': 'newest-k1-2-3'}
        provider = Provider([reply('핵심을 세 가지로 정리해요.')], {**semantic('문서 전체 내용'), 'scope': 'pdf'})
        provider.ledger = {'requests': []}
        doc = copy.deepcopy(self.doc)
        result = ai.run_tutor_request(self.folder, doc, request, provider)
        self.assertEqual(doc, self.doc)
        self.assertIn('studyGuide', provider.calls[0][0])
        self.assertEqual(result['answer'], '핵심을 세 가지로 정리해요.')


if __name__ == '__main__':
    unittest.main()
