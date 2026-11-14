"""Offline K1 planning context, cache isolation and streaming lifecycle contracts."""
import copy
import json
import socket
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import pdf_newest_k1_1_1 as k1
import pdf_new_concept_ver99_study as legacy
from pdf_pipeline import write_json


def block(i):
    return {'id':f'kp{i}f0','page':i+1,'bbox':[.1,.1,.9,.7],'kind':'text',
        'hasVisual':False,'planRole':'teaching','text':f'주제 {i}의 정의와 조건을 설명해요. 조건을 비교하면 결과를 알 수 있어요.'}


def response(source):
    return {'concepts':[{'title':'조건의 비교','sourceSetup':{'observedRelations':[],
        'boundaryChecks':[],'interpretation':'','sourceQuotes':[]},'segments':[
        {'kind':'definition','text':'조건을 비교하는 방법이에요.','blockIds':[source]},
        {'kind':'explanation','text':'조건이 달라지면 결과가 달라지는 이유를 살펴봐요.','blockIds':[source]},
        {'kind':'easyExplanation','text':'같은 조건을 먼저 비교해요.','blockIds':[source]}],
        'standardKnowledgeUsed':False}], 'sequences':[],'tables':[], 'excludedBlocks':[], 'uncertainBlocks':[]}


class K11LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('offline test'))
        self.guard.start();self.addCleanup(self.guard.stop)

    def test_semantic_context_survives_transport_splits_without_global_map(self):
        groups=[{'title':f'주제 {i}','description':f'주제 {i} 설명','blocks':[block(i)]} for i in range(24)]
        # One semantic group split over five pages is still one position.
        groups[12]['blocks']=[{**block(i),'id':f'split{i}'} for i in range(30,35)]
        jobs=k1.jobs_for(groups)
        split=[j for j in jobs if j['topicIndex']==12]
        self.assertGreater(len(split),1)
        for job in split:
            context=job['unitContext']
            self.assertEqual(context['current'],{'index':13,'total':24,'title':'주제 12','description':'주제 12 설명'})
            self.assertEqual([x['index']for x in context['before']],list(range(3,13)))
            self.assertEqual([x['index']for x in context['after']],list(range(14,19)))
            crops=[{'page':job['blocks'][0]['page'],'blockIds':[job['blocks'][0]['id']]}]
            payload=k1.teaching_payload(job,crops,{'pageCount':35,'pageCues':['GLOBAL MAP MUST NOT LEAK']},[])
            self.assertEqual(payload['blocks'][0]['text'],job['blocks'][0]['text'])
            self.assertEqual(payload['crops'],crops)
            self.assertNotIn('GLOBAL MAP',json.dumps(payload))
        old=jobs[0]['id'];groups[1]['description']='다른 학습 문맥'
        self.assertNotEqual(k1.jobs_for(groups)[0]['id'],old)

    def test_planner_metadata_survives_repair_and_normalization(self):
        groups=[{'title':'관계','description':'서로 다른 조건과 결과의 관계를 설명한다.','blocks':[block(0)]}]
        class Provider: model='gpt-6-luna';context={}
        def completion(provider,payload,**kw):
            schema=kw['response_format']['json_schema']['schema']['properties']['groups']['items']
            self.assertIn('description',schema['required'])
            return {'groups':[{'title':'관계','description':groups[0]['description'], 'first':0,'last':0,
                'role':'teaching','continuesPrevious':False}]}
        with tempfile.TemporaryDirectory()as tmp,patch('pdf_ai.complete_study_delivery',side_effect=completion),patch.object(k1,'emit'):
            actual,_=k1.plan_groups(Path(tmp),Provider(),groups[0]['blocks'],Path(tmp))
            self.assertEqual(actual[0]['description'],groups[0]['description'])
            self.assertEqual(actual[0]['blocks'][0]['text'],groups[0]['blocks'][0]['text'])
        self.assertLessEqual(len(k1.compact_description('단어 '*60).split()),40)

    def test_namespace_and_legacy_prompts_unchanged(self):
        doc={'documentId':'fixture','fingerprint':'fp','pages':[]}
        self.assertNotEqual(k1.root_path('/tmp',doc,'newest-k1-1-1','gpt-6-luna','document',0),
                            legacy.root_path('/tmp',doc,'new-concept-v99','gpt-6-luna','document',0))
        self.assertNotEqual(k1.planner_identity(),legacy.planner_identity())
        self.assertNotEqual(k1.teaching_identity(),legacy.teaching_identity())
        from pdf_group_transport import RANGE_FORMAT
        self.assertNotIn('description',RANGE_FORMAT['json_schema']['schema']['properties']['groups']['items']['properties'])

    def test_pair_keeps_each_units_context_and_source_text(self):
        from pdf_study_batch_transport import encode
        groups=[{'title':f'주제 {i}','description':f'설명 {i}','blocks':[block(i)]}for i in range(5)]
        jobs=k1.jobs_for(groups)
        requests=[{'job':j,'payload':k1.teaching_payload(j,[],{'pageCount':5},[]),
                   'response_format':k1.STUDY_FORMAT,'images':[]}for j in (jobs[1],jobs[3])]
        wire,_,_,_=encode(requests,max_units=2,max_images=8)
        for key,request in zip(('u0','u1'),requests):
            self.assertEqual(wire['units'][key]['unitContext'],request['payload']['unitContext'])
            self.assertEqual(wire['units'][key]['blocks'][0]['text'],request['payload']['blocks'][0]['text'])

    def test_cost_workload_counts_neighbor_metadata(self):
        from pdf_newest_k1_1_1_cost import workload
        blocks=[block(i)for i in range(3)]
        doc={'pages':[{'nativeText':b['text']}for b in blocks]}
        groups=[{'title':f'주제{i}','description':'','blocks':[b]}for i,b in enumerate(blocks)]
        bare=workload(doc,[1,2,3],blocks=blocks,jobs=k1.jobs_for(groups))
        for g in groups:g['description']='관계와 조건을 연결해서 설명하는 단락이에요. '*15
        contextual=workload(doc,[1,2,3],blocks=blocks,jobs=k1.jobs_for(groups))
        self.assertGreater(contextual['region_study']['input'],bare['region_study']['input'])
        self.assertGreater(contextual['summary_reduce']['input'],bare['summary_reduce']['input'])

    def test_generate_overview_before_stream_retained_until_final_and_cached(self):
        blocks=[block(i) for i in range(3)]
        groups=[{'title':f'주제 {i}','description':f'조건 {i}를 비교한다.','blocks':[b]}for i,b in enumerate(blocks)]
        doc={'documentId':'k1-offline','fingerprint':'k1-fixture','pages':[
            {'number':b['page'],'label':str(b['page']),'nativeText':b['text']}for b in blocks]}
        calls=[];events=[];snapshots=[];teaching_started=threading.Event()
        class Provider:
            model='gpt-6-luna';billing=None;context={};ledger={'requests':[]};transport=object()
            def complete(inner,payload,**kw):
                self.assertEqual(payload['task'],'lecture_flow_from_planned_units')
                calls.append('overview')
                self.assertTrue(teaching_started.wait(3),'본문이 흐름 응답을 기다리면 안 돼요.')
                self.assertEqual(len(payload['topics']),3)
                return {'body':'조건을 살펴보고 서로 다른 결과를 비교해요.','topicIds':['k1','k3']}
        provider=Provider()
        def complete(provider,payload,**kw):
            calls.append('teaching')
            teaching_started.set()
            raw=response(payload['blocks'][0]['id'])
            wire=json.dumps(raw,ensure_ascii=False)
            kw['on_study_delta'](wire[:len(wire)//2]);kw['on_study_delta'](wire[len(wire)//2:])
            return raw
        with tempfile.TemporaryDirectory()as tmp,ExitStack()as stack:
            folder=Path(tmp);root=k1.root_path(folder,doc,'newest-k1-1-1',provider.model,'document',0)
            write_json(root/'plan.json',k1.plan_record(groups,[],provider.model,[],blocks=blocks))
            def event(kind,**values):
                events.append((kind,values))
                if kind in ('summary_overview_ready','summary_unit_ready'):
                    snap=json.loads((root/'partial.json').read_text())
                    snapshots.append(snap)
                    if kind=='summary_overview_ready':
                        self.assertEqual(snap['overview']['body'],'조건을 살펴보고 서로 다른 결과를 비교해요.')
            for name,value in {'SOURCE_ID_ALIASES':False,'TRANSPORT_BATCH_UNITS':1,'TRANSPORT_BATCH_ALIASES':False}.items():
                stack.enter_context(patch.object(k1,name,value))
            # Identity is sensitive to transport flags; recompute fixture location.
            root=k1.root_path(folder,doc,'newest-k1-1-1',provider.model,'document',0)
            write_json(root/'plan.json',k1.plan_record(groups,[],provider.model,[],blocks=blocks))
            stack.enter_context(patch.object(k1,'extract_layout',return_value=copy.deepcopy(blocks)))
            stack.enter_context(patch.object(k1,'render_crops',return_value=([],[])))
            stack.enter_context(patch.object(k1,'emit',side_effect=event))
            stack.enter_context(patch('pdf_ai.complete_study_delivery',side_effect=complete))
            stack.enter_context(patch('pdf_ai.run_usage',return_value={}))
            result=k1.generate(folder,doc,provider)
            self.assertTrue(result['processingComplete'],result.get('failedUnits'))
            self.assertEqual(len(result['metrics']['unitTimings']),3)
            self.assertEqual([r['pages'] for r in result['metrics']['unitTimings']],[[1],[2],[3]])
            self.assertEqual(calls.count('overview'),1)
            self.assertEqual(calls.count('teaching'),3)
            self.assertEqual(len(snapshots),4)
            self.assertTrue(any(e[0]=='summary_unit_delta'for e in events))
            self.assertEqual(result['overview']['body'],'조건을 살펴보고 서로 다른 결과를 비교해요.')
            before=list(calls)
            cached=k1.generate(folder,doc,provider)
            self.assertTrue(cached['cacheHit'])
            self.assertEqual(calls,before)

if __name__=='__main__':unittest.main()
