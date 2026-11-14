"""Mentor tool execution, using fake providers and no remote calls or user data."""
import unittest
from pdf_ai import tutor, BudgetExceeded
from pdf_tutor_intent import refined_plan, plan_question
from test_pdf_tutor_intent import Replay, document, semantic


def lookup(subject='해외 고용 통계', **extra):
    return {**semantic(subject, web='explicit', followup=True),
            'webOptOut': False, 'toolRequest': {'tool': 'web.search',
                'query': subject+' 공식 통계 정의와 연도 및 분모 확인', 'refresh': False}, **extra}


class MentorToolRequestTests(unittest.TestCase):
    def test_contextual_lookup_runs_once_without_an_extra_answer_or_classifier(self):
        for question in ('너가 찾아서알려줘.', '그 수치는 네가 확인해와', '그럼 일본 쪽 수치로 부탁해'):
            with self.subTest(question=question):
                subject='일본 임시직 비중' if '일본' in question else '미국 임시직 비중'
                provider=Replay(lookup(subject))
                memory={'documentId':'doc','topicQuestion':'미국 임시직 비중',
                    'turns':[{'question':'미국 임시직 비중은?', 'answer':'자료에는 없어요.'}]}
                result=tutor(document(),question,provider,memory=memory)
                self.assertEqual((len(provider.plans),len(provider.searches),len(provider.answers)),(1,1,0))
                self.assertIn(subject,provider.searches[0])
                self.assertNotIn('자료에는 없어요',provider.searches[0])
                self.assertTrue(result['searchDecision']['attempted'])

    def test_executable_lookup_can_investigate_definitions_without_a_local_veto(self):
        provider=Replay(lookup(ask=True,missingConditions=['통계 정의']))
        tutor(document(),'그 비율을 확인해줘',provider)
        self.assertEqual(len(provider.searches),1)

    def test_no_lookup_is_the_default_even_when_answer_requests_it(self):
        for subject in ('통계의 정의','표에 있는 비율 계산','직전 설명을 쉽게 풀기'):
            provider=Replay({**semantic(subject),'toolRequest':None,'webOptOut':False})
            result=tutor(document(),'확인해서 설명해줘',provider)
            self.assertEqual(len(provider.searches),0)
            self.assertFalse(result['searchDecision']['attempted'])
            self.assertTrue(provider.answers[0]['webSearchState']['capabilityAvailable'])

    def test_true_missing_target_and_semantic_opt_out_do_not_search(self):
        for plan in ({**lookup(), 'toolRequest':None,'ask':True},lookup(webOptOut=True)):
            provider=Replay(plan)
            tutor(document(),'그거 부탁해',provider)
            self.assertFalse(provider.searches)

    def test_research_reuse_and_refresh_are_bounded(self):
        provider=Replay(lookup())
        first=tutor(document(),'확인해줘',provider)
        tutor(document(),'그 기준을 더 풀어줘',provider,memory=first['memory'])
        self.assertEqual(len(provider.searches),1)
        provider.plan=lookup(toolRequest={**lookup()['toolRequest'],'refresh':True})
        tutor(document(),'다시 확인해줘',provider,memory=first['memory'])
        self.assertEqual(len(provider.searches),2)

    def test_failure_does_not_retry_or_claim_search_is_disabled(self):
        class Failed(Replay):
            def web_search(self,question,topic_hint=''):
                self.searches.append(question)
                raise BudgetExceeded('no lookup budget')
        provider=Failed(lookup())
        result=tutor(document(),'확인해줘',provider)
        self.assertEqual((len(provider.plans),len(provider.searches),len(provider.answers)),(1,1,1))
        self.assertEqual(provider.answers[0]['webSearchState']['status'],'failed')
        self.assertTrue(provider.answers[0]['webSearchState']['capabilityAvailable'])
        self.assertTrue(result['searchDecision']['attempted'])

    def test_invalid_tools_cannot_be_executed(self):
        local=plan_question('뜻이 뭐야?',{},1,None)
        for tool in ({'tool':'shell','query':'x','refresh':False},
                     {'tool':'web.search','query':'','refresh':False},
                     {'tool':'web.search','query':'x','refresh':'yes'}):
            self.assertEqual(refined_plan(local,lookup(toolRequest=tool),17,None),local)


if __name__=='__main__':unittest.main()
