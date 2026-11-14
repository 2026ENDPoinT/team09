"""Offline invariants only: no PDF version comparison or paid request."""
import copy
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pdf_newest_k1_1_3 as e
from pdf_newest_k1_1_3_early import EarlyUnits
from test_pdf_newest_k1_1_3 import block,response


def groups(count):
    return [{'title':f'T{i}','description':f'D{i}','blocks':[block(i)]} for i in range(count)]


class EarlyContracts(unittest.TestCase):
    def test_three_opening_contexts_are_identical_after_full_plan(self):
        gs=groups(20)
        for i in range(3):
            prefix=e.jobs_for(gs[:i+2])[i];full=e.jobs_for(gs)[i]
            self.assertEqual(prefix,full)
            c=full['unitContext']
            self.assertNotIn('total',c['current'])
            self.assertEqual([x['index'] for x in c['before']],list(range(1,i+1)))
            self.assertEqual(c['after'],[{'index':i+2,'title':f'T{i+1}','description':f'D{i+1}'}])
        c=e.jobs_for(gs)[12]['unitContext']
        self.assertEqual(c['current']['total'],20)
        self.assertEqual([x['index'] for x in c['before']],list(range(3,13)))
        self.assertEqual([x['index'] for x in c['after']],list(range(14,19)))

    def test_source_order_prefix_unblocks_before_last_window_and_preserves_continuation(self):
        bs=[block(i) for i in range(6)]
        released=threading.Event();seen=[]
        class Provider:model='gpt-6-luna';context={}
        def complete(provider,payload,**kw):
            pages=provider.context['pages']
            if min(pages)>3:
                if not released.wait(2):raise AssertionError('prefix never released before final window')
            return {'groups':[{'title':f'T{n}','description':f'D{n}',
                'first':i,'last':i,'role':'teaching','topicPath':[],
                'continuesPrevious':min(pages)>3 and i==0} for i,n in enumerate(pages)]}
        # context must be thread-local like the actual Provider.
        class LocalProvider:
            model='gpt-6-luna'
            def __init__(self):self.local=threading.local()
            @property
            def context(self):return self.local.value
            @context.setter
            def context(self,v):self.local.value=v
        def prefix(gs,*,final):
            seen.append((copy.deepcopy(gs),final))
            if not final:
                self.assertEqual([g['title'] for g in gs],['T1','T2'])
                released.set()
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'PLAN_WINDOW_BLOCKS',3), \
                patch('pdf_ai.complete_study_delivery',side_effect=complete),patch.object(e,'emit'):
            path=Path(tmp);e.write_json(path/'blocks.json',bs)
            result,_=e.plan_groups(path,LocalProvider(),bs,path,on_prefix=prefix)
        self.assertTrue(seen[0][1] is False and seen[-1][1] is True)
        self.assertEqual(len(result),5)
        self.assertEqual([b['id'] for b in result[2]['blocks']],[bs[2]['id'],bs[3]['id']])
        self.assertEqual(result[:2],seen[0][0])

    def test_coordinator_has_one_owner_and_reuses_futures_at_handoff(self):
        gs=groups(7);bs=[b for g in gs for b in g['blocks']]
        doc={'documentId':'x','fingerprint':'x','pages':[{'number':i+1,'nativeText':''} for i in range(7)]}
        calls=[]
        def work(self,i,job,jobs):calls.append(job['id']);return {'source':job['blocks']}
        with tempfile.TemporaryDirectory() as tmp,patch.object(EarlyUnits,'_warm'), \
                patch.object(EarlyUnits,'_work',work),patch.object(e,'emit'):
            with EarlyUnits(Path(tmp),doc,SimpleNamespace(),'document',0) as early:
                early.start(Path(tmp),bs,0)
                early.offer(gs[:2]);self.assertEqual(len(early.futures),1)
                early.offer(gs[:3]);self.assertEqual(len(early.futures),2)
                early.offer(gs[:4]);self.assertEqual(len(early.futures),3)
                early.offer(gs,final=True);early.bind_final(e.jobs_for(gs))
                for f in early.futures.values():f.result()
                self.assertEqual(len(calls),3)
                self.assertEqual(len(set(calls)),3)

    def test_short_document_releases_last_unit_at_eof_only(self):
        gs=groups(1);doc={'documentId':'x','fingerprint':'x','pages':[{'number':1}]}
        with tempfile.TemporaryDirectory() as tmp,patch.object(EarlyUnits,'_warm'), \
                patch.object(EarlyUnits,'_work',return_value={}),patch.object(e,'emit'):
            with EarlyUnits(Path(tmp),doc,SimpleNamespace(),'document',0) as early:
                early.start(Path(tmp),gs[0]['blocks'],0)
                early.offer(gs);self.assertEqual(len(early.futures),0)
                early.offer(gs,final=True);self.assertEqual(len(early.futures),1)
                early.bind_final(e.jobs_for(gs))

    def test_cost_preparation_does_not_call_paid_planner(self):
        bs=[block(0)];doc={'documentId':'x','fingerprint':'x','pages':[{'number':1}]}
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'extract_layout',return_value=bs), \
                patch.object(e,'reading_plan',return_value={'totalCostEstimateUsd':.1}), \
                patch.object(e,'pending_originals_for_plan',return_value={}), \
                patch.object(e,'plan_groups',side_effect=AssertionError('paid grouping in cost stage')):
            result=e.prepare_group_plan(Path(tmp),doc,SimpleNamespace(model='gpt-6-luna'))
            self.assertTrue(result['groupingDeferredToGeneration'])

