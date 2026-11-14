"""Offline page-vision contract tests. No keys, OCR, or external transport."""
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

from pypdf import PdfWriter
import pdf_page_analysis as vision
from pdf_ai import Provider, AiResponseError, adjacent_page_context, generation, non_teaching_page_result, reconcile_non_teaching_pages, recover_generation, review_evidence
from pdf_pipeline import enrich_visual_routing, retrieve
from pdf_slide_lens import candidates
from pdf_study_policy import _page_texts
from test_pdf_generation_context import answer


def document(folder, count=3):
    writer=PdfWriter()
    for n in range(count):
        p=writer.add_blank_page(width=300,height=200)
        if n==1:p.rotate(90)
    writer.write(folder/'source.pdf')
    return {'documentId':'synthetic','fingerprint':'test','incompletePages':[], 'chunks':[],
        'pages':[{'number':n,'nativeText':f'context {n}', 'markdown':f'context {n}',
            'textRegions':[{'bbox':[.1,.1,.8,.2],'text':f'context {n}'}],
            'imageRegions':[{'bbox':[.1,.5,.2,.6]} for _ in range(12 if n==1 else 0)]}
            for n in range(1,count+1)]}


def response(payload):
    kinds=['table','formula','diagram','example']
    inventory=[{'key':str(i),'kind':kind,'label':kind,'anchorIds':
        [a['id'] for a in payload.get('anchors',[])] if i==0 else []} for i,kind in enumerate(kinds)]
    elements=[{'key':str(i),'kind':kind,'title':kind,'bbox':[.1,.1,.9,.9],
        'transcription':f'{kind} on page {payload.get("page",1)}','formulas':
            [{'latex':r'E=\frac{1}{2}I\omega^2','uncertainSymbols':''}] if kind=='formula' else [],
        'description':'visible relationship','relationships':['nodes connected'], 'purpose':'contextual inference',
        'uncertainDetails':[],'status':'complete','lensReason':'diagram_relation'} for i,kind in enumerate(kinds)]
    return {'inventory':inventory,'elements':elements,'coverage':'complete','contextSummary':f'context {payload.get("page",1)}'}


def classified_response(payload):
    kinds={1:['contents'],2:['example'],3:['problem','solution']}[payload['page']]
    inventory=[{'key':str(i),'kind':kind,'label':kind,
                'anchorIds':[a['id'] for a in payload['anchors']] if i==0 else []}
               for i,kind in enumerate(kinds)]
    elements=[{'key':str(i),'kind':kind,'title':kind,'bbox':[.1,.1,.9,.9],
               'transcription':f'{kind} content','formulas':[], 'description':f'{kind} description',
               'relationships':[], 'purpose':'', 'uncertainDetails':[], 'status':'complete'}
              for i,kind in enumerate(kinds)]
    return {'inventory':inventory,'elements':elements,'coverage':'complete','contextSummary':'classified'}


class FakeProvider:
    model='gpt-6-luna'
    def __init__(self):self.calls=[];self.context={}
    def complete(self,payload,**kwargs):
        self.calls.append((copy.deepcopy(payload),kwargs))
        return response(payload) if kwargs.get('image') else answer(payload)


