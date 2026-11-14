import unittest
from unittest.mock import patch
from pdf_tutor_page_image import image_request, prepare
from pdf_ai import tutor
from test_pdf_tutor_examples import ReplayProvider, document

class PageImageTests(unittest.TestCase):
    def test_visual_synonyms_and_spatial_details_on_text_rich_pages(self):
        d=self.doc('충분한 개념 설명과 표 및 그림이 함께 있는 페이지입니다. '*30)
        for q in ['작품 이미지를 보고 설명해줘', '이 이미지의 세 패널을 비교해서 설명해줘',
                  '오른쪽 합계는 얼마야?', '왼쪽에 큰 원 보이지? 어떤 색이야?',
                  '가운데 인물은 어떻게 생겼어?', '전체적으로 뭐가 제일 눈에 띄어?',
                  '거기 제일 위 숫자는 얼마야?', '거기 왼쪽이 뭐야?']:
            with self.subTest(q=q):
                self.assertIsNotNone(image_request(d,q,1,page_bound=True))
                self.assertIsNone(image_request(d,q,1,page_bound=False))
        self.assertIsNone(image_request(self.doc(boxes=False),'오른쪽 합계는 얼마야?',1,page_bound=True))

    def test_concepts_do_not_trigger_visual_synonyms_or_positions(self):
        for text in ['제목', '충분한 본문 '*60]:
            for q in ['이미지 분류의 개념만 설명해줘', '작품의 추상 개념만 알려줘',
                      '오른쪽 식의 원리만 설명해줘', '이미지는 보지 말고 뜻만 알려줘',
                      '그림을 제외하고 개념만 설명해줘', '새로운 문제 만들어줘']:
                with self.subTest(q=q,text=text[:5]):
                    self.assertIsNone(image_request(self.doc(text),q,1,page_bound=True))

    def test_vague_named_page_with_sparse_source(self):
        for q in ['1페이지 부탁할게', '그럼 1쪽은?', '1페이지', 'page 1 please']:
            self.assertEqual(image_request(self.doc(),q,1,page_bound=True)['reason'],
                             'named_page_missing_text')
            self.assertIsNone(image_request(self.doc('충분한 본문 '*60),q,1,page_bound=True))
        for q in ['1페이지 개념만 알려줘','1페이지 삭제해줘','새로운 문제 만들어줘']:
            self.assertIsNone(image_request(self.doc(),q,1,page_bound=True))

    def test_render_failure_is_distinct_from_unreadable_pdf(self):
        p=ReplayProvider()
        from pathlib import Path
        with patch('pdf_ai.load_visual_notes',return_value=[]), patch('pdf_ai.tutor_study_guide',return_value=(None,[])):
            tutor(self.doc(),'1페이지 부탁할게',p,folder=Path('/nonexistent'),web_fallback=False)
        self.assertEqual(p.calls[0]['pdfPageAccess']['image'],'render_failed')
        self.assertIn('last resort',p.calls[0]['task'])

    def test_ambiguous_task_can_still_receive_named_page_image(self):
        from test_pdf_tutor_final_answer import Provider, reply
        from test_pdf_tutor_intent import semantic
        plan=semantic('1페이지',page=1,ask=True)
        p=Provider([{**reply('1쪽 문제를 풀이해드릴까요?'),'visualPages':[1]}],plan)
        with patch('pdf_tutor_page_image.prepare',return_value=([{'data':'test'}],[{'page':1}])):
            tutor(self.doc(),'1페이지 부탁할게',p,web_fallback=False)
        self.assertEqual(p.calls[0][0]['pdfPageAccess']['image'],'attached')
        self.assertEqual(len(p.calls),1)

    def test_vague_page_image_does_not_keep_old_topic_hint(self):
        from test_pdf_tutor_final_answer import Provider, reply
        from test_pdf_tutor_intent import semantic
        p=Provider([{**reply('1쪽에 있는 문제예요.'),'visualPages':[1]}],
                   semantic('광합성',page=1))
        with patch('pdf_tutor_page_image.prepare',return_value=(
                [{'data':'test'}],[{'page':1,'reason':'named_page_missing_text'}])):
            tutor(self.doc(),'1페이지 부탁할게',p,web_fallback=False)
        payload=p.calls[0][0]
        self.assertEqual(payload['questionPlan']['subject'],'1페이지 내용')
        self.assertEqual(payload['topicHint'],'')

    def test_page_bound_short_solving_requests(self):
        for q in ['1페이지 풀이 ㄱㄱ', '1쪽 풀어줘', '이 페이지 풀어줄래?', '1페이지 계산해줘']:
            self.assertIsNotNone(image_request(self.doc(),q,1,page_bound=True))
            self.assertIsNone(image_request(self.doc(),q,1,page_bound=False))
        for q in ['1페이지 풀이 말고 개념만 설명해줘', '1페이지 풀지 말고 개념만 알려줘']:
            self.assertIsNone(image_request(self.doc('개념 설명 '*50),q,1,page_bound=True))

    def doc(self,text='제목',boxes=True):
        d=document();d['chunks'][0]['text']=text
        d['pages'][0]['imageRegions']=[{'bbox':[.1,.2,.9,.4]}] if boxes else []
        return d
    def test_scanned_problem_crop(self):
        r=image_request(self.doc(),'1페이지 문제 풀어줘',1,page_bound=True)
        self.assertEqual(r['page'],1);self.assertNotEqual(r['selectedRegion'],[0,0,1,1])
    def test_mixed_page_full_and_concept_without_image(self):
        d=self.doc('선밀도와 막대의 질량중심에 관한 설명입니다. '*20)
        self.assertEqual(image_request(d,'1페이지 예제 풀어줘',1,page_bound=True)['selectedRegion'],[0,0,1,1])
        self.assertIsNone(image_request(d,'1페이지 선밀도 개념만 설명해줘',1,page_bound=True))
    def test_bounds_and_intent(self):
        for q,p,b in [('1페이지 문제 풀어줘',1,False),('0페이지 문제 풀어줘',0,True),('2페이지 문제 풀어줘',2,True),('1페이지 새로운 문제 만들어줘',1,True),('1페이지 문제 말고 개념만 알려줘',1,True)]:
            self.assertIsNone(image_request(self.doc(),q,p,page_bound=b))
        self.assertEqual(image_request(self.doc(),'1페이지 전체 그림 설명해줘',1,page_bound=True)['selectedRegion'],[0,0,1,1])
    def test_render_failure_no_claim(self):
        self.assertEqual(prepare('/nonexistent',self.doc(),'1페이지 문제 풀어줘',1,page_bound=True),([],[]))
    def test_readable_text_problem_does_not_require_image(self):
        self.assertIsNone(image_request(self.doc('문제: 뉴턴의 제1법칙을 서술하세요.',False),
                                        '1페이지 문제 풀어줘',1,page_bound=True))
    def test_image_evidence_does_not_start_a_review_or_replace_prose(self):
        provider=ReplayProvider(answer='풀이예요.',responseKind='document',visualPages=[1])
        original=provider.complete;kwargs=[]
        def complete(*a,**k):kwargs.append(k);return original(*a,**k)
        provider.complete=complete
        with patch('pdf_tutor_page_image.prepare',return_value=([{'data':'test'}],[{'page':1}])):
            result=tutor(self.doc(),'1페이지 문제 풀어줘',provider,web_fallback=False)
        self.assertEqual(len(kwargs),1)
        self.assertEqual(kwargs[0]['image'],[{'data':'test'}])
        self.assertEqual(result['answer'],'풀이예요.')
        self.assertEqual(result['visualPages'],[1])
    def test_tutor_one_answer_call_and_image_citation(self):
        provider=ReplayProvider(answer='첨부된 문제의 풀이예요.',responseKind='document',visualPages=[1,99])
        original=provider.complete;kwargs=[]
        def complete(*a,**k):kwargs.append(k);return original(*a,**k)
        provider.complete=complete
        with patch('pdf_tutor_page_image.prepare',return_value=([{'data':'test'}],[{'page':1}])):
            result=tutor(self.doc(),'1페이지 문제 풀어줘',provider,web_fallback=False)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(kwargs[0]['image'],[{'data':'test'}])
        self.assertEqual(result['visualPages'],[1])

if __name__=='__main__':unittest.main()
