"""Conversation beats viewer state; free prose in both modes. No network calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pdf_ai import Provider as ApiProvider, tutor
from pdf_tutor_delivery import COMMON_SYSTEM, learning_task
from pdf_tutor_intent import MENTOR_PLAN_SYSTEM
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import chunk, semantic


def document():
    return {'documentId':'doc','pages':[{} for _ in range(10)],'chunks':[
        chunk('무조건항복은 항복 조건의 협상 없이 항복하는 방식이며 점령 개혁과는 구별한다.',6,'surrender'),
        chunk('스탈린은 군사적 점령과 사회체제 강요의 관계를 설명했다.',8,'stalin')]}


def memory():
    return {'documentId':'doc','topicQuestion':'무조건항복','sourceIds':['surrender'],
        'focus':{'subject':'무조건항복','viewerPage':6},
        'turns':[{'question':'무조건항복 뜻을 예를 들어 설명해줘.','answer':'항복하는 쪽이 조건을 내걸지 않는다는 뜻이에요.','subject':'무조건항복'}]}


class Recording(Provider):
    def __init__(self, plan=None):
        super().__init__([reply('앞서 물은 무조건항복의 의미를 이어서 설명해요.')],
            plan or {**semantic('무조건항복',query='무조건항복 조건',followup=True),'scope':'general'})
        self.plans=[]
    def plan_tutor(self, payload):
        self.plans.append(copy.deepcopy(payload));return copy.deepcopy(self.plan)


class ConversationFirstTests(unittest.TestCase):
    def test_scroll_does_not_change_the_same_followup_in_either_mode(self):
        for mode in ('quick','deep'):
            payloads=[]
            for page in (None,1,6,8,10):
                provider=Recording()
                result=tutor(document(),'다시 설명해줘.',provider,memory=memory(),current_page=page,mode=mode,web_fallback=False)
                payload=provider.calls[0][0];payloads.append(payload)
                self.assertNotIn('currentPdfPage',payload)
                self.assertNotIn('requestedPdfPage',payload)
                self.assertNotIn('currentPage',provider.plans[0])
                self.assertNotIn('viewerPage',provider.plans[0]['focus'])
                self.assertEqual(payload['questionPlan']['subject'],'무조건항복')
                self.assertFalse(result['contextDiagnostics']['pageRetargeted'])
                self.assertTrue(result['contextDiagnostics']['viewerPageIgnored'])
                self.assertEqual(payload['learningTask']['responseContract'],'direct')
                self.assertNotIn('response_format',provider.calls[0][1])
            for payload in payloads[1:]:self.assertEqual(payload,payloads[0])

    def test_explicit_user_page_still_works_without_the_viewer(self):
        provider=Recording({**semantic('8페이지 설명',page=8),'scope':'pdf'})
        tutor(document(),'8페이지 내용을 설명해줘.',provider,memory=memory(),current_page=2,mode='deep')
        payload=provider.calls[0][0]
        self.assertEqual(payload['requestedPdfPage'],8)
        self.assertEqual(payload['sources'][0]['sourceId'],'stalin')
        self.assertNotIn('currentPdfPage',payload)

    def test_final_subject_repairs_a_wrong_search_hint_in_memory(self):
        provider=Recording({**semantic('8쪽 스탈린',query='스탈린 점령',page=8,followup=True),'scope':'general'})
        provider.values=[reply('물어본 것은 무조건항복의 뜻이에요.',resolvedTopic='무조건항복')]
        result=tutor(document(),'아까 내가 물어본 뜻을 다시 설명해줘.',provider,memory=memory(),current_page=8,mode='deep')
        self.assertEqual(result['memory']['focus']['subject'],'무조건항복')
        self.assertEqual(result['memory']['turns'][-1]['subject'],'무조건항복')
        self.assertIsNone(result['memory']['focus']['page'])
        self.assertEqual(result['contextDiagnostics']['resolvedSubject'],'무조건항복')
        self.assertEqual(result['contextDiagnostics']['retrievalSubject'],'8쪽 스탈린')

    def test_literal_named_term_survives_a_wrong_planner_paraphrase(self):
        doc={'documentId':'doc','pages':[{} for _ in range(10)],'chunks':[
            chunk('스탈린은 점령한 지역에 자기 사회 체제를 강요한다고 주장했다.',8,'stalin'),
            chunk('군사정부 Military Government는 점령군이 행정권을 행사하는 통치기구이다.',9,'military')]}
        provider=Recording({**semantic('스탈린 주장',query='스탈린 점령 사회 체제',followup=True),'scope':'general'})
        provider.values=[reply('군사정부는 군 당국이 통치하는 기구예요.',resolvedTopic='군사정부')]
        tutor(doc,'군사정부는 군대가 점령지를 통치하는 거야?',provider,current_page=8,web_fallback=False)
        supplied={s['sourceId'] for s in provider.calls[0][0]['sources']}
        self.assertIn('military',supplied)

    def test_modes_do_not_force_examples_a_schema_or_a_canned_verdict(self):
        for plan in ({},{'followup':True,'needsExample':True},{'needsExample':False}):
            self.assertEqual(learning_task('그 이유를 다시 설명해줘.','deep',plan)['responseContract'],'direct')
            self.assertEqual(learning_task('그 이유를 다시 설명해줘.','deep',plan)['caseRequirements'],'')
        self.assertNotIn("begins with '맞아요'",COMMON_SYSTEM)
        self.assertIn('no required opening phrase',COMMON_SYSTEM)
        self.assertIn('scrolling are deliberately NOT supplied',MENTOR_PLAN_SYSTEM)

    def test_actual_api_wire_keeps_turn_roles_and_puts_question_after_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            calls=[]
            def transport(body):
                calls.append(copy.deepcopy(body))
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(reply('조건의 주체를 이어서 설명해요.'))}}],
                    'usage':{'prompt_tokens':20,'completion_tokens':10}}
            provider=ApiProvider(Path(temp),True,.01,transport=transport)
            payload={'taskType':'tutor','learningTask':learning_task('그건 누가 정해?','deep',{}),
                'question':'그건 누가 정해?','recentConversation':[{'question':'무조건항복은 뭐야?','answer':'항복에 조건을 붙이지 않는다는 뜻이에요.'}],
                'questionPlan':{'subject':'스탈린','resolvedRequest':'스탈린의 주장을 설명'},'topicHint':'스탈린',
                'sources':[{'text':'다른 페이지의 스탈린 인용문'}]}
            provider.complete(payload,max_output=100)
            messages=calls[0]['messages']
            self.assertEqual([m['role'] for m in messages],['system','user','assistant','user','user'])
            self.assertEqual(messages[1]['content'],'무조건항복은 뭐야?')
            self.assertIn('조건을 붙이지',messages[2]['content'])
            self.assertEqual(messages[-1]['content'],'그건 누가 정해?')
            current=json.loads(messages[-2]['content'].split('\n',1)[1])
            self.assertNotIn('recentConversation',current)
            self.assertNotIn('question',current)
            self.assertEqual(current['sources'],payload['sources'])
            self.assertNotIn('questionPlan',current)
            self.assertNotIn('topicHint',current)
            self.assertNotIn('subject',current['learningTask'])
            self.assertEqual(payload['questionPlan']['subject'],'스탈린')
            self.assertIn('subject',payload['learningTask'])  # Diagnostic input stays intact.

    def test_current_attachment_stays_with_plain_learner_question(self):
        with tempfile.TemporaryDirectory() as temp:
            calls=[]
            def transport(body):
                calls.append(copy.deepcopy(body))
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(reply('첨부한 문제를 설명해요.'))}}],
                    'usage':{'prompt_tokens':20,'completion_tokens':10}}
            provider=ApiProvider(Path(temp),True,.01,transport=transport)
            provider.complete({'taskType':'tutor','question':'첨부 문제를 설명해줘.','sources':[{'text':'참고 원문'}]},
                max_output=100,image={'width':1,'height':1,'data':'data:image/png;base64,AA=='})
            messages=calls[0]['messages']
            self.assertEqual(messages[-1]['content'][0],{'type':'text','text':'첨부 문제를 설명해줘.'})
            self.assertEqual(messages[-1]['content'][1]['type'],'image_url')
            context=json.loads(messages[-2]['content'].split('\n',1)[1])
            self.assertEqual(context['sources'],[{'text':'참고 원문'}])

    def test_separated_sources_still_count_toward_input_budget(self):
        from pdf_ai import ContextBudgetExceeded
        with tempfile.TemporaryDirectory() as temp:
            calls=[]
            def transport(body):
                calls.append(body)
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(reply('현재 질문에 답해요.'))}}],
                    'usage':{'prompt_tokens':20,'completion_tokens':10}}
            provider=ApiProvider(Path(temp),True,.01,transport=transport,input_bound_limit=22000)
            provider.complete({'taskType':'tutor','question':'개념을 설명해줘.','sources':[]},max_output=100)
            with self.assertRaises(ContextBudgetExceeded):
                provider.complete({'taskType':'tutor','question':'개념을 설명해줘.',
                    'sources':[{'text':'x'*40000}]},max_output=100)
            self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
