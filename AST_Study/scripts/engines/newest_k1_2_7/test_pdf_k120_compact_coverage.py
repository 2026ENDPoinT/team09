"""Offline compact-index checks; no provider or network calls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pdf_newest_k1_2_0 as engine
from pdf_k120_compact_coverage import encode_format,restore,CompactCoverageError
from pdf_study_cache_reuse import constrained_format
from pdf_study_batch_transport import _validate


def fixture():
    blocks=[{'id':key,'page':1,'bbox':[0,.1,.9,.2],'kind':'text',
             'text':'물체의 위치가 시간에 따라 달라지는 운동을 설명한다.'}for key in ('a','b')]
    job={'id':'unit','title':'운동','blocks':blocks}
    form=constrained_format(engine.STUDY_FORMAT,job)
    form['json_schema']['schema']['properties']['sourceCoverage'].update(minItems=2,maxItems=2)
    form['json_schema']['schema']['properties']['uncertainBlocks']['maxItems']=0
    raw={'concepts':[{'title':'운동','sourceSetup':{'teachingRole':'independent',
        'observedRelations':[],'boundaryChecks':[],'interpretation':'','sourceQuotes':[],
        'learnerDifficulty':{'kind':'none','question':''}},'segments':[
            {'kind':'definition','text':'운동은 물체의 위치가 시간에 따라 변하는 현상이에요.','blockIds':['a','b']},
            {'kind':'explanation','text':'서로 다른 시각의 위치를 비교하면 물체가 이동했는지 알 수 있어요.','blockIds':['a','b']}],
        'standardKnowledgeUsed':False}], 'tables':[],'sequences':[],
        'excludedBlocks':[],'uncertainBlocks':[],
        'sourceCoverage':[{'blockId':key,'mainSegmentRef':{'conceptIndex':0,'segmentIndex':0}}
                          for key in ('a','b')]}
    wire,exact=encode_format(form)
    return job,wire,exact,raw


class CompactCoverageTests(unittest.TestCase):
    def test_wire_and_historical_request_share_every_source_and_learning_field(self):
        job,_,_,_=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            args=(Path(tmp),job,job['blocks'],{'pages':[{'label':'1'}]},([],[]))
            current=engine.build_teaching_request(*args)
            historical=engine.build_teaching_request(*args,legacy_coverage=True)
            canonical=engine.build_teaching_request(*args,canonical=True)
        self.assertEqual(current['payload'],historical['payload'])
        self.assertEqual(current['images'],historical['images'])
        self.assertEqual(current['aliases'],historical['aliases'])
        self.assertEqual(current['_sourceCoverageExactFormat'],historical['_sourceCoverageExactFormat'])
        self.assertEqual(current['context']['studyTeachingIdentity'],historical['context']['studyTeachingIdentity'])
        # K1.2.2 already derives the duplicate index locally. K1.2.3 also omits
        # two repetitive internal fields; canonical source accounting stays exact.
        for request in (current,historical,canonical):
            self.assertNotIn('sourceCoverage',request['response_format']['json_schema']['schema']['properties'])
            exact=request['_sourceCoverageExactFormat']['json_schema']['schema']
            self.assertEqual(exact['$defs']['studySourceId']['enum'],['a','b'])
            self.assertEqual((exact['properties']['sourceCoverage']['minItems'],exact['properties']['sourceCoverage']['maxItems']),(2,2))
            self.assertIn('quote',exact['properties']['sourceCoverage']['items']['properties'])

    def test_paid_cache_lookup_never_issues_a_new_call_and_can_restore_old_format(self):
        from pdf_ai import AiResponseError
        calls=[]
        def build(*,legacy_coverage):
            return {'payload':{'legacy':legacy_coverage},'images':[],
                'context':{'legacy':legacy_coverage},'instructions':str(legacy_coverage),'response_format':{}}
        class Provider:
            context={}
            def complete(self,payload,**kwargs):
                calls.append(kwargs)
                if not payload['legacy']:raise AiResponseError('No current-format cache')
                return {'old':'paid response'}
        raw,request=engine.cached_teaching_reply(Provider(),build)
        self.assertEqual(raw,{'old':'paid response'})
        self.assertTrue(request['payload']['legacy'])
        self.assertEqual(len(calls),2)
        self.assertTrue(all(call['cache_only'] is True for call in calls))

    def test_paid_cache_hit_does_not_requery_or_fallback(self):
        provider=type('Provider',(),{'context':{}})()
        with patch.object(provider,'complete',create=True,return_value={'current':'paid'}) as complete:
            request={'payload':{},'images':[],'context':{},'instructions':'','response_format':{}}
            raw,_=engine.cached_teaching_reply(provider,lambda **kw:request)
        self.assertEqual(raw,{'current':'paid'})
        complete.assert_called_once()
        self.assertTrue(complete.call_args.kwargs['cache_only'])

    def test_accept_preserves_canonical_cache_and_revalidates_without_compact_wire(self):
        job,_,exact,raw=fixture()
        request={'_sourceCoverageExactFormat':exact,'aliases':None,'visualOwnership':None,'job':job}
        document={'documentId':'doc','pages':[{'label':'1'}]}
        with tempfile.TemporaryDirectory() as tmp:
            result=engine.accept_teaching_reply(Path(tmp),document,[job],job,raw,request)
            saved=json.loads((Path(tmp)/'response-unit.json').read_text())
            self.assertEqual(saved[engine.CANONICAL_MARKER],engine.COMPACT_COVERAGE_VERSION)
            self.assertNotIn('mainSegmentRef',saved['sourceCoverage'][0])
            self.assertEqual(saved['concepts'],raw['concepts'])
            self.assertEqual(engine.validate(saved,job,document),result)
            legacy=copy.deepcopy(saved);legacy.pop(engine.CANONICAL_MARKER)
            legacy_request={**request,'_sourceCoverageExactFormat':None}
            old=engine.accept_teaching_reply(Path(tmp),document,[job],job,legacy,legacy_request)
            self.assertEqual(old,result)

    def test_old_unmarked_saved_results_keep_their_existing_validation_contract(self):
        job,_,exact,raw=fixture()
        for segment in raw['concepts'][0]['segments']:segment['blockIds']=['a']
        raw['concepts'][0]['sourceSetup']['learnerDifficulty']={'kind':'intermediate_step','question':'시간을 어떻게 비교하나요?'}
        raw['concepts'][0]['segments'].append({'kind':'easyExplanation','text':'두 시각 사이에 달라진 위치를 순서대로 비교해요.','blockIds':['b']})
        raw['sourceCoverage'][1]['mainSegmentRef']={'conceptIndex':0,'segmentIndex':2}
        saved=restore(raw,exact)
        result=engine.validate(saved,job,{'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(next(r for r in result['coverage']if r['blockId']=='b')['state'],'summarized')

    def test_wire_changes_only_coverage_item_and_keeps_count_source_guards(self):
        job,wire,exact,raw=fixture()
        ws=wire['json_schema']['schema'];es=exact['json_schema']['schema']
        for name in es['properties']:
            if name!='sourceCoverage':self.assertEqual(ws['properties'][name],es['properties'][name])
        self.assertEqual(ws['$defs'],es['$defs'])
        self.assertEqual(ws['properties']['sourceCoverage']['minItems'],2)
        self.assertEqual(ws['properties']['sourceCoverage']['maxItems'],2)
        _validate(raw,ws,ws)

    def test_restore_copies_exact_main_text_and_does_not_mutate_input(self):
        job,wire,exact,raw=fixture();before=copy.deepcopy(raw)
        result=restore(raw,exact)
        self.assertEqual(raw,before)
        for key in raw:
            if key!='sourceCoverage':self.assertEqual(result[key],raw[key])
        self.assertEqual(result['sourceCoverage'][0],{'blockId':'a','conceptTitle':'운동',
            'quote':raw['concepts'][0]['segments'][0]['text']})
        schema=exact['json_schema']['schema'];_validate(result,schema,schema)

    def test_every_real_block_exactly_once_in_input_order(self):
        for kind in ('missing','duplicate','outside'):
            with self.subTest(kind=kind):
                *_,exact,raw=fixture()
                if kind=='missing':raw['sourceCoverage'].pop()
                if kind=='duplicate':raw['sourceCoverage'][1]['blockId']='a'
                if kind=='outside':raw['sourceCoverage'][1]['blockId']='c'
                with self.assertRaises(CompactCoverageError):restore(raw,exact)
        # Only duplicate index order is canonicalized, never learner/source order.
        *_,exact,raw=fixture();raw['sourceCoverage'].reverse()
        self.assertEqual([r['blockId']for r in restore(raw,exact)['sourceCoverage']],['a','b'])

    def test_malformed_wire_indices_are_rejected(self):
        mutations=('negative','boolean','extra_field')
        for kind in mutations:
            with self.subTest(kind=kind):
                *_,exact,raw=fixture();ref=raw['sourceCoverage'][0]['mainSegmentRef']
                segment=raw['concepts'][0]['segments'][0]
                if kind=='negative':ref['segmentIndex']=-1
                if kind=='boolean':ref['conceptIndex']=False
                if kind=='extra_field':ref['tableIndex']=0
                with self.assertRaises(ValueError):restore(raw,exact)

    def test_invalid_reference_is_blank_and_not_a_fabricated_citation(self):
        mutations=('outside_concept','outside_segment','easy','uncertain','no_citation')
        for kind in mutations:
            with self.subTest(kind=kind):
                *_,exact,raw=fixture();ref=raw['sourceCoverage'][0]['mainSegmentRef']
                segment=raw['concepts'][0]['segments'][0]
                if kind=='outside_concept':ref['conceptIndex']=3
                if kind=='outside_segment':ref['segmentIndex']=3
                if kind=='easy':segment['kind']='easyExplanation'
                if kind=='uncertain':segment['kind']='uncertain'
                if kind=='no_citation':segment['blockIds']=['b']
                before=copy.deepcopy(raw);value=restore(raw,exact)
                self.assertEqual(value['sourceCoverage'][0],{'blockId':'a','conceptTitle':'','quote':''})
                self.assertEqual(raw,before)
                for key in raw:
                    if key!='sourceCoverage':self.assertEqual(value[key],raw[key])

    def test_unmatched_null_cannot_silently_exclude_source(self):
        job,_,exact,raw=fixture();raw['sourceCoverage'][1]['mainSegmentRef']=None
        for segment in raw['concepts'][0]['segments']:segment['blockIds']=['a']
        value=restore(raw,exact)
        result=engine.validate(value,job,{'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(next(r for r in result['coverage']if r['blockId']=='b')['state'],'needs_review')

    def test_optional_easy_only_does_not_conceal_missing_main_coverage(self):
        job,_,exact,raw=fixture()
        for segment in raw['concepts'][0]['segments']:segment['blockIds']=['a']
        raw['concepts'][0]['sourceSetup']['learnerDifficulty']={'kind':'intermediate_step','question':'시간을 어떻게 비교하나요?'}
        raw['concepts'][0]['segments'].append({'kind':'easyExplanation','text':'두 시각 사이에 달라진 위치를 순서대로 비교해요.','blockIds':['b']})
        raw['sourceCoverage'][1]['mainSegmentRef']={'conceptIndex':0,'segmentIndex':2}
        value=restore(raw,exact)
        value[engine.CANONICAL_MARKER]=engine.COMPACT_COVERAGE_VERSION
        result=engine.validate(value,job,{'documentId':'doc','pages':[{'label':'1'}]})
        row=next(r for r in result['coverage']if r['blockId']=='b')
        self.assertEqual((row['state'],row['reviewKind']),('needs_review','content'))
        self.assertIn('두 시각 사이',result['concepts'][0]['easyExplanation'])

    def test_supplement_guard_never_promotes_or_rewrites_other_decisions(self):
        from pdf_k120_compact_coverage import retain_supplement_review
        result={'coverage':[{'blockId':key,'state':state,'reason':state}for key,state in
            [('a','context'),('b','excluded'),('c','needs_review'),('d','summarized')]],
            'summary':{'body':'untouched'},'concepts':[{'definition':'untouched'}]}
        before=copy.deepcopy(result)
        retain_supplement_review(result,{'a','b','c','d'})
        self.assertEqual(result['coverage'][:3],before['coverage'][:3])
        self.assertEqual(result['summary'],before['summary'])
        self.assertEqual(result['concepts'],before['concepts'])
        self.assertEqual(result['coverage'][3]['state'],'needs_review')

    def test_matching_exclusion_restores_blank_index_without_creating_teaching(self):
        *_,exact,raw=fixture();raw['sourceCoverage'][1]['mainSegmentRef']=None
        raw['excludedBlocks']=[{'blockId':'b','reason':'단순 반복 문제예요.',
            'referenceContext':None,'sourceDisposition':None,'exerciseSelection':None}]
        value=restore(raw,exact)
        self.assertEqual(value['sourceCoverage'][1],{'blockId':'b','conceptTitle':'','quote':''})
        self.assertEqual(value['excludedBlocks'],raw['excludedBlocks'])

    def test_uncertain_segment_remains_uncertain_in_original_validator(self):
        job,wire,exact,raw=fixture()
        raw['sourceCoverage'][1]['mainSegmentRef']=None
        for segment in raw['concepts'][0]['segments']:segment['blockIds']=['a']
        raw['concepts'][0]['segments'].append({'kind':'uncertain','text':'조건을 읽을 수 없어요.','blockIds':['b']})
        value=restore(raw,exact)
        result=engine.validate(value,job,{'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(next(c for c in result['coverage']if c['blockId']=='b')['state'],'needs_review')

    def test_accept_restores_and_checks_before_writing_or_ownership_validation(self):
        *_,exact,raw=fixture();raw['sourceCoverage'].pop()
        with patch.object(engine,'write_json')as write:
            with self.assertRaises(CompactCoverageError):
                engine.accept_teaching_reply(None,None,None,None,raw,{'_sourceCoverageExactFormat':exact})
            write.assert_not_called()

    def test_prompt_contract_has_one_consistent_coverage_representation(self):
        self.assertIn('mainSegmentRef',engine.STUDY_PROMPT)
        self.assertNotIn('conceptTitle and quote are both',engine.STUDY_PROMPT)
        self.assertNotIn('quote copies a',engine.STUDY_PROMPT)
        self.assertIn('definition or explanation',engine.STUDY_PROMPT)


if __name__=='__main__':unittest.main()
