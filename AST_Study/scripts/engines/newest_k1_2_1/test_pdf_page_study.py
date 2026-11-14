"""End-to-end contracts for fused page reading, conservative skips and one-call flow."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
import base64
import pdf_ai as ai
import pdf_page_analysis as vision
import pdf_page_study as fused
from pdf_outline import overview, outline_items
from test_pdf_page_analysis import document, response
from test_pdf_generation_context import answer


def study_response(payload, kinds=None):
    analysis = response(payload)
    if kinds:
        for entry, element, kind in zip(analysis['inventory'], analysis['elements'], kinds):
            entry['kind'] = element['kind'] = kind
    parts, cards, excluded = [], [], []
    for element in analysis['elements']:
        key = element['key']
        if element['kind'] in fused.EXCLUDED_KINDS:
            excluded.append(key)
            continue
        evidence = [{'sourceId': key, 'quote': element['transcription']}]
        body = '개념의 조건과 관계를 설명합니다.'
        if element['formulas']:
            body += '\n\n$$\n' + element['formulas'][0]['latex'] + '\n$$'
        parts.append({'title':element['title'], 'body':body, 'easyExplanation':'조건을 바꾸면 결과가 달라져요.',
                      'evidence':evidence, 'visualPages':[], 'coveredElementIds':[key], 'sequence':None,
                      'standardKnowledgeUsed':False})
        cards.append({'name':element['title'], 'aliases':[], 'definition':'개념의 정의입니다.',
                      'explanation':body, 'easyExplanation':'조건과 결과를 연결해요.', 'example':'', 'confusion':'',
                      'evidence':copy.deepcopy(evidence), 'visualPages':[], 'sequence':None,
                      'standardKnowledgeUsed':False})
    return {'analysis':analysis, 'study':{'summary':{'title':'중요 개념', 'parts':parts,
            'easyExplanation':'', 'excludedElementIds':excluded, 'visualPages':[], 'standardKnowledgeUsed':False},
            'concepts':cards, 'processingNotes':[]}}


class Provider:
    model='gpt-6-luna'
    def __init__(self): self.calls=[]; self.context={}
    def complete(self,payload,**kwargs):
        self.calls.append((copy.deepcopy(payload),kwargs))
        if kwargs.get('image'): return study_response(payload)
        if 'topics' in payload: return {'body':'첫 주제에서 마지막 주제로 이어집니다.',
                                       'topicIds':[x['id'] for x in payload['topics']]}
        return answer(payload)


class FusedPageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.folder=Path(self.temp.name)
        self.doc=document(self.folder); self.provider=Provider()
        self.quiet=contextlib.redirect_stdout(io.StringIO());self.quiet.__enter__()
    def tearDown(self):
        self.quiet.__exit__(None,None,None);self.temp.cleanup()

    def test_three_pages_four_calls_with_all_parts_cards_and_resume(self):
        events=[]
        with patch('pdf_ai.emit',side_effect=lambda kind,**data:events.append((kind,data))):
            result=ai.generation(self.folder,self.doc,self.provider,page_mode=True)
        self.assertEqual(len(self.provider.calls),4)
        self.assertEqual([event['unit'] for kind,event in events if kind=='summary_unit_ready'],[1,2,3])
        self.assertEqual(len(result['sections']),3)
        self.assertEqual([len(s['parts']) for s in result['sections']],[4,4,4])
        self.assertEqual(len(result['concepts']),4)
        self.assertFalse(result['incompleteStudyPages'])
        self.assertEqual(result['overview']['overviewMethod'],'headings_once')
        self.assertEqual([s['evidence'][0]['page'] for s in result['sections']],[1,2,3])
        self.assertTrue(all(e['source']=='ai_transcription' for s in result['sections'] for e in s['evidence']))
        self.assertEqual(ai.generation(self.folder,self.doc,self.provider,page_mode=True),result)
        # A different scope reuses the same per-page combined result.
        ai.generation(self.folder,self.doc,self.provider,scope='page',page=2,page_mode=True)
        self.assertEqual(len(self.provider.calls),4)

    def test_handout_with_contents_and_teaching_never_skips_whole_page(self):
        self.doc=document(self.folder,1)
        class Mixed(Provider):
            def complete(self,payload,**kwargs):
                self.calls.append((payload,kwargs))
                return study_response(payload,['contents','formula','problem','solution'])
        provider=Mixed()
        result=ai.generation(self.folder,self.doc,provider,page_mode=True)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(result['skippedStudyPages'],[])
        self.assertEqual(len(result['sections'][0]['parts']),1)
        self.assertIn('frac', result['sections'][0]['parts'][0]['body'])
        self.assertEqual(len(result['concepts']),1)

    def test_exercise_only_page_is_read_once_without_summary_followup(self):
        self.doc=document(self.folder,1)
        class Excluded(Provider):
            def complete(self,payload,**kwargs):
                self.calls.append((payload,kwargs))
                return study_response(payload,['contents','problem','solution','decoration'])
        provider=Excluded()
        result=ai.generation(self.folder,self.doc,provider,page_mode=True)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(result['skippedStudyPages'],[1])
        self.assertEqual(result['sections'],[])

    def test_only_truly_blank_full_page_skips_all_requests(self):
        self.doc=document(self.folder,1)
        self.doc['pages'][0].update(nativeText='',markdown='',textRegions=[],imageRegions=[])
        result=ai.generation(self.folder,self.doc,self.provider,page_mode=True)
        self.assertEqual(len(self.provider.calls),0)
        self.assertEqual(result['skippedStudyPages'],[1])
        self.assertTrue(self.doc['pages'][0]['pageAnalysis']['localBlank'])
        picture=Image.new('RGB',(100,100),'white');picture.putpixel((98,98),(0,0,0))
        out=io.BytesIO();picture.save(out,format='PNG')
        self.assertFalse(fused.blank_page({}, {'data':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()}))

    def test_reordered_elements_resolve_to_inventory_ids(self):
        payload=fused.page_payload(self.doc,1,{})
        raw=study_response(payload);raw['analysis']['elements'].reverse()
        analysis=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        analysis.update(page=1,inputKey=vision.key_for(self.doc,1))
        vision.apply_result(self.doc,analysis)
        result=fused.resolve_study(raw['study'],analysis,self.doc,1)
        self.assertFalse(result['summary'].get('contentIncomplete'))

    def test_invalid_study_reuses_image_reading_for_one_text_repair(self):
        self.doc=document(self.folder,1)
        class Missing(Provider):
            def complete(self,payload,**kwargs):
                if kwargs.get('image'):
                    self.calls.append((payload,kwargs))
                    result=study_response(payload);result['study']['concepts']=[]
                    return result
                return super().complete(payload,**kwargs)
        provider=Missing()
        result=ai.generation(self.folder,self.doc,provider,page_mode=True)
        self.assertEqual(len(provider.calls),2)
        self.assertEqual(sum(bool(kwargs.get('image')) for _,kwargs in provider.calls),1)
        page_caches=list((self.folder/'generated'/'page-study').iterdir())
        self.assertEqual(len(page_caches),1)
        self.assertTrue((page_caches[0]/'study-repair.json').is_file())
        self.assertTrue((page_caches[0]/'study.json').is_file())
        ai.generation(self.folder,self.doc,provider,page_mode=True)
        self.assertEqual(len(provider.calls),2)

    def test_broken_math_uses_one_text_only_repair_and_keeps_reading(self):
        self.doc=document(self.folder,1)
        class Broken(Provider):
            def complete(self,payload,**kwargs):
                if kwargs.get('image'):
                    self.calls.append((payload,kwargs))
                    value=study_response(payload)
                    value['study']['summary']['parts'][0]['body']=r'\int_0^1 x\,dx를 계산합니다.'
                    return value
                return super().complete(payload,**kwargs)
        provider=Broken()
        result=ai.generation(self.folder,self.doc,provider,page_mode=True)
        self.assertEqual(len(provider.calls),2)
        self.assertEqual(sum(bool(kwargs.get('image')) for _,kwargs in provider.calls),1)
        self.assertEqual(ai.study_math_issues(result),[])

    def test_cached_reading_uses_no_image_request(self):
        raw=response({'page':1,'anchors':vision.anchors(self.doc['pages'][0])})
        analysis=vision.validate(raw,self.doc['pages'][0],vision.key_for(self.doc,1))
        analysis.update(page=1,inputKey=vision.key_for(self.doc,1))
        vision.write_json(vision.cache_path(self.folder,self.doc,1),analysis)
        ai.generation(self.folder,self.doc,self.provider,scope='page',page=1,page_mode=True)
        self.assertEqual(len(self.provider.calls),1)
        self.assertFalse(self.provider.calls[0][1].get('image'))

    def test_learning_role_keeps_teaching_below_navigation_and_practice(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))
        roles=['navigation','teaching','practice','decoration']
        for entry, role in zip(raw['analysis']['inventory'],roles):entry['role']=role
        normalized=fused.normalize_reading(raw['analysis'])
        self.assertEqual([e['kind'] for e in normalized['elements']],['contents','formula','problem','decoration'])
        analysis=vision.validate(normalized,self.doc['pages'][0],vision.key_for(self.doc,1))
        self.assertIsNone(ai.non_teaching_page_result({'pageAnalysis':analysis}))
        page={'markdown':'예제 1. 문제를 풀어라.','pageAnalysis':{'status':'ready','elements':[
            {'kind':'problem','elementId':'p'}, {'kind':'text','elementId':'t','description':'정의를 설명한다'}]}}
        self.assertIsNone(ai.non_teaching_page_result(page))

    def test_uncertain_or_teaching_role_cannot_be_skipped_as_practice(self):
        raw=study_response(fused.page_payload(self.doc,1,{}), ['problem']*4)
        for entry in raw['analysis']['inventory']: entry['role']='teaching'
        value=fused.normalize_reading(raw['analysis'])
        self.assertTrue(all(e['kind']=='text' for e in value['inventory']))
        raw['analysis']['inventory'][0]['role']='uncertain'
        value=fused.normalize_reading(raw['analysis'])
        self.assertEqual(value['coverage'],'partial')
        analysis=vision.validate(value,self.doc['pages'][0],vision.key_for(self.doc,1))
        self.assertIsNone(ai.non_teaching_page_result({'pageAnalysis':analysis}))

    def test_failed_page_preserves_other_results_and_is_not_recharged_on_resume(self):
        class Failing(Provider):
            def complete(self,payload,**kwargs):
                if kwargs.get('image') and payload['page']==2:
                    self.calls.append((payload,kwargs))
                    raise ai.AiResponseError('test timeout')
                return super().complete(payload,**kwargs)
        provider=Failing()
        result=ai.generation(self.folder,self.doc,provider,page_mode=True)
        self.assertEqual(result['incompleteStudyPages'],[2])
        self.assertEqual(result['pageAnalysisIncompletePages'],[2])
        self.assertEqual(len(result['sections']),2)
        calls=len(provider.calls)
        self.assertEqual(ai.generation(self.folder,self.doc,provider,page_mode=True),result)
        self.assertEqual(len(provider.calls),calls)

    def test_parallel_completion_is_ordered_and_first_page_streams_early(self):
        second_started=threading.Event();first_visible=threading.Event();events=[]
        class Slow(Provider):
            def complete(self,payload,**kwargs):
                if kwargs.get('image'):
                    if payload['page']==2:
                        second_started.set()
                        if not first_visible.wait(3):raise AssertionError('first page held until all pages finish')
                    if payload['page']==1:
                        if not second_started.wait(3):raise AssertionError('requests did not overlap')
                return super().complete(payload,**kwargs)
        def emitted(kind,**data):
            if kind=='summary_unit_ready':
                events.append(data['unit'])
                if data['unit']==1:first_visible.set()
        with patch('pdf_ai.emit',side_effect=emitted):
            result=ai.generation(self.folder,self.doc,Slow(),page_mode=True)
        self.assertEqual(events,[1,2,3])
        self.assertEqual([s['evidence'][0]['page'] for s in result['sections']],[1,2,3])

    def test_output_and_schema_are_accounted_for_in_provider(self):
        bodies=[]
        def transport(body):
            bodies.append(body)
            return {'choices':[{'finish_reason':'stop','message':{'content':'{}'}}],
                    'usage':{'prompt_tokens':100,'completion_tokens':10}}
        provider=ai.Provider(self.folder,True,.2,'gpt-6-luna',transport)
        provider.complete({'task':'test'},response_format=fused.RESPONSE_FORMAT)
        self.assertEqual(bodies[0]['response_format'],fused.RESPONSE_FORMAT)
        self.assertIs(bodies[0]['store'],True)
        self.assertGreater(provider.ledger['requests'][0]['inputTokenBound'],len(json.dumps(fused.RESPONSE_FORMAT)))
        provider.complete({'task':'test'},response_format=fused.RESPONSE_FORMAT)
        self.assertEqual(len(bodies),1)

    def test_fused_request_marks_unchanging_prompt_as_cacheable(self):
        bodies=[]
        def transport(body):
            bodies.append(body)
            return {'choices':[{'finish_reason':'stop','message':{'content':'{}'}}],
                    'usage':{'prompt_tokens':100,'completion_tokens':10,
                             'prompt_tokens_details':{'cached_tokens':0}}}
        provider=ai.Provider(self.folder,True,.2,'gpt-6-luna',transport)
        provider.complete({'page':1},system_prompt='fixed prompt',
                          response_format=fused.RESPONSE_FORMAT,cache_stable_prefix=True)
        self.assertEqual(bodies[0]['prompt_cache_options'],{'mode':'explicit'})
        self.assertEqual(bodies[0]['messages'][0]['content'][0]['prompt_cache_breakpoint'],
                         {'mode':'explicit'})
        self.assertEqual(bodies[0]['messages'][1]['content'],'{"page": 1}')

    def test_missing_decoration_detail_does_not_force_second_study_request(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))
        raw['analysis']['inventory'].append({'key':'footer','kind':'decoration',
                                             'label':'쪽번호','anchorIds':[]})
        raw['study']['summary']['excludedElementIds'].append('footer')
        analysis=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        self.assertEqual(analysis['status'],'ready')
        self.assertTrue(any('decorative_detail_inferred' in warning for warning in analysis['warnings']))
        analysis.update(page=1, documentId=self.doc['documentId'],
                        inputKey=vision.key_for(self.doc,1))
        snapshot=copy.deepcopy(self.doc)
        vision.apply_result(snapshot,analysis)
        study=fused.resolve_study(raw['study'],analysis,snapshot,1)
        self.assertEqual(len(study['summary']['parts']),4)
        self.assertEqual(analysis['status'],'ready')

    def test_enhanced_crop_repairs_only_readable_teaching(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))
        raw['analysis']['elements'][1]['transcription']='핵심 관계를 설명하는 원문입니다. '*12
        raw['analysis']['elements'][1]['status']='unreadable'
        raw['analysis']['elements'][1]['uncertainDetails']=['분모가 흐림']
        raw['analysis']['coverage']='partial'
        initial=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        self.assertEqual(initial['status'],'partial')
        class RepairProvider(Provider):
            def complete(self,payload,**kwargs):
                self.calls.append((payload,kwargs))
                return {'status':'complete','transcription':'분모와 조건을 선명하게 판독했습니다.',
                        'formulas':[{'latex':r'F(x)=\frac{x}{2}','uncertainSymbols':''}],
                        'description':'교수 자료의 식','uncertainDetails':[]}
        provider=RepairProvider()
        with patch('pdf_page_study.enhanced_element_image',return_value={'data':'data:image/png;base64,AA==',
                                                        'width':1,'height':1,'bytes':1,'detail':'high'}):
            updated,analysis,changed=fused.repair_unreadable_teaching(
                self.folder,self.doc,1,provider,raw,initial,self.folder/'repair')
        self.assertTrue(changed)
        self.assertEqual(analysis['status'],'ready')
        self.assertEqual(updated['analysis']['elements'][1]['status'],'complete')
        self.assertEqual(len(provider.calls),1)
        with patch('pdf_page_study.enhanced_element_image',side_effect=AssertionError('rerendered')):
            _,again,_=fused.repair_unreadable_teaching(
                self.folder,self.doc,1,provider,raw,initial,self.folder/'repair')
        self.assertEqual(again['status'],'ready')
        self.assertEqual(len(provider.calls),1)

    def test_enhanced_crop_cannot_complete_unreadable_source(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))
        raw['analysis']['elements'][1]['status']='unreadable'
        raw['analysis']['coverage']='partial'
        initial=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        class Unreadable(Provider):
            def complete(self,payload,**kwargs):
                return {'status':'unreadable','transcription':'', 'formulas':[],
                        'description':'', 'uncertainDetails':['원본 픽셀이 소실됨']}
        with patch('pdf_page_study.enhanced_element_image',return_value={'data':'data:image/png;base64,AA==',
                                                        'width':1,'height':1,'bytes':1,'detail':'high'}):
            _,analysis,changed=fused.repair_unreadable_teaching(
                self.folder,self.doc,1,Unreadable(),raw,initial,self.folder/'repair')
        self.assertFalse(changed)
        self.assertEqual(analysis['status'],'partial')

    def test_contrast_retry_runs_when_unreadable_issue_is_also_reported(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))
        raw['analysis']['elements'][1]['status']='unreadable'
        raw['analysis']['elements'][1]['uncertainDetails']=['옅은 본문']
        raw['analysis']['coverage']='partial'
        initial=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        self.assertIn('model_reported_partial',initial['issues'])
        self.assertTrue(any(issue.startswith('element:') for issue in initial['issues']))
        clear=copy.deepcopy(raw)
        clear['analysis']['elements'][1]['status']='complete'
        clear['analysis']['elements'][1]['uncertainDetails']=[]
        clear['analysis']['coverage']='complete'
        class ContrastProvider(Provider):
            def complete(self,payload,**kwargs):
                self.calls.append((payload,kwargs))
                return clear
        provider=ContrastProvider()
        with patch('pdf_page_study.enhanced_element_image',return_value={'data':'data:image/png;base64,AA==',
                                                        'width':1,'height':1,'bytes':1,'detail':'high'}):
            _,refreshed,changed=fused.retry_contrast_page(
                self.folder,self.doc,1,provider,raw,initial,self.folder/'contrast',{})
        self.assertTrue(changed)
        self.assertEqual(refreshed['status'],'ready')
        self.assertEqual(len(provider.calls),1)

    def test_uncertain_crop_does_not_overwrite_original_reading(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))
        raw['analysis']['elements'][1]['transcription']='핵심 관계를 설명하는 원문입니다. '*12
        original=raw['analysis']['elements'][1]['transcription']
        raw['analysis']['elements'][1]['status']='unreadable'
        raw['analysis']['coverage']='partial'
        initial=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        class Approximate(Provider):
            def complete(self,payload,**kwargs):
                return {'status':'complete','transcription':'확신할 수 없는 추측 문장',
                        'formulas':[{'latex':'x=3','uncertainSymbols':'지수 불확실'}],
                        'description':'추측','uncertainDetails':['예시 문장의 일부 불분명함']}
        with patch('pdf_page_study.enhanced_element_image',return_value={'data':'data:image/png;base64,AA==',
                                                        'width':1,'height':1,'bytes':1,'detail':'high'}):
            updated,analysis,changed=fused.repair_unreadable_teaching(
                self.folder,self.doc,1,Approximate(),raw,initial,self.folder/'repair')
        self.assertTrue(changed)
        self.assertEqual(analysis['status'],'ready')
        self.assertEqual(updated['analysis']['elements'][1]['transcription'],original)
        self.assertNotEqual(updated['analysis']['elements'][1]['description'],'추측')

    def test_crop_missing_core_condition_stays_partial(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))
        raw['analysis']['elements'][1]['status']='unreadable'
        raw['analysis']['coverage']='partial'
        initial=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        class Unverified(Provider):
            def complete(self,payload,**kwargs):
                return {'status':'complete','transcription':'일반적인 설명만 보임',
                        'formulas':[],'description':'',
                        'uncertainDetails':['첫 문장의 조건이 흐려 판독할 수 없음']}
        with patch('pdf_page_study.enhanced_element_image',return_value={'data':'data:image/png;base64,AA==',
                                                        'width':1,'height':1,'bytes':1,'detail':'high'}):
            _,analysis,changed=fused.repair_unreadable_teaching(
                self.folder,self.doc,1,Unverified(),raw,initial,self.folder/'repair')
        self.assertFalse(changed)
        self.assertEqual(analysis['status'],'partial')

    def test_title_only_first_reading_cannot_be_completed_by_fluent_crop(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))
        raw['analysis']['elements'][1]['transcription']='모든 연속함수는 적분이 가능한가?'
        raw['analysis']['elements'][1]['status']='unreadable'
        raw['analysis']['coverage']='partial'
        initial=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        class Fluent(Provider):
            def complete(self,payload,**kwargs):
                return {'status':'complete','transcription':'길고 그럴듯한 추측 문장',
                        'formulas':[],'description':'','uncertainDetails':[]}
        with patch('pdf_page_study.enhanced_element_image',return_value={'data':'data:image/png;base64,AA==',
                                                        'width':1,'height':1,'bytes':1,'detail':'high'}):
            _,analysis,changed=fused.repair_unreadable_teaching(
                self.folder,self.doc,1,Fluent(),raw,initial,self.folder/'repair')
        self.assertFalse(changed)
        self.assertEqual(analysis['status'],'partial')

    def test_old_cached_practice_warning_revalidates_without_api(self):
        self.doc=document(self.folder,1)
        class Practice(Provider):
            def complete(self,payload,**kwargs):
                self.calls.append((payload,kwargs))
                raw=study_response(payload,['contents','problem','solution','decoration'])
                raw['analysis']['elements'][1]['status']='unreadable'
                raw['analysis']['elements'][1]['uncertainDetails']=['연습문제의 흐린 숫자']
                return raw
        provider=Practice()
        first,_,_=fused.request_study(self.folder,self.doc,1,provider,{})
        self.assertEqual(first['status'],'ready')
        old=copy.deepcopy(first)
        old['validationVersion']=3
        old['status']='partial'
        old['issues']=['element:practice:unreadable']
        vision.write_json(vision.cache_path(self.folder,self.doc,1),old)
        calls=len(provider.calls)
        updated,_,changed=fused.request_study(self.folder,self.doc,1,provider,{})
        self.assertTrue(changed)
        self.assertEqual(updated['status'],'ready')
        self.assertEqual(len(provider.calls),calls)

    def test_concept_reuses_its_cited_part_without_losing_unique_note(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))['study']
        first=raw['summary']['parts'][0]
        first['body']='조건, 핵심 수식, 적용 이유를 설명한 단락입니다.'
        first['easyExplanation']='쉽게 풀어 쓴 단락입니다.'
        card=raw['concepts'][0]
        card['explanation']='혼동하기 쉬운 경계 조건을 덧붙입니다.'
        card['easyExplanation']=''
        hydrated=fused.hydrate_concept_explanations(raw)
        self.assertEqual(hydrated['concepts'][0]['explanation'],
                         first['body']+'\n\n혼동하기 쉬운 경계 조건을 덧붙입니다.')
        self.assertEqual(hydrated['concepts'][0]['easyExplanation'],first['easyExplanation'])
        raw['concepts'][0]['explanation']=''
        self.assertEqual(fused.hydrate_concept_explanations(raw)['concepts'][0]['explanation'],
                         first['body'])

    def test_new_cards_keep_independent_prose_when_sharing_summary_evidence(self):
        class IndependentCards(Provider):
            def complete(self, payload, **kwargs):
                raw = super().complete(payload, **kwargs)
                part = raw['study']['summary']['parts'][0]
                part['body'] = '여러 개념을 연결하는 긴 요약 본문이에요.'
                for i, card in enumerate(raw['study']['concepts'][:2]):
                    card['evidence'] = copy.deepcopy(part['evidence'])
                    card['explanation'] = f'개념 {i}에만 해당하는 원리예요.'
                    card['easyExplanation'] = f'개념 {i}의 구체적인 예시예요.'
                return raw
        _, result, _ = fused.request_study(self.folder, self.doc, 1, IndependentCards(), {})
        for i, card in enumerate(result['concepts'][:2]):
            self.assertEqual(card['explanation'], f'개념 {i}에만 해당하는 원리예요.')
            self.assertEqual(card['easyExplanation'], f'개념 {i}의 구체적인 예시예요.')
            self.assertNotIn('긴 요약 본문', card['explanation'])

    def test_concept_uses_first_cited_primary_part(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))['study']
        first=raw['summary']['parts'][0]
        second=raw['summary']['parts'][1]
        first['body']='첫째 설명'
        second['body']='둘째 설명'
        first['coveredElementIds']=['e1']
        second['coveredElementIds']=['e2']
        card=raw['concepts'][0]
        card['evidence']=[{'sourceId':'e2'},{'sourceId':'e1'}]
        card['explanation']='추가 설명'
        self.assertEqual(fused.hydrate_concept_explanations(raw)['concepts'][0]['explanation'],
                         '둘째 설명\n\n추가 설명')

    def test_inline_absolute_value_commands_are_renderable(self):
        content={'summary':{'parts':[{'body':r'\(\lvert x\rvert\)'}]},'concepts':[]}
        ai.clean_generated_display_text(content)
        self.assertEqual(content['summary']['parts'][0]['body'],r'\(|x|\)')

    def test_long_overview_sends_only_titles_once_preserves_sections(self):
        sections=[{'title':f'주제 {i}', 'body':'긴 설명 '*2000,
                   'parts':[{'title':f'조건 {i}','body':'보존할 설명'}],
                   'evidence':[{'sourceId':f'c{i}','quote':'원문','page':i}]} for i in range(1,114)]
        original=copy.deepcopy(sections)
        result=overview(self.provider,self.folder,sections)
        self.assertEqual(len(self.provider.calls),1)
        payload=self.provider.calls[0][0]
        self.assertEqual(len(payload['topics']),113)
        self.assertNotIn('body',json.dumps(payload))
        self.assertNotIn('원문',json.dumps(payload,ensure_ascii=False))
        self.assertEqual(sections,original)
        self.assertEqual(len(result['evidence']),113)

    def test_bounded_overview_never_starts_paid_cascade(self):
        sections=[{'title':'제목','parts':[],'evidence':[]}]*4
        with patch('pdf_outline.MAX_OUTLINE_BYTES',1):
            result=overview(self.provider,self.folder,sections)
        self.assertEqual(len(self.provider.calls),0)
        self.assertEqual(result['overviewMethod'],'local_headings_prose')
        self.assertFalse(result['body'].startswith('- '))

    def test_outline_list_response_becomes_short_prose(self):
        sections=[{'title':f'주제 {i}', 'parts':[], 'evidence':[]} for i in range(3)]
        with patch.object(self.provider, 'complete', return_value={
                'body':'- 주제 0\n- 주제 1\n- 주제 2', 'topicIds':['s0','s1','s2']}):
            result=overview(self.provider,self.folder,sections)
        self.assertEqual(result['overviewMethod'],'local_headings_prose')
        self.assertNotIn('\n-',result['body'])

    def test_invalid_outline_references_do_not_discard_sections(self):
        sections=[{'title':'함수', 'parts':[], 'evidence':[]}]
        with patch.object(self.provider, 'complete', return_value={
                'body':'함수를 살펴봐요.', 'topicIds':['outside']}):
            result=overview(self.provider,self.folder,sections)
        self.assertEqual(result['overviewMethod'],'local_headings_prose')
        self.assertEqual(result['sourceSectionIds'],['s0'])

    def test_partial_inventory_cannot_be_skipped_as_empty(self):
        raw=study_response(fused.page_payload(self.doc,1,{}),['contents','problem','solution','decoration'])
        raw['analysis']['inventory'].append({'key':'missing_teaching','kind':'formula',
                                             'label':'누락된 학습 수식','anchorIds':[],
                                             'role':'teaching'})
        analysis=vision.validate(raw['analysis'],self.doc['pages'][0],vision.key_for(self.doc,1))
        self.assertEqual(analysis['status'],'partial')
        self.assertIsNone(ai.non_teaching_page_result({'pageAnalysis':analysis}))

    def test_unanswered_formula_prompts_under_heading_are_not_study(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))['analysis']
        for entry in raw['inventory']: entry['role']='teaching'
        for index,(entry,element) in enumerate(zip(raw['inventory'],raw['elements'])):
            if index==0:
                element.update(transcription='점화공식',formulas=[],description='소제목')
            else:
                element.update(transcription='예제',formulas=[{'latex':r'\int \sin^n x\,dx',
                                                               'uncertainSymbols':''}],description='문제 식')
        normalized=fused.normalize_reading(raw)
        self.assertEqual([entry['role'] for entry in normalized['inventory']],
                         ['decoration','practice','practice','practice'])
        analysis=vision.validate(normalized,self.doc['pages'][0],vision.key_for(self.doc,1))
        self.assertIsNotNone(ai.non_teaching_page_result({'pageAnalysis':analysis}))

    def test_decoration_only_missing_detail_can_skip_but_missing_study_cannot(self):
        raw=study_response(fused.page_payload(self.doc,1,{}),
                           ['contents','problem','solution','decoration'])['analysis']
        for entry,role in zip(raw['inventory'],['navigation','practice','practice','decoration']):
            entry['role']=role
        raw['inventory'].append({'key':'extra','kind':'decoration','label':'쪽번호',
                                 'anchorIds':[],'role':'decoration'})
        analysis=vision.validate(raw,self.doc['pages'][0],vision.key_for(self.doc,1))
        self.assertEqual(analysis['status'],'ready')
        self.assertTrue(any('decorative_detail_inferred' in warning for warning in analysis['warnings']))
        self.assertIsNotNone(ai.non_teaching_page_result({'pageAnalysis':analysis}))
        analysis['inventory'][-1]['role']='teaching'
        self.assertIsNone(ai.non_teaching_page_result({'pageAnalysis':analysis}))

    def test_literal_null_math_closer_is_repaired_without_changing_evidence(self):
        value={'summary':{'parts':[{'body':'\\(x+1\\u0000\nt는 식입니다.',
                                    'evidence':[{'quote':r'\(x+1\u0000t'}]}]},'concepts':[]}
        ai.clean_generated_display_text(value)
        self.assertEqual(value['summary']['parts'][0]['body'],r'\(x+1\)는 식입니다.')
        self.assertEqual(value['summary']['parts'][0]['evidence'][0]['quote'],r'\(x+1\u0000t')
        self.assertEqual(ai.study_math_issues(value),[])

    def test_bare_tex_in_visible_text_triggers_repair_gate(self):
        value={'summary':{'parts':[{'body':r'\(x+1\)과 \Delta x를 비교합니다.'}]},'concepts':[]}
        self.assertTrue(any('bare_tex' in item for item in ai.study_math_issues(value)))

    def test_corrupt_optional_concept_addition_uses_complete_summary(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))['study']
        raw['concepts'][0]['explanation']='\x08igl(A) 설명'
        hydrated=fused.hydrate_concept_explanations(raw)
        self.assertEqual(hydrated['concepts'][0]['explanation'],raw['summary']['parts'][0]['body'])

    def test_unrepairable_control_in_primary_explanation_is_rejected(self):
        raw=study_response(fused.page_payload(self.doc,1,{}))['study']
        raw['summary']['parts'][0]['body']='식 \x08igl(A)'
        self.assertTrue(ai.study_unrepairable_controls(raw))

    def test_known_math_control_and_span_artifacts_are_repaired(self):
        value={'summary':{'parts':[{'body':'폭은 \x05\\Delta x\x05이고 '
                                           '\x1cspan\x1e\\(n\\)\x1c/span\x1e개입니다.'}]}}
        self.assertEqual(ai.study_unrepairable_controls(value),[])
        ai.clean_generated_display_text(value)
        self.assertEqual(value['summary']['parts'][0]['body'],
                         r'폭은 \(\Delta x\)이고 \(n\)개입니다.')
        self.assertEqual(ai.study_math_issues(value),[])

    def test_ansi_highlighted_math_keeps_inline_delimiters(self):
        value={'summary':{'parts':[{'body':'두 변수는 \x1b[1mu=sec^3x\x1b[0m, '
                                          '\x1b[1mdv=sec^2x\\,dx\x1b[0m입니다.'}]}}
        ai.clean_generated_display_text(value)
        self.assertEqual(value['summary']['parts'][0]['body'],
                         r'두 변수는 \(u=sec^3x\), \(dv=sec^2x\,dx\)입니다.')
        self.assertEqual(ai.study_math_issues(value),[])

    def test_literal_escaped_paragraph_break_is_not_visible_tex(self):
        value={'concepts':[{'explanation':r'첫 단락입니다.\n\n둘째 단락입니다.'}]}
        ai.clean_generated_display_text(value)
        self.assertEqual(value['concepts'][0]['explanation'],'첫 단락입니다.\n\n둘째 단락입니다.')
        self.assertEqual(ai.study_math_issues(value),[])

if __name__=='__main__':unittest.main()