class PageAnalysisTests(unittest.TestCase):
    def test_required_elements_ignores_layout_only_heading(self):
        unit = [
            {'id': 'heading-source', 'elementId': 'heading', 'elementTitle': 'Function',
             'elementKind': 'text', 'source': 'ai_visual_observation',
             'text': 'Slide title heading at the upper left.', 'formulas': []},
            {'id': 'diagram-source', 'elementId': 'mechanism', 'elementTitle': 'Function call',
             'elementKind': 'diagram', 'source': 'ai_visual_observation',
             'text': 'The diagram explains the call and return relation.', 'formulas': []},
        ]
        self.assertEqual([item['elementId'] for item in vision.required_elements(unit)],
                         ['mechanism'])

    def setUp(self):
        self.legacy = patch("pdf_ai.FUSED_PAGES", False)
        self.legacy.start(); self.addCleanup(self.legacy.stop)
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.doc=document(self.folder);self.provider=FakeProvider()
        self.quiet=contextlib.redirect_stdout(io.StringIO());self.quiet.__enter__()
    def tearDown(self):self.quiet.__exit__(None,None,None);self.temp.cleanup()

    def test_fragments_text_only_repeated_educational_elements_one_request_per_page(self):
        vision.analyze_pages(self.folder,self.doc,self.provider)
        self.assertEqual(len(self.provider.calls),3)
        self.assertEqual(sorted(c[0]['page'] for c in self.provider.calls),[1,2,3])
        for page in self.doc['pages']:
            self.assertEqual(len(page['pageAnalysis']['elements']),4)
            self.assertEqual(page['pageAnalysis']['status'],'ready')
        third=next(c[0] for c in self.provider.calls if c[0]['page']==3)
        self.assertEqual(third['previousContext'][1]['nativeText'],'context 2')
        self.assertEqual(third['previousContext'][1]['analysis'],'')
        self.assertNotEqual(self.doc['pages'][0]['pageAnalysis']['elements'][0]['elementId'],
                            self.doc['pages'][1]['pageAnalysis']['elements'][0]['elementId'])
        vision.analyze_pages(self.folder,self.doc,self.provider)
        self.assertEqual(len(self.provider.calls),3)
        self.assertEqual(vision.plan(self.folder,self.doc)['pending'],0)

    def test_ten_visual_requests_run_together_and_slide_states_distinguish_partial(self):
        self.doc=document(self.folder,12)
        vision.hydrate(self.folder,self.doc)
        self.assertTrue(all(state['state']=='pending' and state['analyzed']==0
                            for state in self.doc['pageAnalysisStates']))
        barrier=threading.Barrier(10)
        active=peak=0
        lock=threading.Lock()

        class ParallelProvider(FakeProvider):
            def complete(self,payload,**kwargs):
                nonlocal active,peak
                if kwargs.get('image'):
                    with lock:
                        active+=1;peak=max(peak,active)
                    if payload['page']<=10:barrier.wait(timeout=5)
                    value=response(payload)
                    if payload['page']==12:value['elements'].pop()
                    with lock:active-=1
                    return value
                return answer(payload)

        image={'data':'data:image/png;base64,dGVzdA==','width':300,'height':200,'bytes':4}
        with patch('pdf_page_analysis.render_page',return_value=image):
            vision.analyze_pages(self.folder,self.doc,ParallelProvider())
        self.assertEqual(peak,10)
        self.assertEqual(len(self.doc['pageAnalysisStates']),12)
        self.assertTrue(all(state['analyzed']==1 and state['complete']==1
                            for state in self.doc['pageAnalysisStates'][:11]))
        self.assertEqual(self.doc['pageAnalysisStates'][11]['state'],'partial')
        self.assertEqual(self.doc['pageAnalysisStates'][11]['complete'],0)
        self.assertEqual(self.doc['pageAnalysisIncompletePages'],[12])

    def test_prompt_change_does_not_turn_stored_reading_into_pending(self):
        page=self.doc['pages'][0]
        page['pageAnalysis']={'version':vision.VERSION,'documentId':self.doc['documentId'],
                              'page':1,'inputKey':'older-prompt-key','status':'ready'}
        self.assertEqual(vision.analysis_states(self.doc)[0]['state'],'ready')
        page['pageAnalysis']['documentId']='other-document'
        self.assertEqual(vision.analysis_states(self.doc)[0]['state'],'pending')

    def test_plan_flags_uncertain_paid_page_before_retry(self):
        vision.write_json(self.folder/'usage/previous.json', {
            'model':'gpt-6-luna', 'requests':[{'kind':'page_visual', 'page':2,
                'pageKey':vision.key_for(self.doc,2), 'state':'reserved'}]})
        result=vision.plan(self.folder,self.doc)
        self.assertEqual(result['uncertainPreviousPages'],[2])
        self.assertEqual(result['pending'],3)

    def test_partial_previous_visual_context_is_marked_as_partial(self):
        self.doc['pages'][0]['pageAnalysis']={'status':'partial','contextSummary':'uncertain diagram'}
        context=adjacent_page_context(self.doc,2)
        self.assertEqual(context[0]['visualContextSummary'],'uncertain diagram')
        self.assertEqual(context[0]['visualContextStatus'],'partial')

    def test_inventory_omissions_general_unlabeled_and_missing_anchors(self):
        page=self.doc['pages'][0];value=response({'anchors':vision.anchors(page)})
        value['elements'].pop(2)
        result=vision.validate(value,page,'key');self.assertEqual(result['status'],'partial')
        self.assertIn('inventory:2:missing',result['issues'])
        value['inventory'][0]['anchorIds']=[]
        self.assertIn('anchor:t0:missing',vision.validate(value,page,'key')['issues'])
        self.assertEqual(vision.validate({'inventory':[],'elements':[],'coverage':'complete','contextSummary':''},
                                        {'number':1},'key')['status'],'partial')

    def test_numbered_footer_kind_disagreement_preserves_entire_page(self):
        page=self.doc['pages'][0]
        value=response({'anchors':vision.anchors(page)})
        value['inventory'].append({'key':'footer','kind':'text','label':'page number','anchorIds':[]})
        value['elements'].append({'key':'footer','kind':'decoration','title':'page number',
            'bbox':[.48,.93,.52,.96],'transcription':'33','formulas':[],
            'description':'printed footer number','relationships':[],'purpose':'navigation',
            'uncertainDetails':[],'status':'complete'})
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'ready')
        self.assertEqual(len(result['elements']),5)
        self.assertEqual(result['elements'][-1]['kind'],'decoration')
        self.assertEqual(result['inventory'][-1]['kind'],'decoration')
        self.assertEqual(value['inventory'][-1]['kind'],'text')  # paid response stays immutable

    def test_substantive_kind_disagreement_is_partial_without_losing_other_elements(self):
        page=self.doc['pages'][0]
        value=response({'anchors':vision.anchors(page)})
        value['elements'][1]['kind']='table'
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'partial')
        self.assertEqual(len(result['elements']),4)
        self.assertIn('inventory:1:kind_mismatch',result['issues'])

    def test_code_example_classification_and_complete_notes_are_not_failures(self):
        page=self.doc['pages'][0]
        value=response({'anchors':vision.anchors(page)})
        value['inventory'][3]['kind']='code'
        value['elements'][0]['uncertainDetails']=['표의 한 글리프는 원본 모양 그대로 기록함']
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['elements'][3]['kind'],'code')
        value['elements'][0]['status']='unreadable'
        self.assertEqual(vision.validate(value,page,'key')['status'],'partial')

    def test_short_axis_label_can_join_one_described_diagram(self):
        page={'number':8,'textRegions':[{'bbox':[.078,.415,.366,.449],'text':'0 y'}]}
        value=response({})
        value['elements'][2]['bbox']=[.036,.177,.268,.363]
        value['elements'][2]['description']='원점은 0으로 표시되며 y축은 위쪽을 향한다.'
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['elements'][2]['anchorIds'],['t0'])
        page['textRegions'][0]['text']='A missing definition of inertia'
        self.assertIn('anchor:t0:missing',vision.validate(value,page,'key')['issues'])

    def test_extracted_formula_fragment_inside_read_visual_is_warning(self):
        page={'number':8,'textRegions':[{'bbox':[.3,.3,.55,.32],'text':'∫ / + 2'}]}
        value=response({})
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'ready')
        self.assertIn('anchor:t0:missing',result['warnings'])
        page['textRegions'][0]['text']='누락된 핵심 정의입니다'
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'partial')
        self.assertIn('anchor:t0:missing',result['issues'])

    def test_unreadable_practice_does_not_mark_read_teaching_partial(self):
        page={'number':1}
        value=response({})
        value['inventory'][2]['kind']='problem'
        value['elements'][2]['kind']='problem'
        value['elements'][2]['status']='unreadable'
        value['coverage']='partial'
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'ready')
        self.assertIn('practice_or_navigation_unreadable',result['warnings'])
        value['elements'][1]['status']='unreadable'
        self.assertEqual(vision.validate(value,page,'key')['status'],'partial')

    def test_short_parenthesized_method_label_is_not_missing_the_method(self):
        page={'number':1,'textRegions':[{'bbox':[.07,.58,.21,.60],
                                         'text':'(다른 풀이)'}]}
        value=response({})
        value['elements'][1]['bbox']=[.06,.61,.8,.85]
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'ready')
        self.assertIn('anchor:t0:missing',result['warnings'])

    def test_one_malformed_element_does_not_erase_other_diagrams(self):
        page=self.doc['pages'][0]
        value=response({'anchors':vision.anchors(page)})
        value['elements'][0]['formulas']='invalid'
        result=vision.validate(value,page,'key')
        self.assertEqual(result['status'],'partial')
        self.assertEqual(len(result['elements']),3)
        self.assertIn('element:0:invalid_formulas',result['issues'])
        self.assertIn('inventory:0:missing',result['issues'])
        self.assertTrue(any(e['kind']=='diagram' for e in result['elements']))

    def test_cached_kind_failure_revalidates_only_paid_response(self):
        page=self.doc['pages'][0]
        key=vision.key_for(self.doc,1)
        old={'version':vision.VERSION,'inputKey':key,'page':1,'status':'partial',
             'inventory':[],'elements':[],'contextSummary':'',
             'issues':['요소 종류가 목록과 일치하지 않습니다.']}
        vision.write_json(vision.cache_path(self.folder,self.doc,1),old)
        calls=[]
        class CachedProvider(FakeProvider):
            def complete(self,payload,**kwargs):
                calls.append(kwargs.get('cache_only'))
                value=response(payload)
                value['inventory'].append({'key':'footer','kind':'text','label':'page number','anchorIds':[]})
                value['elements'].append({'key':'footer','kind':'decoration','title':'page number',
                    'bbox':[.48,.93,.52,.96],'transcription':'33','formulas':[],
                    'description':'printed footer number','relationships':[],'purpose':'navigation',
                    'uncertainDetails':[],'status':'complete'})
                return value
        image={'data':'data:image/png;base64,dGVzdA==','width':300,'height':200,'bytes':4}
        with patch('pdf_page_analysis.render_page',return_value=image):
            repaired,newly_analyzed,_=vision.request_page(self.folder,self.doc,1,CachedProvider())
        self.assertEqual(calls,[True])
        self.assertTrue(newly_analyzed)
        self.assertEqual(repaired['status'],'ready')
        self.assertEqual(len(repaired['elements']),5)

    def test_cached_kind_failure_without_paid_response_is_preserved(self):
        key=vision.key_for(self.doc,1)
        old={'version':vision.VERSION,'inputKey':key,'page':1,'status':'partial',
             'inventory':[],'elements':[],'contextSummary':'',
             'issues':['요소 종류가 목록과 일치하지 않습니다.']}
        vision.write_json(vision.cache_path(self.folder,self.doc,1),old)
        class NoPaidResponse(FakeProvider):
            def complete(self,payload,**kwargs):
                self.assert_cache_only=kwargs.get('cache_only')
                raise AiResponseError('cache miss')
        provider=NoPaidResponse()
        image={'data':'data:image/png;base64,dGVzdA==','width':300,'height':200,'bytes':4}
        with patch('pdf_page_analysis.render_page',return_value=image):
            recovered,newly_analyzed,_=vision.request_page(self.folder,self.doc,1,provider)
        self.assertEqual(recovered,old)
        self.assertFalse(newly_analyzed)
        self.assertTrue(provider.assert_cache_only)

    def test_previous_complete_study_result_remains_viewable_after_prompt_revision(self):
        self.doc['pageAnalysisVersion']=vision.VERSION
        targets=[1,2,3]
        legacy=vision.summary_cache(self.folder,self.doc,'gpt-6-luna','document',0,targets,
                                    'pdf-grounded-ko-v38')
        vision.write_json(legacy/'result.json',{'kind':'ai_generated','promptVersion':'pdf-grounded-ko-v38',
            'sections':[],'concepts':[],'overview':{'title':'old','body':'stored study result','evidence':[]}})
        recovered=recover_generation(self.folder,self.doc)
        self.assertEqual(recovered['overview']['body'],'stored study result')

    def test_page_prompt_omits_slide_lens_and_accepts_elements_without_lens_reason(self):
        self.assertNotIn('SlideLens', vision.SYSTEM)
        self.assertNotIn('lensReason', vision.SYSTEM)
        self.assertNotIn('lens', vision.SUMMARY_POLICY.lower())
        self.assertIn('kind=contents', vision.SYSTEM)
        self.assertIn('standalone practice', vision.SYSTEM)
        value=response({'anchors':vision.anchors(self.doc['pages'][0])})
        for element in value['elements']:
            element.pop('lensReason')
        result=vision.validate(value,self.doc['pages'][0],'key')
        self.assertEqual(result['status'],'ready')
        self.assertTrue(all(element['lensReason']=='none' for element in result['elements']))

    def test_contents_and_practice_do_not_return_through_coverage_recovery(self):
        kinds=('example','contents','problem','solution','text')
        chunks=[{'id':f'source-{i}', 'page':1, 'elementId':f'element-{i}',
                 'elementTitle':kind, 'elementKind':kind, 'text':f'{kind} content',
                 'formulas':[]} for i,kind in enumerate(kinds)]
        self.assertEqual([item['elementId'] for item in vision.required_elements(chunks)],
                         ['element-4'])
        summary={'title':'개념', 'body':'설명 예제', 'excludedElementIds':['element-4'],
                 'parts':[{'body':'설명 예제', 'coveredElementIds':['element-0'],
                           'evidence':[{'sourceId':'source-0','page':1}], 'visualPages':[]}]}
        vision.preserve_summary_elements(summary,chunks,review_evidence)
        self.assertEqual(summary.get('coverageUnverifiedElementIds',[]),[])
        self.assertEqual(len(summary['parts']),1)
        self.assertNotIn('contents content',summary['body'])
        self.assertNotIn('problem content',summary['body'])

    def test_slide_heading_is_not_required_study_content(self):
        chunks = [
            {'id': 'heading-text', 'page': 1, 'elementId': 'heading', 'elementTitle': '메뉴 선택 방식',
             'elementKind': 'text', 'source': 'ai_transcription', 'text': '메뉴 선택 방식', 'formulas': []},
            {'id': 'heading-note', 'page': 1, 'elementId': 'heading', 'elementTitle': '메뉴 선택 방식',
             'elementKind': 'text', 'source': 'ai_visual_observation',
             'text': '페이지 상단의 강의 주제 제목이다.', 'formulas': []},
            {'id': 'teaching', 'page': 1, 'elementId': 'lesson', 'elementTitle': '입력 검증',
             'elementKind': 'text', 'source': 'ai_transcription',
             'text': 'scanf 결과를 검사한다', 'formulas': []},
        ]
        self.assertEqual([item['elementId'] for item in vision.required_elements(chunks)], ['lesson'])

    def test_repeated_three_stage_flow_uses_existing_cited_summary(self):
        chunks = [
            {'id': 'flow-note', 'page': 4, 'elementId': 'steps', 'elementTitle': '입력 과정',
             'elementKind': 'text', 'source': 'ai_visual_observation',
             'text': '입력 → 버퍼 → 프로그램 흐름을 단계로 풀어 쓴다.', 'formulas': []},
            {'id': 'flow-text', 'page': 4, 'elementId': 'steps', 'elementTitle': '입력 과정',
             'elementKind': 'text', 'source': 'ai_transcription',
             'text': '1. 키보드 입력\n2. 버퍼에 저장\n3. 프로그램이 읽음', 'formulas': []},
            {'id': 'buffer-text', 'page': 4, 'elementId': 'buffer', 'elementTitle': '버퍼 입력',
             'elementKind': 'text', 'source': 'ai_transcription',
             'text': '입력 → 버퍼 → 프로그램', 'formulas': []},
        ]
        summary = {'parts': [{'title': '버퍼 입력', 'body': '입력 → 버퍼 → 프로그램 순서로 전달됩니다.',
            'coveredElementIds': ['buffer'], 'evidence': [{'sourceId': 'buffer-text', 'page': 4}],
            'visualPages': []}]}
        vision.preserve_summary_elements(summary, chunks, review_evidence)
        self.assertEqual(summary['coverageUnverifiedElementIds'], [])
        self.assertIn('steps', summary['parts'][0]['coveredElementIds'])
        summary['parts'][0]['body'] = '버퍼가 필요합니다.'
        summary['parts'][0]['coveredElementIds'].remove('steps')
        vision.preserve_summary_elements(summary, chunks, review_evidence)
        self.assertIn('steps', summary['coverageUnverifiedElementIds'])

    def test_formula_id_never_forces_lens_but_diagram_survives(self):
        vision.analyze_page(self.folder,self.doc,1,self.provider)
        regions=candidates(self.doc,[1]);self.assertTrue(any(r['kind']=='diagram' for r in regions))
        self.assertFalse(any(r['kind']=='formula' for r in regions))
        formula=next(c for c in self.doc['chunks'] if c.get('formulas'))
        self.assertIn('$$',formula['text'])

    def test_summary_omission_does_not_append_source_derivation(self):
        vision.analyze_page(self.folder,self.doc,1,self.provider)
        chunks=self.doc['chunks'];formula=next(c for c in chunks if c.get('formulas'))
        evidence,_=review_evidence([{'sourceId':formula['id'],'quote':formula['text'][:20]}],{c['id']:c for c in chunks})
        summary={'parts':[{'body':'formula discussed here','coveredElementIds':[formula['elementId']], 'evidence':evidence}]}
        vision.preserve_summary_elements(summary,chunks,review_evidence)
        self.assertNotIn(r'E=\frac{1}{2}I\omega^2',summary['parts'][0]['body'])
        self.assertEqual(len(summary['coverageUnverifiedElementIds']),2)
        self.assertTrue(summary['contentIncomplete'])
        self.assertEqual(len(summary['parts']),1)
        self.assertNotIn('요약 반영 확인 필요',summary['body'])

    def test_uncertain_symbols_not_silently_completed(self):
        value=response({});value['elements'][1]['formulas'][0]['uncertainSymbols']='subscript unclear'
        result=vision.validate(value,{'number':1},'key')
        self.assertEqual(result['status'],'ready')
        self.assertTrue(any('formula_uncertain' in warning for warning in result['warnings']))
        self.assertIn('판독 확인 필요',vision.element_text(result['elements'][1]))

    def test_bounds_nan_inverted_and_fullpage_fallback(self):
        for box in (None,[0,0,float('nan'),1],[.8,.2,.1,.4],[-.1,0,1,1],[True,0,1,1]):
            self.assertEqual(vision.padded_box(box),([0.,0.,1.,1.],'full_page'))
        self.assertEqual(vision.padded_box([0,.005,.995,1])[0],[0.,0.,1.,1.])
        a=vision.validate(response({}),{'number':1},'stable')
        v=response({});v['elements'][0]['bbox']=[.2,.2,.6,.6]
        b=vision.validate(v,{'number':1},'stable')
        self.assertEqual(a['elements'][0]['elementId'],b['elements'][0]['elementId'])

    def test_refine_boundary_includes_clipped_label_not_background_or_distant_neighbor(self):
        box=[.12,.71,.86,.79]
        label={'bbox':[.65,.76,.887,.792]}
        self.assertGreater(vision.refine_box(box,[label])[2],.887)
        self.assertEqual(vision.refine_box(box,[{'bbox':[0,0,1,1]},{'bbox':[.85,.7,.97,.8]}]),box)
        self.assertTrue(vision.frame_compatible(self.folder,1))
        self.assertFalse(vision.frame_compatible(self.folder,2))

    def test_native_citation_of_same_anchor_does_not_duplicate_element(self):
        self.doc['chunks']=[{'id':'native1','documentId':'synthetic','page':1,'source':'native','text':'context 1',
                            'field':'markdown','start':0,'end':9,'bbox':None}]
        vision.analyze_page(self.folder,self.doc,1,self.provider)
        chunk=next(c for c in self.doc['chunks'] if c.get('elementId'))
        self.assertEqual(chunk['nativeSupportSourceIds'],['native1'])
        summary={'parts':[{'body':'covered','coveredElementIds':[chunk['elementId']],
                           'evidence':[{'sourceId':'native1'}]}]}
        vision.preserve_summary_elements(summary,self.doc['chunks'],review_evidence)
        self.assertNotIn(chunk['elementId'],summary['coverageUnverifiedElementIds'])

    def test_render_rotation_full_composite_and_limit(self):
        a=vision.render_page(self.folder,1);b=vision.render_page(self.folder,2)
        self.assertEqual((a['width'],a['height']),(b['height'],b['width']))
        self.assertLessEqual(max(a['width'],a['height']),vision.MAX_SIDE)

    def test_legacy_ocr_not_in_search_context_or_new_sources(self):
        self.doc['pages'][0]['ocrBlocks']=[{'text':'SECRET_OCR_ONLY'}]
        self.doc['chunks']=[{'id':'ocr','page':1,'source':'ocr','text':'SECRET_OCR_ONLY'}]
        self.assertEqual(retrieve(self.doc,'SECRET_OCR_ONLY'),[])
        self.assertNotIn('SECRET_OCR_ONLY',json.dumps(_page_texts(self.doc)))
        enrich_visual_routing(self.doc)
        vision.analyze_page(self.folder,self.doc,1,self.provider)
        self.assertNotIn('SECRET_OCR_ONLY',json.dumps(self.provider.calls))

    def test_invalid_paid_json_is_preserved_and_no_automatic_rebill(self):
        calls=[]
        def transport(body):
            calls.append(body)
            return {'choices':[{'finish_reason':'stop','message':{'content':'{invalid'}}],
                    'usage':{'prompt_tokens':2,'completion_tokens':2}}
        provider=Provider(self.folder,True,1,'gpt-6-luna',transport)
        r=vision.analyze_page(self.folder,self.doc,1,provider)
        self.assertEqual(r['status'],'partial')
        vision.analyze_page(self.folder,self.doc,1,provider)
        self.assertEqual(len(calls),1)
        self.assertEqual(vision.plan(self.folder,self.doc,[.1,.5],[1])['partial'],1)
        self.assertEqual(len(list((self.folder/'generated/paid-responses').glob('*.raw.json'))),1)

    def test_cancel_resume_and_previous_context_limit(self):
        vision.analyze_page(self.folder,self.doc,1,self.provider)
        (self.folder/'cancel').write_text('cancel')
        with self.assertRaises(InterruptedError):vision.analyze_pages(self.folder,self.doc,self.provider)
        (self.folder/'cancel').unlink()
        vision.analyze_pages(self.folder,self.doc,self.provider)
        self.assertEqual(len(self.provider.calls),3)
        for invalid in ([],[0],[True],[4],['1']):
            with self.assertRaises(ValueError):vision.plan(self.folder,self.doc,pages=invalid)

    def test_selected_later_page_sends_only_that_image_and_previous_three_texts(self):
        self.doc=document(self.folder,6)
        vision.analyze_pages(self.folder,self.doc,self.provider,[6])
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual([p['page'] for p in self.provider.calls[0][0]['previousContext']],[3,4,5])
        self.assertTrue(all(p['status']=='native_only' for p in self.provider.calls[0][0]['previousContext']))

    def test_truncated_response_cached_without_second_send(self):
        calls=[]
        def transport(body):
            calls.append(body)
            return {'choices':[{'finish_reason':'length','message':{'content':'{"inventory":'}}],
                    'usage':{'prompt_tokens':4,'completion_tokens':4}}
        provider=Provider(self.folder,True,1,'gpt-6-luna',transport)
        self.assertEqual(vision.analyze_page(self.folder,self.doc,1,provider)['status'],'partial')
        vision.analyze_page(self.folder,self.doc,1,provider)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(list((self.folder/'generated/paid-responses').glob('*.incomplete.json'))),1)

    def test_pipeline_streams_each_page_and_resumes_without_new_vision(self):
        events=[]
        with patch('pdf_ai.emit',side_effect=lambda kind,**args:events.append((kind,args))):
            result=generation(self.folder,self.doc,self.provider,page_mode=True)
        self.assertEqual(len([c for c in self.provider.calls if c[1].get('image')]),3)
        self.assertEqual(len([e for e in events if e[0]=='summary_unit_ready']),3)
        calls=len(self.provider.calls)
        self.assertEqual(generation(self.folder,self.doc,self.provider,page_mode=True),result)
        self.assertEqual(len(self.provider.calls),calls)
        for cache in (self.folder/'generated').glob('*/result.json'):cache.unlink()
        recovered=recover_generation(self.folder,self.doc)
        self.assertEqual(recovered['partialUnits'],3)
        generation(self.folder,self.doc,self.provider,page_mode=True)
        self.assertEqual(len(self.provider.calls),calls)

    def test_only_excluded_pages_skip_paid_summaries_but_keep_teaching_example(self):
        class SelectiveProvider(FakeProvider):
            def complete(self,payload,**kwargs):
                self.calls.append((copy.deepcopy(payload),kwargs))
                return classified_response(payload) if kwargs.get('image') else answer(payload)

        provider=SelectiveProvider()
        result=generation(self.folder,self.doc,provider,page_mode=True)
        visual=[c for c in provider.calls if c[1].get('image')]
        summaries=[c for c in provider.calls if 'sources' in c[0]]
        self.assertEqual(len(visual),3)
        self.assertEqual([c[0]['sources'][0]['page'] for c in summaries],[2])
        self.assertEqual(len(result['sections']),1)
        self.assertEqual(result['skippedStudyPages'],[1,3])
        self.assertEqual(result['sections'][0]['evidence'][0]['page'],2)
        cache=next(path for path in (self.folder/'generated').iterdir()
                   if path.is_dir() and (path/'result.json').exists())
        for index in (0,2):
            saved=json.loads((cache/f'unit-{index:05}.json').read_text(encoding='utf-8'))
            self.assertTrue(saved['summary']['studyContentSkipped'])
            self.assertEqual(saved['concepts'],[])

    def test_single_excluded_page_skips_serial_summary(self):
        self.doc=document(self.folder,1)
        class ContentsProvider(FakeProvider):
            def complete(self,payload,**kwargs):
                self.calls.append((copy.deepcopy(payload),kwargs))
                return classified_response(payload) if kwargs.get('image') else answer(payload)

        provider=ContentsProvider()
        result=generation(self.folder,self.doc,provider,page_mode=True)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(result['sections'],[])
        self.assertEqual(result['skippedStudyPages'],[1])
        self.assertEqual(result['overview']['title'],'학습 내용 없음')

    def test_incomplete_or_mixed_page_never_skips_summary(self):
        excluded={'kind':'problem','elementId':'e1'}
        teaching={'kind':'text','elementId':'e2'}
        self.assertIsNone(non_teaching_page_result({'pageAnalysis':{
            'status':'partial','elements':[excluded]}}))
        self.assertIsNone(non_teaching_page_result({'pageAnalysis':{
            'status':'ready','elements':[excluded,teaching]}}))

    def test_chapter_contents_and_standalone_practice_skip_without_flagging_learning(self):
        heading={'kind':'text','elementId':'heading','title':'이차원 운동','description':'페이지 상단의 제목','transcription':''}
        contents={'kind':'contents','elementId':'contents','title':'학습 주제','description':''}
        page={'markdown':'4장\n이차원 운동\n• 포물체 운동','pageAnalysis':{'status':'ready','elements':[heading,contents]}}
        self.assertTrue(non_teaching_page_result(page)['summary']['studyContentSkipped'])
        worked={'kind':'example','elementId':'example','title':'예제 2','description':'조건과 문항'}
        solution={'kind':'formula','elementId':'calculation','title':'(a) 풀이','description':'값을 계산'}
        page={'markdown':'포물체 운동\n예제 2. 멀리뛰기 선수의 도달 거리를 구하라.',
              'pageAnalysis':{'status':'partial','elements':[heading,worked,solution]}}
        self.assertIsNone(non_teaching_page_result(page))
        page['pageAnalysis']['elements'].append({'kind':'text','elementId':'definition',
            'title':'포물체 운동의 정의','description':'성분별 운동을 설명한다','transcription':'독립된 개념 설명'})
        self.assertIsNone(non_teaching_page_result(page))

    def test_bare_example_prompts_are_not_missing_study_content(self):
        prompt={'kind':'example','elementId':'e1','title':'적분 예제',
                'transcription':'예제 ∫ x sin x dx',
                'description':'적분식만 제시되어 있고 풀이 단계는 보이지 않는다.'}
        analysis={'status':'ready','inventory':[{'key':'e1','role':'teaching'}],
                  'elements':[prompt]}
        result=non_teaching_page_result({'pageAnalysis':analysis})
        self.assertTrue(result['summary']['studyContentSkipped'])
        analysis['inventory'].append({'key':'e2','role':'teaching'})
        analysis['elements'].append({'kind':'text','elementId':'e2','title':'부분적분 원리',
                                     'transcription':'부분적분 공식을 설명한다.'})
        self.assertIsNone(non_teaching_page_result({'pageAnalysis':analysis}))
        report={'incompleteStudyPages':[3], 'skippedStudyPages':[]}
        document={'pages':[{}, {}, {'pageAnalysis':{'status':'ready',
            'inventory':[{'key':'e1','role':'teaching'}], 'elements':[prompt]}}]}
        reconcile_non_teaching_pages(report,document)
        self.assertEqual(report['incompleteStudyPages'],[])
        self.assertEqual(report['skippedStudyPages'],[3])

    def test_course_cover_skips_but_text_concept_page_does_not(self):
        cover={'number':1,'nativeText':'Introduction to Programming\nC++ Basics\nInstructor (name@example.edu)',
            'pageAnalysis':{'status':'ready','elements':[
                {'kind':'text','elementId':'e1','title':'강의 제목','description':'과목 이름'},
                {'kind':'text','elementId':'e2','title':'강의 주제','description':'부제'},
                {'kind':'text','elementId':'e3','title':'강사명 및 이메일','description':'연락처'},
                {'kind':'decoration','elementId':'e4','title':'로고','description':''}]}}
        skipped=non_teaching_page_result(cover)
        self.assertTrue(skipped['summary']['studyContentSkipped'])
        self.assertEqual(skipped['concepts'],[])
        concept=copy.deepcopy(cover)
        concept['pageAnalysis']['elements'].append({'kind':'text','elementId':'e5',
            'title':'함수 정의','description':'반환값과 매개변수의 관계를 설명한다'})
        self.assertIsNone(non_teaching_page_result(concept))

    def test_lecturer_label_on_cover_is_not_a_study_section(self):
        cover={'number':1,'nativeText':'Introduction to Programming (2)\nC++ Basics - 2\nLaihyuk Park (lhpark@seoultech.ac.kr)',
            'pageAnalysis':{'status':'ready','elements':[
                {'kind':'text','elementId':'e1','title':'강의 제목','description':'페이지 중앙의 강의 제목'},
                {'kind':'text','elementId':'e2','title':'강의 부제','description':'강의 제목 아래 부제목'},
                {'kind':'text','elementId':'e3','title':'강의자','description':'강의자 이름과 이메일 주소'},
                {'kind':'decoration','elementId':'e4','title':'로고','description':'대학 심볼'}]}}
        self.assertTrue(non_teaching_page_result(cover)['summary']['studyContentSkipped'])

    def test_parallel_summary_uses_only_previous_page_and_preserves_page_order(self):
        active = 0
        maximum = 0
        lock = threading.Lock()
        calls = []

        class SlowProvider(FakeProvider):
            def complete(self, payload, **kwargs):
                nonlocal active, maximum
                if kwargs.get('image'):
                    return response(payload)
                if 'sources' not in payload:
                    return answer(payload)
                page = payload['sources'][0]['page']
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                    calls.append((page, copy.deepcopy(payload)))
                time.sleep({1:.09, 2:.04, 3:.01}[page])
                with lock:
                    active -= 1
                return answer(payload)

        provider = SlowProvider()
        events = []
        with patch('pdf_ai.emit', side_effect=lambda kind, **args: events.append((kind,args))):
            result = generation(self.folder,self.doc,provider,page_mode=True)
        self.assertEqual(maximum,3)
        contexts = {page: payload['neighboringContext'] for page,payload in calls}
        self.assertEqual(contexts[1],[])
        self.assertEqual([item['page'] for item in contexts[2]],[1])
        self.assertEqual([item['page'] for item in contexts[3]],[2])
        self.assertEqual(contexts[3][0]['visualContextSummary'],'context 2')
        self.assertTrue(all('sourceId' not in item for items in contexts.values() for item in items))
        self.assertTrue(all(payload['knownConceptNames']==[] for _,payload in calls))
        self.assertEqual([section['evidence'][0]['page'] for section in result['sections']],[1,2,3])
        ready = [event['unit'] for kind,event in events if kind=='summary_unit_ready']
        self.assertEqual(ready,[3,2,1])

    def test_first_summary_is_visible_while_next_page_vision_is_running(self):
        second_vision_started = threading.Event()
        first_summary_ready = threading.Event()
        visible_during_vision = []

        class OverlapProvider(FakeProvider):
            def complete(self, payload, **kwargs):
                if kwargs.get('image') and payload['page'] == 2:
                    second_vision_started.set()
                    if not first_summary_ready.wait(2):
                        raise AssertionError('page 1 summary waited for all visual pages')
                elif not kwargs.get('image') and 'sources' in payload and payload['sources'][0]['page'] == 1:
                    saved = json.loads((self_folder/'document.json').read_text(encoding='utf-8'))
                    if saved['pages'][0]['pageAnalysis']['status'] != 'ready':
                        raise AssertionError('summary started before the shared document was saved')
                    if not second_vision_started.wait(2):
                        raise AssertionError('next visual page did not overlap the summary')
                return super().complete(payload, **kwargs)

        self_folder = self.folder
        def record(kind, **event):
            if kind == 'summary_unit_ready' and event['unit'] == 1:
                visible_during_vision.append(second_vision_started.is_set())
                first_summary_ready.set()

        with patch('pdf_ai.emit', side_effect=record):
            generation(self.folder,self.doc,OverlapProvider(),page_mode=True)
        self.assertEqual(visible_during_vision,[True])

    def test_serial_rollback_keeps_prior_concept_hints_and_three_page_context(self):
        self.doc=document(self.folder,4)
        with patch('pdf_ai.SUMMARY_PARALLEL',False), patch('pdf_ai.PROMPT_VERSION','pdf-grounded-ko-v34'):
            generation(self.folder,self.doc,self.provider,page_mode=True)
        requests=[payload for payload,kwargs in self.provider.calls if not kwargs.get('image') and 'sources' in payload]
        self.assertEqual([payload['sources'][0]['page'] for payload in requests],[1,2,3,4])
        self.assertEqual([item['page'] for item in requests[3]['neighboringContext']],[1,2,3])
        self.assertIn('같은 개념',requests[3]['knownConceptNames'])


if __name__=='__main__':unittest.main()
