"""Audit regressions: metadata cost, hypothetical reasoning and grounded advice."""
import copy
import json
import unittest
from unittest.mock import patch

from pdf_ai import tutor, partial_json_answer, BudgetExceeded
from pdf_tutor_intent import page_count_question
from test_pdf_tutor_intent import Replay, document, semantic


class AnswerProvider(Replay):
    def __init__(self, plan, answer):
        super().__init__(plan)
        self.answer = answer

    def complete(self, payload, **kwargs):
        self.answers.append(copy.deepcopy(payload))
        return copy.deepcopy(self.answer)


def general(answer):
    return dict(answer=answer, responseKind='general', notFound=False,
                needsExternalSearch=False, evidence=[], visualPages=[])


class AuditRegressions(unittest.TestCase):
    def test_multipart_metadata_and_contents_use_local_citation_status_without_regeneration(self):
        class MissingCitationProvider(AnswerProvider):
            def complete(self,payload,**kwargs):
                self.answers.append(copy.deepcopy(payload))
                return {'answer':'총 17페이지이고 작품은 16쪽에서 설명해요.',
                    'responseKind':'document','notFound':False,'claimVerdict':'none',
                    'evidence':[],'visualPages':[]}
        provider=MissingCitationProvider(semantic('삶의 기쁨 작품과 문서 분량',page=16),{})
        result=tutor(document(),'이 PDF는 몇 페이지고 16쪽 작품은 어떻게 설명해?',provider)
        self.assertEqual(result['kind'],'ai_generated')
        self.assertEqual(provider.answers[0]['documentPageCount'],17)
        self.assertEqual(result['evidence'],[])
        self.assertTrue(result['evidenceIncomplete'])
        self.assertEqual(len(provider.answers),1)
        self.assertFalse(provider.searches)

    def test_factual_answer_streams_prose_and_keeps_final_evidence(self):
        class StreamProvider(AnswerProvider):
            def complete(self, payload, **kwargs):
                self.stream_callback = kwargs.get('on_delta')
                if self.stream_callback:
                    self.stream_callback('자료는 색채와')
                    self.stream_callback('자료는 색채와 형태의 혁신을 설명해요.')
                return super().complete(payload, **kwargs)
        provider = StreamProvider(semantic('삶의 기쁨', page=16), {
            'answer': '자료는 색채와 형태의 혁신을 설명해요.', 'responseKind': 'document',
            'notFound': False, 'evidence': [{'sourceId': 'matisse', 'quote': '색채와 형태의 혁신'}]})
        streamed = []
        result = tutor(document(), '16쪽 설명이 맞는지 확인해줘', provider, progress=streamed.append)
        self.assertTrue(callable(provider.stream_callback))
        self.assertEqual(result['kind'], 'ai_generated')
        self.assertEqual(streamed[0], '자료는 색채와')
        self.assertEqual(streamed[-1], result['answer'])
        self.assertEqual(result['evidence'][0]['page'], 16)
        self.assertEqual(result['memory']['turns'][-1]['answer'], result['answer'])

    def test_factual_verdict_and_evidence_are_part_of_the_first_answer(self):
        class VerdictProvider(AnswerProvider):
            def complete(self,payload,**kwargs):
                self.answers.append(copy.deepcopy(payload))
                return {'answer':'아니요. 자료는 색채와 형태의 혁신을 설명해요.',
                    'claimVerdict':'rejected','responseKind':'document','notFound':False,
                    'needsExternalSearch':False,'evidence':[
                        {'sourceId':'matisse','quote':'색채와 형태의 혁신'}]}
        provider=VerdictProvider(semantic('삶의 기쁨',page=16),{})
        result=tutor(document(),'16페이지 작품은 모든 색채가 단조롭다는 뜻이지?',provider)
        self.assertTrue(result['answer'].startswith('아니요'))
        self.assertEqual(len(provider.answers),1)
        self.assertEqual(result['evidence'][0]['page'],16)
        self.assertFalse(provider.searches)

    def test_missing_citations_cannot_turn_a_completed_answer_into_a_review_budget_failure(self):
        class LimitedProvider(AnswerProvider):
            def complete(self,payload,**kwargs):
                if self.answers:raise BudgetExceeded('A second answer must not be attempted')
                self.answers.append(copy.deepcopy(payload))
                return {'answer':'찾은 근거만으로 그 부분을 단정하기는 어려워요.',
                    'claimVerdict':'none','responseKind':'document','evidence':[]}
        provider=LimitedProvider(semantic('작품',page=16),{})
        shown=[]
        result=tutor(document(),'16페이지 작품은 모든 색채가 단조롭다는 뜻이지?',provider,progress=shown.append)
        self.assertEqual(len(provider.answers),1)
        self.assertTrue(result['evidenceIncomplete'])
        self.assertEqual(result['answer'],'찾은 근거만으로 그 부분을 단정하기는 어려워요.')
        self.assertNotIn('',shown)

    def test_stream_can_read_answer_after_claim_verdict(self):
        self.assertEqual(partial_json_answer(
            '{"claimVerdict":"rejected","answer":"아니요. 우선순위가 반대예요.'),
            '아니요. 우선순위가 반대예요.')

    def test_pure_metadata_is_local_and_preserves_learning_focus(self):
        memory = {'documentId': 'doc', 'topicQuestion': '삶의 기쁨',
                  'focus': {'subject': '삶의 기쁨', 'page': 16, 'viewerPage': 16},
                  'sourceIds': ['matisse'],
                  'turns': [{'question': '작품 설명해줘', 'answer': '색채의 혁신이에요.'}]}
        for q in ('이 PDF는 총 몇 페이지야?', '이 PDF 전체는 몇 페이지야?',
                  '열려 있는 문서의 쪽수를 알려줘', '전체 쪽수가 얼마인지 알려줘',
                  'How many pages does this PDF have?', 'What is the page count?'):
            with self.subTest(q=q):
                provider = Replay()
                with patch('pdf_ai.exhaustive_tutor_sources', side_effect=AssertionError('costly review')):
                    result = tutor(document(), q, provider, memory=memory)
                self.assertEqual(result['answer'], '이 PDF는 총 17페이지예요.')
                self.assertEqual(result['documentMetadata'], {'pageCount': 17})
                self.assertEqual(result['memory']['focus'], memory['focus'])
                self.assertEqual(result['memory']['sourceIds'], ['matisse'])
                self.assertFalse(provider.plans or provider.answers or provider.searches)

    def test_metadata_never_discards_a_content_question_or_an_attachment(self):
        for q in ('다다이즘은 몇 페이지에 있어?', '3쪽의 내용이 뭐야?',
                  'PDF는 몇 페이지고 핵심 내용은 뭐야?',
                  'Explain how many pages discuss stocks', '목차에 적힌 쪽수와 달라?'):
            self.assertFalse(page_count_question(q), q)
        provider = Replay(semantic('첨부 자료'))
        tutor(document(), '이 PDF는 총 몇 페이지야?', provider,
              attachment={'name': 'note', 'kind': 'image', 'images': []})
        self.assertEqual(len(provider.answers), 1)

    def test_semantic_count_fallback_needs_only_the_existing_small_plan(self):
        provider = Replay(semantic('문서 분량', intent='page_count'))
        result = tutor(document(), '지금 펼친 파일 끝까지 장수가 어떻게 되지?', provider)
        self.assertEqual(result['documentMetadata']['pageCount'], 17)
        self.assertEqual(len(provider.plans), 1)
        self.assertFalse(provider.answers or provider.searches)

    def test_empty_metadata_is_not_reported_as_a_zero_page_pdf(self):
        result = tutor({'documentId': 'doc', 'pages': [], 'chunks': []}, 'PDF는 몇 페이지야?')
        self.assertEqual(result['kind'], 'no_evidence')
        self.assertNotIn('0페이지', result['answer'])

    def test_invented_scenarios_do_not_get_a_false_missing_topic_notice(self):
        for q in ('이 PDF에는 없는 동아리 회장 사례로 설명해줘. 실제 사건 말고 네가 만든 예시로.',
                  '비슷한 원리로, 이 PDF에는 없는 가상의 작품을 하나만 예로 들어줘.',
                  '등장인물을 바꿔서 그 원리를 보여주는 짧은 상황극을 써줄래?'):
            provider = AnswerProvider(semantic('원리', intent='illustrate'),
                                      general('가상의 사례예요. 대표가 공동 자금을 자기 편의에 쓰는 상황을 생각해 봐요.'))
            result = tutor(document(), q, provider)
            self.assertEqual(result['answer'], provider.answer['answer'])
            self.assertEqual((len(provider.answers), len(provider.searches)), (1, 0))

    def test_learning_relevance_can_use_general_educational_reasoning(self):
        provider = AnswerProvider(semantic('야수파', intent='learning_relevance'),
                                  general('이름만 외우기보다 색채와 표현의 원리를 알면 새로운 작품도 비교할 수 있어요.'))
        result = tutor(document(), '이 자료 공부할 때 야수파를 이해해야 해?', provider)
        self.assertEqual(result['kind'], 'ai_generated')
        self.assertEqual(result['answer'], provider.answer['answer'])
        self.assertFalse(provider.searches)

    def test_reasoning_text_is_preserved_without_inventing_citation_links(self):
        for intent, answer in [('learning_relevance', '자료도 레디메이드를 사물의 발견과 선택으로 설명해요.'),
                               ('illustrate', 'PDF 16페이지에 동아리 회장 사례가 있어요.')]:
            provider = AnswerProvider(semantic('작품', intent=intent), general(answer))
            result = tutor(document(), '이 자료를 공부할 이유를 예로 설명해줘', provider)
            self.assertEqual(result['kind'], 'ai_generated')
            self.assertEqual(result['answer'], answer)
            self.assertEqual(result['evidence'], [])
        # A request to locate actual contents still needs document evidence.
        provider = AnswerProvider(semantic('삶의 기쁨'), general('밝은 색채를 강조한 작품이에요.'))
        result = tutor(document(), '이 PDF 16쪽에서 뭐라고 설명해?', provider)
        self.assertEqual(result['kind'], 'ai_generated')
        self.assertEqual(result['evidence'], [])


if __name__ == '__main__':
    unittest.main()