class FullEarlyPipeline(unittest.TestCase):
    def test_early_output_before_tail_plan_and_no_duplicate_generation(self):
        import json
        from contextlib import ExitStack
        bs=[block(i) for i in range(8)]
        doc={'documentId':'early-full','fingerprint':'fixture','pages':[
            {'number':b['page'],'label':str(b['page']),'nativeText':b['text']} for b in bs]}
        early_output=threading.Event();tail_complete=threading.Event();calls=[];events=[]
        class Provider:
            model='gpt-6-luna';billing=None;transport=object()
            def __init__(self):self.local=threading.local();self.ledger={'requests':[]}
            @property
            def context(self):return getattr(self.local,'context',{})
            @context.setter
            def context(self,value):self.local.context=value
            def complete(self,payload,**kw):
                return {'body':'앞의 조건을 살피고 뒤의 조건을 비교해요.','topicIds':['k1','k8']}
        provider=Provider()
        def complete(provider,payload,**kw):
            if provider.context['kind']=='region_plan':
                pages=provider.context['pages']
                if min(pages)>4:
                    if not early_output.wait(3):raise AssertionError('early output waited for whole plan')
                    tail_complete.set()
                return {'groups':[{'title':f'T{n}','description':f'D{n}','first':i,'last':i,
                    'role':'teaching','topicPath':[],'continuesPrevious':False} for i,n in enumerate(pages)]}
            calls.append(payload['blocks'][0]['id'])
            raw=response(payload['blocks'][0]['id'])
            kw['on_study_delta'](json.dumps(raw,ensure_ascii=False))
            return raw
        def emit(kind,**values):
            events.append((kind,values))
            if kind=='summary_unit_delta' and values.get('summary') and not tail_complete.is_set():early_output.set()
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            for name,value in {'SOURCE_ID_ALIASES':False,'TRANSPORT_BATCH_ALIASES':False,'PLAN_WINDOW_BLOCKS':4}.items():
                stack.enter_context(patch.object(e,name,value))
            stack.enter_context(patch.object(e,'extract_layout',return_value=copy.deepcopy(bs)))
            stack.enter_context(patch.object(e,'render_crops',return_value=([],[])))
            stack.enter_context(patch.object(EarlyUnits,'_warm'))
            stack.enter_context(patch.object(e,'emit',side_effect=emit))
            stack.enter_context(patch('pdf_ai.complete_study_delivery',side_effect=complete))
            stack.enter_context(patch('pdf_ai.run_usage',return_value={}))
            result=e.generate(Path(tmp),doc,provider)
            self.assertTrue(early_output.is_set())
            self.assertTrue(result['processingComplete'],result['failedUnits'])
            self.assertEqual(len(calls),8)
            self.assertEqual(len(set(calls)),8)
            self.assertEqual(result['earlyStart']['earlyTasks'],3)
            self.assertEqual(result['totalUnits'],8)
            self.assertEqual([v['unit'] for k,v in events if k=='summary_unit_ready'],list(range(1,9)))

if __name__=='__main__':unittest.main()
