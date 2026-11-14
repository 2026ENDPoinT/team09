"""Document absence/count claims require a whole-page scan, not lexical top hits."""
import copy
import unittest
from unittest.mock import patch

import pdf_ai as ai
from pdf_tutor_document_find import request,scan,answer
from pdf_tutor_document_scope import summary_request,full_review_request
from test_pdf_tutor_intent import chunk


def document(texts):
    return {'documentId':'doc','pages':[{'nativeText':t,'textState':'ready','imageRegions':[]}
                                      for t in texts],
            'chunks':[chunk(t,p,f'p{p}') for p,t in enumerate(texts,1)]}


class NoRemote:
    model='test-only'
    def __init__(self):self.ledger={'requests':[]}
    def plan_tutor(self,*args,**kwargs):raise AssertionError('count must not call a planner')
    def complete(self,*args,**kwargs):raise AssertionError('count must not call an answer model')
    def web_search(self,*args,**kwargs):raise AssertionError('count must not search the web')


class DocumentFindTests(unittest.TestCase):
    def test_actual_unquoted_question_resolves_only_the_named_person(self):
        q='전체 내용을 봐바. 혹시 여기서 데이먼이라는 사람에 대한 언급이 몇번나와?'
        self.assertEqual(request(q),{'term':'데이먼','kind':'person_name'})
        for name in ('고든','제이미','Damon'):
            with self.subTest(name=name):
                self.assertEqual(request(f'이 PDF에서 {name}이라는 사람이 몇 번 언급돼?')['term'],name)

    def test_quoted_terms_and_simple_particle_are_supported(self):
        for q in ['PDF에서 “배당성장률”은 몇 번 나와?', "전체 자료에서 'ROE' 언급 횟수만 알려줘",
                  '이 문서에서 고든이 몇 번 언급돼?','여기서 「효율시장가설」이 총 몇회 등장해?']:
            with self.subTest(q=q):self.assertIsNotNone(request(q))

    def test_ambiguous_external_page_specific_and_multipart_tasks_keep_existing_route(self):
        for q in ['이 문서에는 몇 번 나와?', '여기서 그 사람은 몇 번 나와?',
                  '자료에서 몇 번 문제를 풀어줘', 'PDF 2쪽에서 “고든”은 몇 번 나와?',
                  '웹에서 “데이먼”은 몇 번 언급돼?', '이 PDF 말고 다른 자료에서 “고든”은 몇 번 나와?',
                  'PDF에서 “ROE”와 “ROA”는 각각 몇 번 나와?',
                  'PDF에서 “데이먼” 말고 고든은 몇 번 나와?',
                  'PDF에서 데이먼이라는 사람 말고 고든이라는 사람은 몇 번 나와?',
                  'PDF에서 “고든”이 몇 번 나오는지 말하고 의미도 설명해줘',
                  '고든 모형은 왜 배당성장률을 쓰는 거야?']:
            with self.subTest(q=q):self.assertIsNone(request(q))

    def test_counts_every_page_including_late_and_margin_mentions_once(self):
        doc=document(['표지 고든\n본문 고든','중간 내용','마지막 고든 고든'])
        doc['chunks']+=copy.deepcopy(doc['chunks'])  # overlapping retrieval chunks must not double count
        doc['chunks'][0]['text']='본문 고든'  # the margin still belongs to the original document
        result=scan(doc,{'term':'고든'})
        self.assertEqual(result['count'],4)
        self.assertEqual(result['pageCounts'],[{'page':1,'count':2},{'page':3,'count':2}])
        self.assertTrue(result['fullTextChecked'])

    def test_original_pdf_reading_order_repairs_a_word_interrupted_by_math_in_the_index(self):
        doc=document(['예상 주\n𝒊 𝒏 𝒏\n가를 계산한다.'])
        with patch('pdf_tutor_document_find.source_text',return_value=['예상 주\n가를 계산한다.']):
            result=scan(doc,{'term':'주가'},folder='connected')
        self.assertEqual(result['count'],1)
        self.assertEqual(result['basis'],'source_pdf_text')

    def test_layout_failure_without_original_access_cannot_prove_zero(self):
        doc=document(['예상 주\n𝒊 𝒏 𝒏\n가를 계산한다.'])
        doc['pages'][0]['warnings']=['다단/표 배치 가능성 · 읽기 순서 확인 필요']
        with patch('pdf_tutor_document_find.source_text',return_value=None):
            result=scan(doc,{'term':'주가'})
        self.assertFalse(result['fullTextChecked'])

    def test_failed_original_read_cannot_prove_zero_from_a_stale_healthy_index(self):
        with patch('pdf_tutor_document_find.source_text',return_value=None):
            result=scan(document(['건강한 캐시 원문']),{'term':'데이먼'},folder='connected')
        self.assertFalse(result['fullTextChecked'])

    def test_study_paraphrases_are_never_counted_as_original_mentions(self):
        doc=document(['금융의 기본 원리','배당과 주가'])
        doc['chunks'].append({**chunk('데이먼 데이먼 데이먼',1,'invented'),'source':'ai_visual_observation'})
        result=scan(doc,{'term':'데이먼'})
        self.assertEqual(result['count'],0)
        self.assertTrue(result['fullTextChecked'])

    def test_case_unicode_font_and_korean_line_wrap_are_normalized(self):
        doc=document(['ROE roe 𝑹𝑶𝑬','데이\n먼은 고\n든을 설명한다.'])
        self.assertEqual(scan(doc,{'term':'ROE'})['count'],3)
        self.assertEqual(scan(doc,{'term':'데이먼','kind':'person_name'})['count'],1)
        self.assertEqual(scan(doc,{'term':'고든','kind':'person_name'})['count'],1)

    def test_longer_different_person_name_does_not_count(self):
        doc=document(['데이먼드와 McDamon, Damonian. 데이먼은, 데이먼이라는 인물. Damon\'s work.'])
        self.assertEqual(scan(doc,{'term':'데이먼','kind':'person_name'})['count'],2)
        self.assertEqual(scan(doc,{'term':'Damon','kind':'person_name'})['count'],1)

    def test_missing_or_visual_page_never_produces_a_document_wide_zero(self):
        for page in ({'nativeText':''},{'nativeText':'인용문만 있어요','imageRegions':[{'id':'image'}]},
                     {'nativeText':'원문','ocrNeeded':True},{'nativeText':'원문','status':'failed'}):
            with self.subTest(page=page):
                doc=document(['정상 원문']);doc['pages'].append(page)
                result=scan(doc,{'term':'데이먼'})
                self.assertFalse(result['fullTextChecked'])
                self.assertIn('확정할 수 없어요',answer(result))
                self.assertNotIn('전체를 검색한 결과',answer(result))

    def test_partial_positive_result_is_also_not_an_exact_total(self):
        doc=document(['고든 고든',''])
        result=scan(doc,{'term':'고든'})
        self.assertEqual(result['count'],2)
        self.assertFalse(result['fullTextChecked'])
        self.assertIn('현재 확인된',answer(result))
        self.assertIn('확정할 수 없어요',answer(result))

    def test_empty_document_does_not_claim_zero_mentions(self):
        result=scan(document([]),{'term':'데이먼'})
        self.assertFalse(result['fullTextChecked'])
        self.assertIn('확정할 수 없어요',answer(result))

    def test_image_count_uses_only_ocr_and_links_matching_original_pages(self):
        doc=document(['본문의 데이먼 데이먼','다른 원문','본문의 데이먼'])
        ocr={'textsByPage':{2:['데이먼 사진','데이먼 삽화']},'checkedPages':[1,2,3],'unreadablePages':[]}
        with patch('pdf_tutor_image_ocr.scan',return_value=ocr):
            result=ai.run_tutor_request(None,doc,{'question':'이 pdf 전체에서 이미지 속 데이먼이라는 말이 몇번 나와?'},
                                        NoRemote())
        self.assertEqual(result['documentSearch']['pageCounts'],[{'page':2,'count':2}])
        self.assertEqual(result['visualPages'],[2])
        self.assertEqual(result['evidence'],[])
        self.assertFalse(result['evidenceIncomplete'])
        self.assertEqual(result['runUsage']['requests'],0)

    def test_an_unreadable_image_page_does_not_prove_zero(self):
        ocr={'textsByPage':{},'checkedPages':[1],'unreadablePages':[2]}
        with patch('pdf_tutor_image_ocr.scan',return_value=ocr):
            result=scan(document(['원문','다른 원문']),{'term':'데이먼','scope':'images'})
        self.assertFalse(result['fullTextChecked'])
        self.assertEqual(result['searchedPages'],[1])
        self.assertIn('2쪽',answer(result))
        self.assertNotIn('**0회**',answer(result))

    def test_image_with_native_ocr_layer_is_not_double_counted(self):
        ocr={'textsByPage':{1:['데이먼 데이먼']},'checkedPages':[1,2],'unreadablePages':[]}
        with patch('pdf_tutor_image_ocr.scan',return_value=ocr):
            result=scan(document(['데이먼 데이먼','다른 원문']),{'term':'데이먼','scope':'all'})
        self.assertEqual(result['count'],2)
        self.assertFalse(result['fullTextChecked'])
        self.assertIn('중복',answer(result))

    def test_actual_adapter_is_free_streams_and_records_only_the_real_question_and_answer(self):
        doc=document(['금융과 주식','배당성장률','고든 고든'])
        q='전체 내용을 봐바. 혹시 여기서 데이먼이라는 사람에 대한 언급이 몇번나와?'
        memory={'documentId':'doc','sourceTask':{'page':2,'item':3,'action':'solve'},
                'turns':[{'question':'3번 문제 풀어줘','answer':'문제 풀이예요.'}]}
        stream=[];stages=[]
        with patch('pdf_ai.tutor_hits',side_effect=AssertionError('never count retrieval hits')):
            result=ai.run_tutor_request(None,doc,{'question':q,'page':3,'memory':memory,'webFallback':True},
                                        NoRemote(),progress=stream.append,stage=stages.append)
        self.assertIn('**0회**',result['answer'])
        self.assertNotIn('발췌',result['answer'])
        self.assertNotIn('보내',result['answer'])
        self.assertEqual(result['runUsage']['requests'],0)
        self.assertEqual(result['runUsage']['usageBasedUsd'],0)
        self.assertEqual(stream[-1],result['answer'])
        self.assertEqual(result['memory']['turns'][-1]['question'],q)
        self.assertEqual(result['memory']['turns'][-1]['answer'],result['answer'])
        self.assertNotIn('sourceTask',result['memory'])
        self.assertEqual(stages,['pdf_search','answer_wait'])

    def test_full_reading_casual_verbs_are_not_misrouted_as_partial_summary(self):
        for q in ['전체 내용을 봐바. 혹시 다른 분야 내용도 있어?',
                  '이 PDF 전체 내용을 살펴봐.','문서 전체를 봐줘.']:
            with self.subTest(q=q):
                self.assertTrue(full_review_request(q))
                self.assertTrue(summary_request(q,{}))


if __name__=='__main__':unittest.main()
