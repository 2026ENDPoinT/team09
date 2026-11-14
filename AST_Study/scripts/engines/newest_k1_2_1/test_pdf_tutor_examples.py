"""Offline regressions for streamed invented examples being replaced by web fallback."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from pdf_ai import Provider, tutor, tutor_new_example_intent


QUESTION = '금융시장의 기능을 이 pdf에 없는 예시로 해서 예시로 섦여해줘.'
ANSWER = ('예를 들어, 작은 빵집을 운영하는 지민은 오븐을 새로 사면 매년 500만 원의 추가 수익을 '
          '낼 수 있지만, 지금은 오븐을 살 돈이 부족해요. 반면 민수는 당장 쓸 계획이 없는 저축금 '
          '1,000만 원을 가지고 있어요. 금융시장이 두 사람을 연결해 민수가 돈을 빌려주고 '
          '지민이 이자를 지급하면, 민수는 저축으로 이자 수익을 얻고 지민은 오븐으로 더 많은 '
          '빵을 팔 수 있어요.')


class ReplayProvider:
    model = 'test-only'
    def __init__(self, **overrides):
        self.value = {'answer':ANSWER, 'responseKind':'general', 'notFound':False,
                      'needsExternalSearch':False, 'webSearchTopic':'', 'evidence':[], 'visualPages':[]}
        self.value.update(overrides)
        self.calls = []; self.searches = []

    def complete(self, payload, max_output=2400, on_delta=None, **kwargs):
        self.calls.append(payload)
        if on_delta:
            on_delta(self.value['answer'][:40])
            on_delta(self.value['answer'])
        return copy.deepcopy(self.value)

    def web_search(self, question, topic_hint=''):
        self.searches.append(question)
        return {'answer':'확인한 실제 사례예요. [1]', 'webSources':[
            {'number':1, 'title':'Source', 'url':'https://example.org/source'}]}


def document():
    text='금융시장은 저축자의 자금을 차입자의 생산적 투자로 연결해요.'
    return {'documentId':'doc', 'pages':[{}], 'chunks':[{
        'id':'c1','documentId':'doc','page':1,'source':'native','field':'markdown',
        'start':0,'end':len(text),'text':text,'bbox':None}]}


class TutorExampleTests(unittest.TestCase):
    def test_tutor_request_survives_analysis_cancel_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/'cancel').write_text('cancel',encoding='utf-8')
            response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'answer':'설명해요.'})}}],
                      'usage':{'prompt_tokens':20,'completion_tokens':5}}
            provider=Provider(folder,True,.1,transport=lambda body:response)
            self.assertEqual(provider.complete({'taskType':'tutor','question':'설명해줘'},max_output=100)['answer'],'설명해요.')
            with self.assertRaises(InterruptedError):
                provider.complete({'task':'semantic_study'},max_output=100)

    def test_streamed_example_is_exactly_the_final_answer_and_memory(self):
        provider=ReplayProvider();stream=[]
        result=tutor(document(),QUESTION,provider,progress=stream.append,mode='deep')
        self.assertEqual(result['kind'],'ai_generated')
        self.assertEqual(result['answer'],ANSWER)
        self.assertEqual(stream[-1],result['answer'])
        self.assertEqual(result['memory']['turns'][-1]['answer'],ANSWER)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(provider.searches,[])
        self.assertEqual(result['evidence'],[])
        self.assertNotIn('webSources',result)

    def test_new_example_phrasings_do_not_trigger_pdf_missing_search(self):
        for question in [QUESTION, '이 PDF에 없는 비유로 설명해줘',
                         '자료에 안 나오는 새로운 예제로 알려줘',
                         'PDF 예시 말고 다른 상황으로 설명해줘',
                         '이 강의의 개념을 가상의 사례로 설명해줘',
                         'Explain using an example not in the PDF.']:
            with self.subTest(question=question):
                provider=ReplayProvider()
                result=tutor(document(),question,provider)
                self.assertEqual(result['answer'],ANSWER)
                self.assertFalse(provider.searches)

    def test_explicit_search_still_searches(self):
        provider=ReplayProvider()
        result=tutor(document(),QUESTION+' 외부 검색해줘.',provider)
        self.assertEqual(result['kind'],'web_generated')
        self.assertEqual(len(provider.searches),1)
        self.assertFalse(provider.calls)

    def test_invented_example_does_not_search_just_because_model_requests_it(self):
        provider=ReplayProvider(needsExternalSearch=True,webSearchTopic='금융시장 사례')
        result=tutor(document(),QUESTION,provider)
        self.assertEqual(result['kind'],'ai_generated')
        self.assertEqual(len(provider.searches),0)

    def test_actual_missing_topic_and_real_world_cases_are_not_invented_examples(self):
        for question in ['이 PDF에는 없는 부분적분법을 공부하고 싶어. 개념을 설명해줘',
                         '이 PDF에 없는 실제 사례를 찾아줘',
                         '이 자료에 없는 사례로 실제로 있었는지 확인해줘',
                         '이 PDF에 그 예시가 있는지 확인해줘']:
            with self.subTest(question=question):
                self.assertFalse(tutor_new_example_intent(question))
        provider=ReplayProvider()
        result=tutor(document(),'이 PDF에는 없는 부분적분법의 개념을 설명해줘',provider)
        self.assertEqual(result['kind'],'ai_generated')
        self.assertFalse(provider.searches)

    def test_example_with_search_disallowed_keeps_answer_without_missing_pdf_notice(self):
        provider=ReplayProvider()
        result=tutor(document(),QUESTION+' 검색하지 마.',provider)
        self.assertEqual(result['answer'],ANSWER)
        self.assertFalse(provider.calls[0]['externalSearchAvailable'])
        self.assertFalse(provider.searches)

    def test_unverified_document_claims_do_not_bypass_evidence_validation(self):
        provider=ReplayProvider(answer='PDF 1페이지에 빵집 사례가 있어요.',responseKind='document',
                                evidence=[{'sourceId':'fake','quote':'빵집'}])
        result=tutor(document(),QUESTION,provider)
        self.assertEqual(result['kind'],'ai_generated')
        self.assertEqual(result['evidence'],[])
        self.assertTrue(result['evidenceIncomplete'])
        self.assertEqual(len(provider.calls),1)

    def test_blocked_response_is_not_preserved_as_an_illustration(self):
        result=tutor(document(),QUESTION,ReplayProvider(blocked=True))
        self.assertEqual(result['kind'],'blocked')


if __name__=='__main__':
    unittest.main()
