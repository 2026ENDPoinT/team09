"""Offline routing, research reuse, failure and clickable-source contracts."""
import unittest
from home_assistant import chat
from test_home_assistant import Fake
from test_pdf_tutor_intent import semantic

class Replay(Fake):
    def __init__(self,plan):super().__init__();self.plan=plan;self.searches=[];self.plans=[];self.failure=False
    def plan_tutor(self,payload):self.plans.append(payload);return self.plan
    def web_search(self,question,topic_hint='',**options):
        self.searches.append((question,topic_hint))
        if self.failure:raise RuntimeError('offline search failure')
        return {'answer':'공식 자료에 3.14라고 적혀 있어요. [1]',
                'webSources':[{'number':1,'title':'공식 [발표]','url':'https://www.python.org/downloads/'}]}

class WebTests(unittest.TestCase):
    def test_fresh_search_synthesizes_once_with_sources_and_date(self):
        p=Replay(semantic('Python 최신 버전',web='fresh'));shown=[]
        r=chat({'question':'Python 최신 정식 버전 알려줘','localDateTime':'2026-10-24T22:00:00+09:00','timezone':'Asia/Seoul'},p,shown.append)
        self.assertEqual(1,len(p.searches));self.assertEqual(1,len(p.calls));self.assertEqual('succeeded',r['searchStatus'])
        self.assertIn('2026-10-24',p.searches[0][0]);self.assertIn('externalResearch',p.calls[0][0])
        self.assertIn('https://www.python.org/downloads/',r['answer']);self.assertEqual(shown[-1],r['answer'])
        self.assertEqual(1,len(r['memory']['webResearch']))
    def test_followup_reuses_but_refresh_searches_again(self):
        p=Replay(semantic('Python 최신 버전',web='fresh'))
        first=chat({'question':'Python 최신 버전 알려줘'},p)
        p.plan=semantic('Python 최신 버전',followup=True)
        r=chat({'question':'그 내용을 한 줄로 요약해줘','memory':first['memory']},p)
        self.assertEqual(1,len(p.searches));self.assertEqual('reused',r['searchStatus']);self.assertTrue(r['webSources'])
        self.assertNotIn('**출처**',r['answer'])
        self.assertNotIn('**출처**',r['memory']['turns'][-1]['answer'])
        p.plan=semantic('Python 최신 버전',followup=True,web='fresh')
        refreshed=chat({'question':'최신 기준으로 다시 검색해줘','memory':r['memory']},p)
        self.assertIn('**출처**',refreshed['answer'])
        self.assertEqual(2,len(p.searches))
        p.plan=semantic('Python 최신 버전 변경점',followup=True,web='verify')
        chat({'question':'그 버전 변경점을 공식 자료로 알려줘','memory':r['memory']},p)
        self.assertEqual(3,len(p.searches))
    def test_followup_strips_model_copied_footer_and_reference(self):
        p=Replay(semantic('Python 최신 버전',web='fresh'))
        first=chat({'question':'Python 최신 버전 알려줘'},p)
        p.plan=semantic('Python 최신 버전',followup=True)
        p.complete=lambda payload,**options:{'answer':'맞아요. [1]\n\n**출처**\n- 이전 출처'}
        result=chat({'question':'그렇구나','memory':first['memory']},p)
        self.assertEqual('맞아요.',result['answer'])
        self.assertTrue(result['memory']['webResearch'])
    def test_missing_target_and_opt_out_never_search(self):
        p=Replay(semantic('환율',web='fresh',ask=True));p.plan['missingConditions']=['통화쌍']
        r=chat({'question':'환율 지금 얼마야?'},p)
        self.assertFalse(p.searches);self.assertEqual('clarification_required',r['searchStatus'])
        p.plan=semantic('최신 버전',web='fresh')
        r=chat({'question':'검색하지 말고 아는 범위에서 답해줘'},p)
        self.assertFalse(p.searches);self.assertEqual('disabled',r['searchStatus'])
    def test_stable_reasoning_does_not_search_and_failure_does_not_claim_success(self):
        p=Replay(semantic('곱셈 계산'))
        chat({'question':'10곱하기4는?'},p);self.assertFalse(p.searches)
        p.plan=semantic('Python 최신 버전',web='fresh');p.failure=True
        r=chat({'question':'Python 최신 버전 알려줘'},p)
        self.assertEqual('failed',r['searchStatus']);self.assertEqual([],r['webSources']);self.assertNotIn('**출처**',r['answer'])
        self.assertEqual('failed',p.calls[-1][0]['searchStatus'])
    def test_unavailable_planner_does_not_authorize_guess_search(self):
        p=Replay(semantic('대상',web='fresh'))
        def broken(payload):raise RuntimeError('planner unavailable')
        p.plan_tutor=broken
        r=chat({'question':'검색해줘'},p)
        self.assertFalse(p.searches);self.assertEqual('planner_unavailable',r['searchStatus'])
    def test_long_saved_answer_keeps_source_footer_within_memory_limit(self):
        p=Replay(semantic('Python 최신 버전',web='fresh'))
        p.complete=lambda payload,**options:{'answer':'가'*6000}
        r=chat({'question':'Python 최신 버전 알려줘'},p)
        saved=r['memory']['turns'][-1]['answer']
        self.assertLessEqual(len(saved.encode('utf-8')),5000);self.assertIn('**출처**',saved);self.assertIn('https://www.python.org/downloads/',saved)

if __name__=='__main__':unittest.main()
