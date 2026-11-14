import copy
import unittest
from unittest.mock import patch
from pdf_tutor_page_image import elliptical_page_request, located_page_request, planned_source_request
from pdf_ai import tutor
from test_pdf_tutor_examples import ReplayProvider, document

class EllipsisTests(unittest.TestCase):
    def test_location_completes_source_action(self):
        for previous in ['1번 풀이해줘', '3번 문제 풀어줄래?', '예제의 답 구해줘', '그래프의 모양을 설명해줘']:
            for q in ['1페이지에 있어', '1쪽에 1번 문제 있어.', '아니 1쪽 아래쪽이야', '1페이지예요']:
                with self.subTest(previous=previous,q=q):
                    r=located_page_request(q,self.state([previous]),1,7,33)
                    self.assertEqual(r['page'],1)
                    self.assertIn(previous,r['request'])
                    self.assertFalse(r['candidate'])

    def test_number_does_not_become_page_number(self):
        r=located_page_request('1번 풀이해줘',{},None,7,33)
        self.assertEqual(r['page'],7)
        self.assertTrue(r['candidate'])
        self.assertIsNone(located_page_request('1번 풀이해줘',{},None,None,33))

    def test_no_inheritance_across_new_topic_or_negation(self):
        for previous in ['뉴턴 법칙 설명해줘', '1번 풀지 말고 개념만 설명해줘', '새 문제 만들어줘']:
            self.assertIsNone(located_page_request('1페이지에 있어',self.state(['1번 풀이해줘',previous]),1,1,33))
        for q in ['1페이지에는 없어', '1페이지 문제 말고 원리만 설명해줘', '1페이지에 운동량 개념이 있어',
                  '1페이지에 새 문제 만들어줘', '1페이지 삭제해줘']:
            self.assertIsNone(located_page_request(q,self.state(['1번 풀이해줘']),1,1,33))
        self.assertIsNone(located_page_request('99페이지에 있어',self.state(),0,1,33))
        self.assertIsNone(located_page_request('1페이지에 있어',{},1,1,33))

    def test_location_then_next_page_carries_action(self):
        s=self.state(['1번 풀이해줘','1페이지에 있어'])
        r=elliptical_page_request('다음 페이지도',s,None,1,33)
        self.assertEqual(r['page'],2)
        self.assertIn('문제 풀이',r['request'])

    def test_candidate_and_location_integration_no_added_calls(self):
        d=document();d['pages']=[{} for _ in range(33)]
        for q,s,page,candidate in [('7페이지 1번 풀이해줘',None,7,False),
                                  ('1페이지에 있어',self.state(['1번 풀이해줘']),1,False)]:
            p=ReplayProvider(answer='풀이예요.',responseKind='document',visualPages=[page])
            with patch('pdf_tutor_page_image.prepare',return_value=([{'data':'test'}],[{'page':page}])) as prep:
                tutor(d,q,p,memory=s,current_page=7,web_fallback=False)
            self.assertEqual(prep.call_args.args[3],page)
            self.assertTrue(prep.call_args.kwargs['page_bound'])
            self.assertEqual(p.calls[0]['pdfPageAccess']['candidateOnly'],candidate)
            if candidate:
                self.assertEqual(p.calls[0]['pdfPageAccess']['requestedItem'],'1번')
                self.assertIn('must match exactly',p.calls[0]['task'])
            self.assertEqual(len(p.calls),1)

    def test_existing_plan_source_target_and_concept_opt_out(self):
        for q in ['표의 합계를 읽어줘', '작품 이미지의 주요 색을 설명해줘', '예제의 답 구해줘']:
            self.assertTrue(planned_source_request(q,{'scope':'pdf','page':3}))
            self.assertFalse(planned_source_request(q,{'scope':'general','page':3}))
            self.assertFalse(planned_source_request(q,{'scope':'pdf','page':None}))
        for q in ['그래프의 원리를 설명해줘', '표의 개념을 설명해줘', '새로운 문제 만들어줘',
                  '문제 풀지 말고 개념만 알려줘']:
            self.assertFalse(planned_source_request(q,{'scope':'pdf','page':3}))

    def test_semantic_source_page_reused_without_another_judgment(self):
        from test_pdf_tutor_final_answer import Provider, reply
        from test_pdf_tutor_intent import semantic
        d=document();d['pages']=[{} for _ in range(5)]
        p=Provider([{**reply('합계예요.'),'visualPages':[3]}],{**semantic('표의 합계',page=3),'scope':'pdf'})
        with patch('pdf_tutor_page_image.prepare',return_value=([{'data':'test'}],[{'page':3}])) as prep:
            tutor(d,'표의 합계를 읽어줘',p,current_page=3,web_fallback=False)
        self.assertEqual(prep.call_args.args[3],3)
        self.assertTrue(prep.call_args.kwargs['page_bound'])
        self.assertEqual(len(p.calls),1)

    def state(self,questions=None):
        return {'documentId':'doc','topicQuestion':'1페이지 풀이 ㄱㄴ?',
                'focus':{'page':1,'viewerPage':1},
                'turns':[{'question':q,'answer':'답변'} for q in (questions or ['1페이지 풀이 ㄱㄴ?'])]}
    def test_page_changes_carry_action_not_old_page(self):
        for q,page in [('15페이지 부탁할게',15),('그럼 15쪽은?',15),('다음 페이지도',None),('이것도 부탁해',None),('좀 더 자세히',None)]:
            r=elliptical_page_request(q,self.state(),page,1,33)
            self.assertEqual(r['page'],page or (2 if '다음' in q else 1))
            self.assertIn('문제 풀이',r['request'])
    def test_viewer_movement_and_chain(self):
        self.assertEqual(elliptical_page_request('이것도',self.state(),None,15,33)['page'],15)
        s=self.state(['1페이지 풀어줘','15페이지 부탁할게'])
        self.assertIsNotNone(elliptical_page_request('16페이지도',s,16,1,33))
    def test_relative_page_after_implicit_task_does_not_revive_old_topic(self):
        s=self.state(['1페이지 풀어줘','다른 주제야. 이상적분 개념만 알려줘','15페이지 부탁할게'])
        s['focus']['page']=15
        for q,page in [('다음 페이지도',16),('이전 쪽도',14)]:
            r=elliptical_page_request(q,s,None,1,33)
            self.assertEqual(r['page'],page)
            self.assertIn('내용 설명',r['request'])
            self.assertNotIn('문제 풀이',r['request'])
        self.assertIsNone(elliptical_page_request('다음 페이지도',{},None,1,33))
        s['focus']['page']=33
        self.assertIsNone(elliptical_page_request('다음 페이지도',s,None,1,33))

    def test_relative_page_integration_after_topic_switch(self):
        d=document();d['pages']=[{} for _ in range(33)]
        s=self.state(['다른 주제야. 개념만 알려줘','15페이지 부탁할게'])
        s['focus']['page']=15
        p=ReplayProvider(answer='16쪽 내용이에요.',responseKind='document',visualPages=[16])
        with patch('pdf_tutor_page_image.prepare',return_value=([{'data':'test'}],[{'page':16}])) as prep:
            tutor(d,'다음 페이지도',p,memory=s,current_page=1,web_fallback=False)
        self.assertEqual(prep.call_args.args[3],16)
        self.assertTrue(prep.call_args.kwargs['page_bound'])
        self.assertEqual(len(p.calls),1)
    def test_no_cross_topic_or_document_inference(self):
        for q in ['15페이지 개념만 설명해줘','15페이지 말고 새 문제 만들어줘','15페이지 파일 삭제해줘']:
            self.assertIsNone(elliptical_page_request(q,self.state(),15,1,33))
        for qs in [['선밀도의 뜻을 설명해줘'],['1페이지 풀어줘','운동량 개념 설명해줘'],['새 문제 만들어줘']]:
            self.assertIsNone(elliptical_page_request('15페이지 부탁해',self.state(qs),15,1,33))
        self.assertIsNone(elliptical_page_request('15페이지 부탁해',{},15,1,33))
        self.assertIsNone(elliptical_page_request('99페이지도',self.state(),0,1,33))
    def test_tutor_integration_uses_new_page_and_one_answer_call(self):
        d=document();d['pages']=[{} for _ in range(33)]
        p=ReplayProvider(answer='15페이지 풀이예요.',responseKind='document',visualPages=[15])
        with patch('pdf_tutor_page_image.prepare',return_value=([{'data':'test'}],[{'page':15}])) as prep:
            r=tutor(d,'15페이지 부탁할게',p,memory=self.state(),current_page=1,web_fallback=False)
        self.assertEqual(prep.call_args.args[3],15)
        self.assertIn('문제 풀이',prep.call_args.args[2])
        self.assertEqual(p.calls[0]['question'],'15페이지 부탁할게')
        self.assertIn('문제 풀이',p.calls[0]['questionPlan']['resolvedRequest'])
        self.assertEqual(len(p.calls),1)
        self.assertEqual(r['visualPages'],[15])

if __name__=='__main__':unittest.main()
