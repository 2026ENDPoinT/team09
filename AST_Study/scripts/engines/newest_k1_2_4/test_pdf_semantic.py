"""Semantic migration contracts; all providers are offline, never load API keys."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pdf_ai as ai
import pdf_semantic as sem
import pdf_page_analysis as vision
from pdf_pipeline import write_json
from test_pdf_page_analysis import document


def reading(page, text, role='teaching', kind='text'):
    return {'inventory': [{'key': 'e1', 'kind': kind, 'role': role, 'label': '강의 내용',
                           'anchorIds': [a['id'] for a in page['anchors']]}],
            'elements': [{'key': 'e1', 'title': '강의 개념', 'kind': kind, 'bbox': [.1,.1,.9,.9],
                          'transcription': text, 'formulas': [], 'description': '', 'relationships': [],
                          'purpose': '개념을 설명해요.', 'uncertainDetails': [], 'status': 'complete'}],
            'coverage': 'complete', 'contextSummary': '강의 개념을 설명해요.'}


class FakeProvider:
    model = 'gpt-6-luna'
    def __init__(self, mode='rp'):
        self.calls = []; self.context = {}; self.mode = mode; self.fail = False
    def complete(self, payload, **kwargs):
        self.calls.append(copy.deepcopy(payload))
        if payload['task'] == 'semantic_reading':
            values=[]
            for p in payload['pages']:
                text = ('환매조건부채권은 일정 기간 이후 정해진 가격으로 되사는' if p['page']==1 else
                        '조건으로 발행한 채권이며 통상 만기가 2주 이하예요.') if self.mode=='rp' else '탐색 과정에서 같은 경로를 방문해요.'
                values.append({'page':p['page'], 'analysis':reading(p,text)})
            return {'pages':values}
        if payload['task'] == 'semantic_links':
            available=payload['before'][:]; ds=[]
            for b in payload['targets']:
                role=('continue' if self.mode=='rp' else 'repeat') if available else 'new'
                ds.append({'id':b['id'], 'role':role, 'attachTo':available[-1]['id'] if available else '',
                           'reason':'앞선 설명과 이어져요.', 'delta':''})
                available.append(b)
            return {'decisions':ds}
        if payload['task']=='semantic_study':
            if self.fail:
                raise ai.AiResponseError('offline simulated interruption')
            return {'units':[{'unitId':u['unitId'], 'title':'환매조건부채권' if self.mode=='rp' else '탐색 과정',
                'parts':[{'title':'개념과 조건', 'body':' '.join(b['text'] for b in u['blocks']),
                          'easyExplanation':'조건과 결과를 함께 살펴봐요.', 'blockIds':u['requiredBlockIds']}],
                'concepts':[{'name':'핵심 개념','definition':'조건을 포함한 개념이에요.', 'partIndex':0,'extra':''}]}
                for u in payload['units']]}
        raise AssertionError(payload)


def block(i, text='같은 개념을 설명해요.', kind='text'):
    return {'id':str(i), 'page':i+1,'kind':kind,'sourceRole':'teaching','title':'설명',
            'text':text,'readingStatus':'complete','uncertainDetails':[], 'bbox':[0,0,1,1],
            'anchorIds':[], 'originId':str(i),'provenance':'ai_reading','start':0,'end':len(text)}


def decision(b, role='new', ref=''):
    return {'id':b['id'],'role':role,'attachTo':ref,'reason':'판정 사유','delta':''}


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.quiet=contextlib.redirect_stdout(io.StringIO());self.quiet.__enter__()
    def tearDown(self):
        self.quiet.__exit__(None,None,None);self.temp.cleanup()

    def test_topic_can_contain_heading_two_terms_table_and_example(self):
        bs=[block(i,t) for i,t in enumerate(['통화량 측정', 'M1 정의', 'M2 정의', '구성 비교표', '수치 예시'])]
        ds=[decision(bs[0])]+[decision(b,'detail',bs[i-1]['id']) for i,b in enumerate(bs) if i]
        ds[-1]['role']='example_start'
        validated=sem.validate_decisions({'decisions':ds},{'before':[],'targets':bs,'after':[]})
        units,ledger=sem.make_units(bs,validated,{b['page'] for b in bs})
        self.assertEqual(len(units),1)
        self.assertEqual(units[0]['blocks'],bs)
        self.assertEqual(len(ledger),5)

    def test_study_schema_requires_requested_count_and_ids_without_mutating_base(self):
        fmt=sem.study_format([{'unitId':'u1'},{'unitId':'u2'}])
        arr=fmt['json_schema']['schema']['properties']['units']
        self.assertEqual((arr['minItems'],arr['maxItems']),(2,2))
        self.assertEqual(arr['items']['properties']['unitId']['enum'],['u1','u2'])
        self.assertEqual(arr['items']['properties']['title'],{'type':'string'})
        self.assertEqual(arr['items']['properties']['parts']['items']['properties']['body'],{'type':'string'})
        self.assertEqual(arr['items']['properties']['parts']['items']['properties']['blockIds']['items'],{'type':'string'})
        self.assertNotIn('minItems',sem.STUDY_FORMAT['json_schema']['schema']['properties']['units'])

    def test_defined_term_cannot_disappear_when_grouped_under_broader_topic(self):
        bs=[block(0,'1.5.2 위험 분담\n자산변환(asset transformation): 새로운 자산을'),block(1,'개발한 후 판매합니다.')]
        self.assertEqual(sem.defined_terms(bs),[{'name':'자산변환','english':'asset transformation','blockId':'0'}])
        raw={'title':'위험 분담','parts':[{'body':'금융중개기관이 위험을 분담합니다.'}], 'concepts':[]}
        self.assertEqual(sem.missing_defined_terms(raw,bs),['자산변환'])
        raw['concepts']=[{'name':'자산변환','definition':'새 자산을 개발하고 판매합니다.'}]
        self.assertEqual(sem.missing_defined_terms(raw,bs),[])
        self.assertEqual(sem.defined_terms([block(0,'예: 사과 3개\nhttps://example.com\n12:30')]),[])
        self.assertEqual(sem.missing_defined_terms({'parts':[]},[block(0,'M1: 좁은 통화량\nM2: 넓은 통화량')]),['M1','M2'])

    def test_boundary_check_list_contains_both_sentence_fragments_not_typo(self):
        bs=[block(0),block(1),block(2)]
        bs[0]['uncertainDetails']=['이 페이지에서 문장의 나머지를 확인할 수 없습니다.']
        bs[1]['uncertainDetails']=['문장 첫머리의 상품명이 잘려 있어 확정할 수 없습니다.']
        bs[2]['uncertainDetails']=['이 페이지의 단위에 오타가 있습니다.']
        self.assertEqual([x['blockId'] for x in sem.boundary_checks(bs)],['0','1'])

    def boundary_fixture(self):
        doc=document(self.folder,2)
        bs=[block(0,'환매조건부채권은 정해진 가격으로 되사는'),block(1,'조건의 채권이며 통상 만기는 2주 이하예요.')]
        bs[0]['uncertainDetails']=['문장이 페이지 하단에서 중단되어 나머지 조건을 확인할 수 없습니다.']
        ds=sem.validate_decisions({'decisions':[decision(bs[0]),decision(bs[1],'continue',bs[0]['id'])]},
                                  {'before':[],'targets':bs,'after':[]})
        units,ledger=sem.make_units(bs,ds,{1,2});job=sem.study_jobs(units)[0]
        raw=FakeProvider().complete({'task':'semantic_study','units':[
            {**s,'requiredBlockIds':[b['id'] for b in s['blocks']]} for s in job]})
        resolution={'blockId':'0','detailIndex':0,'evidenceBlockIds':['0','1'],
                    'explanation':'다음 페이지에 발행 조건과 만기가 이어져요.'}
        raw['units'][0]['resolvedBoundaries']=[resolution]
        return doc,bs,units,ledger,job,raw

    def test_boundary_resolution_requires_joined_evidence_and_preserves_audit(self):
        doc,bs,units,ledger,job,raw=self.boundary_fixture()
        completed=sem.validate_study(raw,job,doc)
        result=sem.assemble(doc,'document',0,[1,2],units,ledger,completed,1)
        self.assertTrue(result['coverageComplete'])
        self.assertEqual(result['coverage'][0]['uncertainDetails'],bs[0]['uncertainDetails'])
        self.assertEqual(result['coverage'][0]['resolvedBoundaries'][0]['evidenceBlockIds'],['0','1'])
        raw['units'][0]['resolvedBoundaries']=[]
        unresolved=sem.assemble(doc,'document',0,[1,2],units,ledger,sem.validate_study(raw,job,doc),1)
        self.assertFalse(unresolved['coverageComplete'])

    def test_cannot_resolve_unreadable_typo_or_missing_evidence(self):
        for change in ('unreadable','typo','unknown','no_neighbor','different_parts'):
            doc,bs,units,ledger,job,raw=self.boundary_fixture()
            r=raw['units'][0]['resolvedBoundaries'][0]
            if change=='unreadable':bs[0]['readingStatus']='unreadable'
            elif change=='typo':bs[0]['uncertainDetails']=['이 페이지의 기호에 오타가 있습니다.']
            elif change=='unknown':r['evidenceBlockIds']=['0','invented']
            elif change=='no_neighbor':r['evidenceBlockIds']=['0']
            else:
                p=raw['units'][0]['parts'][0];p['blockIds']=['0']
                raw['units'][0]['parts'].append({**p,'blockIds':['1']})
            with self.subTest(change=change):
                completed=sem.validate_study(raw,job,doc)
                self.assertEqual(completed[0]['resolvedBoundaries'],[])
                self.assertEqual(len(completed[0]['rejectedBoundaryResolutions']),1)
                result=sem.assemble(doc,'document',0,[1,2],units,ledger,completed,1)
                self.assertFalse(result['coverageComplete'])

    def test_textbook_supplement_flags_survive_summary_and_card_assembly(self):
        doc,bs,units,ledger,job,raw=self.boundary_fixture()
        raw['units'][0]['parts'][0]['standardKnowledgeUsed']=True
        completed=sem.validate_study(raw,job,doc)
        result=sem.assemble(doc,'document',0,[1,2],units,ledger,completed,1)
        self.assertTrue(result['standardKnowledgeUsed'])
        self.assertTrue(result['sections'][0]['standardKnowledgeUsed'])
        self.assertTrue(result['concepts'][0]['entries'][0]['standardKnowledgeUsed'])

    def test_adjacent_reciprocal_continuation_preserves_both_sources(self):
        first, second = block(0, '환매조건부채권은 정해진 가격으로 되사는'), block(1, '조건의 채권이며 통상 만기는 2주 이하예요.')
        original = {'decisions':[decision(first,'continue',second['id']), decision(second,'continue',first['id'])]}
        window = {'before':[], 'targets':[first,second], 'after':[]}
        actual = sem.validate_decisions(original, window)
        self.assertEqual(original['decisions'][0]['attachTo'], second['id'])
        self.assertEqual(actual[0]['attachTo'], '')
        self.assertEqual(actual[0]['normalization'], 'adjacent_reciprocal_continuation')
        units, ledger = sem.make_units([first,second], actual, {1,2})
        self.assertEqual(len(units),1)
        self.assertEqual(units[0]['blocks'],[first,second])
        self.assertIn('normalization', ledger[0])

    def test_forward_artwork_link_preserves_group_without_swallowing_intervening_topic(self):
        bs=[block(i) for i in range(3)]
        raw=[decision(bs[0],'example_start','2'),decision(bs[1]),decision(bs[2])]
        actual=sem.validate_decisions({'decisions':raw},{'before':[], 'targets':bs, 'after':[]})
        units,ledger=sem.make_units(bs,actual,{1,2,3})
        self.assertEqual([[b['id'] for b in u['blocks']] for u in units],[['0','2'],['1']])
        self.assertEqual(raw[0]['attachTo'],'2')
        self.assertEqual(ledger[0]['originalDecision']['attachTo'],'2')
        self.assertEqual(sem.validate_decisions({'decisions':actual},{'before':[], 'targets':bs, 'after':[]}),actual)

    def test_forward_component_reaches_prior_context_and_keeps_all_source(self):
        bs=[block(i) for i in range(4)]
        raw=[decision(bs[1],'detail','3'),decision(bs[2]),decision(bs[3],'detail','0')]
        actual=sem.validate_decisions({'decisions':raw},{'before':bs[:1], 'targets':bs[1:], 'after':[]})
        units,_=sem.make_units(bs,[decision(bs[0]),*actual],{1,2,3,4})
        self.assertEqual([[b['id'] for b in u['blocks']] for u in units],[['0','1','3'],['2']])

    def test_cycles_normalized_without_dropping_a_repeat_source(self):
        bs=[block(i) for i in range(3)]
        raw=[decision(bs[0],'repeat','2'),decision(bs[1],'detail','0'),decision(bs[2],'detail','1')]
        actual=sem.validate_decisions({'decisions':raw},{'before':[], 'targets':bs, 'after':[]})
        units,_=sem.make_units(bs,actual,{1,2,3})
        jobs=sem.study_jobs(units)
        self.assertEqual([b['id'] for j in jobs for seg in j for b in seg['blocks']],['0','1','2'])

    def test_unresolved_following_context_and_missing_decision_preserved(self):
        bs=[block(i) for i in range(3)]
        ds=sem.validate_decisions({'decisions':[decision(bs[0],'repeat','2')]},
                                  {'before':[],'targets':bs[:2],'after':bs[2:]})
        self.assertEqual([d['role'] for d in ds],['uncertain','uncertain'])
        self.assertTrue(all(not d['attachTo'] for d in ds))
        units,ledger=sem.make_units(bs[:2],ds,{1,2})
        result=sem.assemble(document(self.folder,3),'document',0,[1,2],units,ledger,[],0)
        self.assertEqual(result['coverageCounts']['needs_review'],2)
        self.assertFalse(result['coverageComplete'])

    def test_self_and_excluded_links_do_not_swallow_teaching_sources(self):
        a,b=block(0),block(1,kind='decoration')
        for raw in ([decision(a,'detail','0'),decision(b,'exclude')],
                    [decision(a,'detail','1'),decision(b,'exclude')]):
            ds=sem.validate_decisions({'decisions':raw},{'before':[],'targets':[a,b],'after':[]})
            units,ledger=sem.make_units([a,b],ds,{1,2})
            self.assertEqual(units[0]['blocks'],[a])
            self.assertEqual(ds[0]['role'],'uncertain')
            self.assertEqual(ledger[1]['state'],'excluded')
        with self.assertRaises(ValueError):
            sem.validate_decisions({'decisions':[]},{'before':[],'targets':[a,b],'after':[]})

    def test_missing_navigation_heading_not_sent_as_an_empty_lesson(self):
        a,b=block(0,'액션 페인팅'),block(1,'회화의 평면성을 설명해요.')
        a['sourceRole']='navigation'
        ds=sem.validate_decisions({'decisions':[decision(b)]},{'before':[],'targets':[a,b],'after':[]})
        units,ledger=sem.make_units([a,b],ds,{1,2})
        self.assertEqual([u['blocks'] for u in units],[[b]])
        self.assertEqual(ledger[0]['state'],'excluded')
        self.assertEqual(ledger[0]['exclusionBasis'],'complete_reading_non_teaching_unit')
        self.assertEqual(ledger[1]['state'],'pending_summary')

    def test_navigation_filter_keeps_mixed_and_uncertain_content(self):
        a,b=block(0,'액션 페인팅'),block(1,'회화의 평면성을 설명해요.')
        a['sourceRole']='navigation'
        units,_=sem.make_units([a,b],[decision(a),decision(b,'detail','0')],{1,2})
        self.assertEqual(units[0]['blocks'],[a,b])
        a['uncertainDetails']=['일부 내용 판독이 불확실해요.']
        units,_=sem.make_units([a],[decision(a,'uncertain')],{1})
        self.assertEqual(units[0]['blocks'],[a])
        a['uncertainDetails']=[];a['readingStatus']='unreadable'
        units,_=sem.make_units([a],[decision(a,'uncertain')],{1})
        self.assertEqual(units[0]['blocks'],[a])

    def test_empty_teaching_result_is_still_rejected(self):
        a=block(0,'학습 내용이 있는 원문이에요.')
        units,_=sem.make_units([a],[decision(a)],{1});job=sem.study_jobs(units)[0]
        raw={'units':[{'unitId':job[0]['unitId'],'title':'주제','parts':[], 'concepts':[], 'resolvedBoundaries':[]}]}
        with self.assertRaisesRegex(ValueError,'학습 내용이 있는 설명 단위가 비어'):
            sem.validate_study(raw,job,document(self.folder,1))

    def test_local_overview_finishes_valid_sections_without_outline_api(self):
        doc=document(self.folder,2)
        class Independent(FakeProvider):
            def complete(self,payload,**kwargs):
                if payload.get('task')=='semantic_links':
                    self.calls.append(copy.deepcopy(payload))
                    return {'decisions':[decision(b) for b in payload['targets']]}
                return super().complete(payload,**kwargs)
        provider=Independent()
        result=sem.generate(self.folder,doc,provider,local_overview=True)
        self.assertTrue(result['processingComplete'])
        self.assertEqual(len(result['sections']),2)
        self.assertEqual(result['overview']['overviewMethod'],'local_headings_prose')
        self.assertFalse(any(p.get('task')=='lecture_flow_from_headings' for p in provider.calls))

    def test_original_semantic_plan_still_supplies_desktop_cost_fields(self):
        doc=document(self.folder,2)
        plan=sem.reading_plan(self.folder,doc,[1,2],'gpt-6-luna','document',None)
        self.assertEqual(plan['strategy'],'semantic-v1')
        self.assertEqual(plan['pending'],2)
        for key in ('costEstimateUsd','additionalCostEstimateUsd','totalCostEstimateUsd'):
            self.assertIsInstance(plan[key],float)

    def test_cross_page_sentence_single_summary_and_multpage_evidence(self):
        doc=document(self.folder,2); provider=FakeProvider()
        legacy=self.folder/'generated/latest-document-0.json';write_json(legacy,{'legacy':'unchanged'})
        original=copy.deepcopy(doc)
        result=sem.generate(self.folder,doc,provider)
        self.assertEqual(doc,original)
        self.assertEqual(json.loads(legacy.read_text()),{'legacy':'unchanged'})
        self.assertEqual(len(result['sections']),1)
        self.assertIn('만기가 2주 이하',result['sections'][0]['body'])
        self.assertEqual({e['page'] for e in result['sections'][0]['evidence']},{1,2})
        self.assertEqual(result['coverageCounts']['summarized'],2)
        self.assertEqual([p['task'] for p in provider.calls],['semantic_reading','semantic_links','semantic_study'])
        self.assertTrue(result['coverageComplete'])
        self.assertEqual(sem.generate(self.folder,doc,provider),result)
        self.assertEqual(len(provider.calls),3)

    def test_177_repeated_frames_are_all_read_but_one_summary(self):
        doc=document(self.folder,177);provider=FakeProvider('repeat')
        with patch.object(vision,'render_page',return_value={'data':'unused','width':300,'height':200}):
            result=sem.generate(self.folder,doc,provider)
        pages=[p['page'] for call in provider.calls if call['task']=='semantic_reading' for p in call['pages']]
        self.assertEqual(sorted(pages),list(range(1,178)))
        self.assertEqual(len(result['sections']),1)
        self.assertEqual(result['coverageCounts']['integrated'],176)
        self.assertEqual(result['coverageCounts']['summarized'],1)
        self.assertEqual(len([p for p in provider.calls if p['task']=='semantic_reading']),45)
        self.assertEqual(len([p for p in provider.calls if p['task']=='semantic_study']),1)
        # Planning windows have bounded context, never all accumulated prior pages.
        for call in provider.calls:
            if call['task']=='semantic_links':
                self.assertLessEqual(len(call['targets']),32)
                self.assertLessEqual(len(call['before']),6)
                self.assertLessEqual(len(call['after']),2)

    def test_existing_reading_reused_without_images_or_legacy_write(self):
        doc=document(self.folder,2);provider=FakeProvider()
        for n in (1,2):
            raw=reading({'anchors':vision.anchors(doc['pages'][n-1])},'원문 설명이에요.')
            saved=vision.validate(raw,doc['pages'][n-1],vision.key_for(doc,n))
            saved.update(inputKey=vision.key_for(doc,n),page=n,documentId=doc['documentId'])
            write_json(vision.cache_path(self.folder,doc,n),saved)
        result=sem.generate(self.folder,doc,provider)
        self.assertFalse(any(x['task']=='semantic_reading' for x in provider.calls))
        self.assertEqual(result['coverageCounts']['summarized'],2)

    def test_repeat_changed_number_not_compressed(self):
        a,b=block(0,'금리 2%'),block(1,'금리 3%')
        ds=sem.validate_decisions({'decisions':[decision(b,'repeat',a['id'])]},
                                 {'before':[a],'targets':[b],'after':[]})
        self.assertEqual(ds[0]['role'],'example_change')

    def test_unknown_and_duplicate_ids_rejected(self):
        a,b=block(0),block(1)
        w={'before':[],'targets':[a,b],'after':[]}
        for values in ([decision(a),decision(a)], [decision(a),decision(block(8))],
                       [decision(a),decision(b,'continue','unknown')]):
            with self.assertRaises(ValueError):sem.validate_decisions({'decisions':values},w)

    def test_teaching_cannot_be_silently_excluded(self):
        a=block(0)
        ds=sem.validate_decisions({'decisions':[decision(a,'exclude')]},{'before':[],'targets':[a],'after':[]})
        self.assertEqual(ds[0]['role'],'uncertain')

    def test_uncertain_reading_is_not_skipped(self):
        a,b=block(0),block(1);b['readingStatus']='unreadable'
        ds=sem.validate_decisions({'decisions':[decision(b,'repeat',a['id'])]},
                                 {'before':[a],'targets':[b],'after':[]})
        self.assertEqual(ds[0]['role'],'uncertain')

    def test_non_teaching_all_excluded_needs_no_summary(self):
        bs=[block(0,kind='contents'),block(1,kind='problem')]
        ds=[decision(b,'exclude') for b in bs]
        units,ledger=sem.make_units(bs,ds,{1,2})
        self.assertEqual(units,[])
        result=sem.assemble(document(self.folder,2),'document',0,[1,2],units,ledger,[],0)
        self.assertEqual(result['coverageCounts']['excluded'],2)
        self.assertTrue(result['coverageComplete'])

    def test_cross_window_continuation_has_exactly_one_owner(self):
        bs=[block(i) for i in range(70)]
        ds=[decision(b,'continue' if i else 'new',bs[i-1]['id'] if i else '') for i,b in enumerate(bs)]
        units,ledger=sem.make_units(bs,ds,set(range(1,71)))
        self.assertEqual(len(units),1)
        self.assertEqual(len({x['blockId'] for x in ledger}),70)
        self.assertEqual(len(units[0]['blocks']),70)

    def test_long_unit_segments_preserve_all_text_and_bounded_neighbors(self):
        bs=[block(i,'문장과 조건을 보존해요. '*150) for i in range(20)]
        ds=[decision(b,'continue' if i else 'new',bs[i-1]['id'] if i else '') for i,b in enumerate(bs)]
        units,_=sem.make_units(bs,ds,set(range(1,21)));jobs=sem.study_jobs(units)
        self.assertGreater(len(jobs),1)
        self.assertEqual([b['id'] for j in jobs for s in j for b in s['blocks']],[b['id'] for b in bs])
        self.assertTrue(any(s['context'] for j in jobs for s in j))

    def test_split_text_preserves_every_character_and_offsets(self):
        text=('페이지를 넘어가는 원문이에요.\n\n'*1000)
        spans=sem.split_text(text,300)
        self.assertEqual(''.join(s[2] for s in spans),text)
        self.assertTrue(all(text[a:b]==s for a,b,s in spans))
        self.assertTrue(all(len(s.encode())<=300 for _,_,s in spans))

    def test_scope_reads_one_neighbor_each_side(self):
        doc=document(self.folder,10)
        self.assertEqual(sem.selection(doc,'page',5),(5,[5],[4,5,6]))
        self.assertEqual(sem.selection(doc,'section',7),(6,[6,7,8,9,10],[5,6,7,8,9,10]))
        for scope,page in [('bad',1),('page',0),('page',11),('page',True)]:
            with self.assertRaises(ValueError):sem.selection(doc,scope,page)

    def test_partial_failure_preserves_readings_links_and_retry_skips_them(self):
        doc=document(self.folder,2);provider=FakeProvider();provider.fail=True
        with self.assertRaises(ai.AiResponseError):sem.generate(self.folder,doc,provider)
        self.assertTrue((sem.run_cache(self.folder,doc,provider.model,'document',0)/'manifest.json').exists())
        previous=len(provider.calls);provider.fail=False
        sem.generate(self.folder,doc,provider)
        self.assertEqual([p['task'] for p in provider.calls[previous:]],['semantic_study'])

    def test_source_or_prompt_version_invalidates_only_appropriate_cache(self):
        doc=document(self.folder,1);provider=FakeProvider()
        sem.generate(self.folder,doc,provider)
        initial=len(provider.calls)
        with patch.object(sem,'STUDY_VERSION','semantic-study-test'):
            sem.generate(self.folder,doc,provider)
        self.assertFalse(any(c['task']=='semantic_reading' for c in provider.calls[initial:]))
        self.assertNotEqual(sem.run_cache(self.folder,doc,provider.model,'document',0),
                            sem.run_cache(self.folder,{**doc,'fingerprint':'changed'},provider.model,'document',0))

    def test_missing_and_foreign_summary_evidence_is_rejected(self):
        doc=document(self.folder,2);bs=[block(0),block(1)]
        segment={'unitId':'u','parentId':'p','segment':1,'blocks':bs,'context':[]}
        raw=FakeProvider().complete({'task':'semantic_study','units':[{'unitId':'u','blocks':bs,'requiredBlockIds':['0','1']}]})
        raw['units'][0]['parts'][0]['blockIds']=['0']
        with self.assertRaises(ValueError):sem.validate_study(raw,[segment],doc)
        raw['units'][0]['parts'][0]['blockIds']=['0','1','wrong']
        with self.assertRaises(ValueError):sem.validate_study(raw,[segment],doc)

    def test_complete_caption_omission_is_recorded_without_losing_teaching(self):
        doc=document(self.folder,1)
        taught=block(0,'데 스틸은 수평선과 수직선을 활용해요.')
        caption=block(1,'데 스틸 선언문, 1918.')
        caption.update(page=1,sourceRole='navigation')
        blocks=[taught,caption]
        units,ledger=sem.make_units(blocks,[decision(taught),decision(caption,'detail',taught['id'])],{1})
        job=sem.study_jobs(units)[0]
        raw=FakeProvider().complete({'task':'semantic_study','units':[
            {**job[0],'requiredBlockIds':[taught['id']]}]})
        completed=sem.validate_study(raw,job,doc)
        result=sem.assemble(doc,'document',0,[1],units,ledger,completed,1)
        self.assertEqual(result['coverageCounts']['summarized'],1)
        self.assertEqual(result['coverageCounts']['excluded'],1)
        self.assertEqual(result['coverageCounts']['pending_summary'],0)
        self.assertTrue(result['coverageComplete'])

    def test_same_page_source_is_valid_evidence_but_foreign_id_is_not(self):
        doc=document(self.folder,1)
        image=block(0,'밤의 식당 안에 인물들이 보여요.',kind='image')
        explanation=block(1,'작품은 도시의 고립감을 설명해요.')
        explanation['page']=1
        segment={'unitId':'u','parentId':'p','segment':1,'blocks':[image],'context':[]}
        raw=FakeProvider().complete({'task':'semantic_study','units':[
            {'unitId':'u','blocks':[image],'requiredBlockIds':[image['id']]}]})
        raw['units'][0]['parts'][0]['blockIds']=[image['id'],explanation['id']]
        with self.assertRaises(ValueError):sem.validate_study(raw,[segment],doc)
        completed=sem.validate_study(raw,[segment],doc,{image['id']:image,explanation['id']:explanation})
        self.assertEqual([e['sourceId'] for e in completed[0]['summary']['parts'][0]['evidence']],['0','1'])
        raw['units'][0]['parts'][0]['blockIds'].append('invented')
        with self.assertRaises(ValueError):sem.validate_study(raw,[segment],doc,{image['id']:image,explanation['id']:explanation})

    def test_real_provider_budget_and_paid_cache_used(self):
        doc=document(self.folder,2);fake=FakeProvider()
        def transport(body):
            content=body['messages'][1]['content']
            payload=json.loads(content[0]['text'] if isinstance(content,list) else content)
            answer=fake.complete(payload)
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer,ensure_ascii=False)}}],
                    'usage':{'prompt_tokens':200,'completion_tokens':100,'prompt_tokens_details':{'cached_tokens':50}}}
        provider=ai.Provider(self.folder,True,.5,transport=transport)
        result=sem.generate(self.folder,doc,provider)
        usage=sem.record_usage(self.folder,doc,provider,'document',0)
        self.assertEqual(usage['requests'],3)
        self.assertEqual(usage['cachedInputTokens'],150)
        self.assertEqual({e['kind'] for e in provider.ledger['requests']},
                         {'semantic_read','semantic_link','semantic_summary'})
        self.assertTrue(result['coverageComplete'])

    def test_revalidation_recovers_paid_batch_before_requesting_missing_subset(self):
        doc=document(self.folder,2);fake=FakeProvider(); paid=[]
        def transport(body):
            content=body['messages'][1]['content']
            payload=json.loads(content[0]['text'] if isinstance(content,list) else content)
            paid.append(payload)
            if payload.get('task')=='semantic_links':
                answer={'decisions':[decision(b) for b in payload['targets']]}
            elif 'topics' in payload:
                answer={'body':'강의 개념을 살펴봐요.','topicIds':[x['id'] for x in payload['topics']]}
            else:answer=fake.complete(payload)
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer,ensure_ascii=False)}}],
                    'usage':{'prompt_tokens':200,'completion_tokens':100}}
        provider=ai.Provider(self.folder,True,.5,transport=transport)
        original=sem.validate_study
        def temporarily_reject_second(value,job,document,same_page_sources=None):
            if any('sp2-' in s['unitId'] for s in job):
                raise ValueError('simulated old validation rule')
            return original(value,job,document,same_page_sources)
        with patch.object(sem,'validate_study',side_effect=temporarily_reject_second):
            with self.assertRaises(ValueError):sem.generate(self.folder,doc,provider)
        self.assertEqual(len(list((self.folder/'generated/semantic/study-units').glob('*.json'))),1)
        result=sem.generate(self.folder,doc,provider)
        self.assertTrue(result['processingComplete'])
        self.assertEqual(len([p for p in paid if p.get('task')=='semantic_study']),1)

    def test_partial_job_recovery_and_resume_do_not_repeat_finished_summary(self):
        doc=document(self.folder,3)
        class Independent(FakeProvider):
            def complete(self,payload,**kwargs):
                if payload.get('task')=='semantic_links':
                    self.calls.append(copy.deepcopy(payload))
                    return {'decisions':[decision(b) for b in payload['targets']]}
                if payload.get('task')=='semantic_study' and self.failPage and 'sp2-' in payload['units'][0]['unitId']:
                    self.calls.append(copy.deepcopy(payload));raise ai.AiResponseError('offline interruption')
                if 'topics' in payload:
                    self.calls.append(copy.deepcopy(payload))
                    return {'body':'개념의 흐름을 살펴봐요.','topicIds':[x['id'] for x in payload['topics']]}
                return super().complete(payload,**kwargs)
        provider=Independent();provider.failPage=True
        with patch.object(sem,'STUDY_BYTES',1):
            with self.assertRaises(ai.AiResponseError):sem.generate(self.folder,doc,provider)
            partial=sem.recover(self.folder,doc)
            self.assertEqual(partial['kind'],'partial')
            self.assertEqual(partial['partialUnits'],2)
            self.assertEqual(partial['coverageCounts']['pending_summary'],1)
            previous=len(provider.calls);provider.failPage=False
            result=sem.generate(self.folder,doc,provider)
            fresh=[c for c in provider.calls[previous:] if c.get('task')=='semantic_study']
            self.assertEqual(len(fresh),1)
            self.assertIn('sp2-',fresh[0]['units'][0]['unitId'])
            self.assertEqual([e['page'] for s in result['sections'] for e in s['evidence']],[1,2,3])
            self.assertTrue(result['coverageComplete'])

    def test_clean_native_conditions_survive_formula_only_transcription(self):
        doc=document(self.folder,1)
        doc['pages'][0]['textRegions'][0]['text']='단, 금리가 일정할 때에만 적용해요.'
        raw=reading({'anchors':vision.anchors(doc['pages'][0])},'')
        raw['elements'][0]['formulas']=[{'latex':'x=2','uncertainSymbols':''}]
        parsed=vision.validate(raw,doc['pages'][0],vision.key_for(doc,1))
        parsed.update(page=1)
        bs=sem.blocks_from_readings(doc,{1:parsed},[1])
        self.assertIn('금리가 일정할 때에만',bs[0]['text'])
        self.assertIn('x=2',bs[0]['text'])

    def test_incomplete_batch_resume_requests_only_missing_units(self):
        doc=document(self.folder,3)
        class Subset(FakeProvider):
            first=True
            def complete(self,payload,**kwargs):
                if payload.get('task')=='semantic_links':
                    self.calls.append(copy.deepcopy(payload))
                    return {'decisions':[decision(b) for b in payload['targets']]}
                if 'topics' in payload:
                    return {'body':'강의 개념을 살펴봐요.','topicIds':[x['id'] for x in payload['topics']]}
                value=super().complete(payload,**kwargs)
                if payload.get('task')=='semantic_study' and self.first:
                    self.first=False
                    return {'units':value['units'][:1]}
                return value
        provider=Subset()
        with self.assertRaisesRegex(ValueError,'요약 2개가 빠졌어요'):
            sem.generate(self.folder,doc,provider)
        self.assertEqual(len(list((self.folder/'generated/semantic/study-units').glob('*.json'))),1)
        previous=len(provider.calls)
        result=sem.generate(self.folder,doc,provider)
        fresh=[c for c in provider.calls[previous:] if c.get('task')=='semantic_study']
        self.assertEqual(len(fresh),1)
        self.assertEqual(len(fresh[0]['units']),2)
        self.assertTrue(all('sp1-' not in u['unitId'] for u in fresh[0]['units']))
        self.assertTrue(result['coverageComplete'])
        self.assertEqual(len(result['sections']),3)

    def test_resume_can_recover_before_any_summary_is_complete(self):
        doc=document(self.folder,2);provider=FakeProvider();provider.fail=True
        with self.assertRaises(ai.AiResponseError):sem.generate(self.folder,doc,provider)
        partial=sem.recover(self.folder,doc)
        self.assertEqual(partial['kind'],'partial')
        self.assertEqual(partial['coverageCounts']['pending_summary'],2)
        self.assertEqual(partial['partialUnits'],0)

    def test_tutor_uses_semantic_sources_without_touching_legacy_index(self):
        doc=document(self.folder,2);write_json(self.folder/'document.json',doc)
        original=(self.folder/'document.json').read_bytes()
        sem.generate(self.folder,doc,FakeProvider())
        sem.tutor_sources(self.folder,doc)
        self.assertEqual((self.folder/'document.json').read_bytes(),original)
        guide,evidence=ai.tutor_study_guide(self.folder,doc,1,broad=True,question='핵심 개념')
        self.assertIsNotNone(guide)
        self.assertTrue(any(c.get('semanticSource') for c in doc['chunks']))
        self.assertTrue(all(e['sourceId'] in {c['id'] for c in doc['chunks']} for e in evidence))

    def test_concurrent_generation_rejected_and_lock_released_after_error(self):
        doc=document(self.folder,1);provider=FakeProvider()
        with sem.generation_lock(self.folder):
            with self.assertRaises(ValueError):sem.generate(self.folder,doc,provider)
        self.assertEqual(provider.calls,[])
        result=sem.generate(self.folder,doc,provider)
        self.assertTrue(result['coverageComplete'])

    def test_no_budget_no_remote_call(self):
        doc=document(self.folder,1);calls=[]
        provider=ai.Provider(self.folder,True,.00001,transport=lambda p:calls.append(p))
        with self.assertRaises(ai.BudgetExceeded):sem.generate(self.folder,doc,provider)
        self.assertEqual(calls,[])

    def test_cancellation_before_reading(self):
        doc=document(self.folder,1);provider=FakeProvider()
        (self.folder/'cancel').touch()
        with self.assertRaises(InterruptedError):sem.generate(self.folder,doc,provider)
        self.assertEqual(provider.calls,[])


if __name__=='__main__':unittest.main()
