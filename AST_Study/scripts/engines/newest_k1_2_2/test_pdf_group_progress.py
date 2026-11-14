"""Planning progress observes existing work; it must not change AI requests."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pdf_ai
import pdf_new_concept_ver99_study as study


class GroupProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'doc';self.folder.mkdir()
        self.blocks=[{'id':f'source{i}','page':i+1,'kind':'text','text':f'조건 {i}에서 정의와 결과의 관계를 설명해요.',
                      'bbox':[.1,.1,.9,.6],'hasVisual':False,'visualOnly':False}for i in range(6)]
        self.doc={'documentId':'progress-fixture','fingerprint':'same-source',
                  'pages':[{'number':i+1,'label':str(i+1),'nativeText':b['text']}for i,b in enumerate(self.blocks)]}
        self.events=[];self.calls=[];self.hold=threading.Event();self.observed=threading.Event()
        self.provider=SimpleNamespace(model='gpt-6-luna',billing=None,complete=self.complete)

    def emit(self,kind,**value):
        if kind=='study_timeline':
            self.events.append(value)
            if value.get('stage')=='group_progress'and value.get('completedWindows',0)>0:self.observed.set()

    def complete(self,payload,**kwargs):
        self.calls.append(copy.deepcopy((payload,kwargs)))
        if payload['targets'][0]['id']=='source0'and not self.hold.wait(4):raise AssertionError('test did not release first window')
        return {'groups':[{'title':b['id']+' 관계','blockIds':[b['id']],
                           'role':'teaching','continuesPrevious':False}for b in payload['targets']]}

    def patches(self):
        stack=ExitStack()
        for name,value in [('PLAN_WINDOW_BLOCKS',2),('WORKERS',14),('PLAN_TRANSPORT','ids')]:
            stack.enter_context(patch.object(study,name,value))
        stack.enter_context(patch.object(study,'extract',side_effect=lambda *args:copy.deepcopy(self.blocks)))
        stack.enter_context(patch.object(study,'render_crops',side_effect=AssertionError('planning must not render study images')))
        stack.enter_context(patch.object(study,'emit',side_effect=self.emit))
        return stack

    def test_out_of_order_windows_publish_real_progress_before_planning_finishes(self):
        with self.patches(),ThreadPoolExecutor(max_workers=1)as pool:
            future=pool.submit(study.prepare_group_plan,self.folder,self.doc,self.provider)
            try:
                self.assertTrue(self.observed.wait(3),'No progress while a real planner request remains active')
                self.assertFalse(future.done())
                self.assertFalse(any(e['stage']=='group_done'for e in self.events))
                mid=[e for e in self.events if e['stage']=='group_progress'and e['completedWindows']>0]
                self.assertGreater(mid[-1]['percent'],11);self.assertLess(mid[-1]['percent'],20)
            finally:self.hold.set()
            result=future.result(5)
        self.assertTrue(result['groupingConfirmed']);self.assertEqual(len(self.calls),3)
        progress=[e for e in self.events if e['stage']=='group_progress']
        self.assertEqual([e['completedWindows']for e in progress],[0,1,2,3])
        self.assertEqual([e['percent']for e in progress],[11,13,16,19])
        self.assertTrue(all(e['totalWindows']==3 for e in progress))
        self.assertEqual([e['percent']for e in self.events],sorted(e['percent']for e in self.events))
        self.assertEqual(self.events[0]['percent'],3);self.assertEqual(self.events[-1]['percent'],20)
        # Each original target, original two-block boundary context, and request
        # schema/options remain exactly as before; progress adds no requests.
        requests=sorted(self.calls,key=lambda r:r[0]['targets'][0]['id'])
        for n,(payload,options)in enumerate(requests):
            self.assertEqual(payload['task'],'region_groups')
            expected=[study.planning_fragment(b)for b in self.blocks[2*n:2*n+2]]
            self.assertEqual(payload['targets'],expected)
            self.assertEqual(payload['before'],[study.planning_fragment(b)for b in self.blocks[max(0,2*n-2):2*n]])
            self.assertEqual(payload['after'],[study.planning_fragment(b)for b in self.blocks[2*n+2:2*n+4]])
            self.assertEqual(options,dict(max_output=6000,system_prompt=study.PLAN_PROMPT,
                                         response_format=study.PLAN_FORMAT,cache_stable_prefix=True))

    def test_failed_planning_never_reports_completion(self):
        self.provider.complete=lambda *a,**k:(_ for _ in()).throw(pdf_ai.AiResponseError('fixture failure'))
        with self.patches():
            with self.assertRaises(pdf_ai.AiResponseError):study.prepare_group_plan(self.folder,self.doc,self.provider)
        self.assertFalse(any(e['stage']=='group_done'for e in self.events))
        self.assertTrue(all(e['percent']<20 for e in self.events))
        root=study.root_path(self.folder,self.doc,'new-concept-v99',self.provider.model,'document',0)
        self.assertFalse((root/'plan.json').exists())

    def test_cached_plan_reports_ready_without_repeating_paid_work(self):
        self.hold.set()
        with self.patches():
            study.prepare_group_plan(self.folder,self.doc,self.provider)
            calls=len(self.calls);self.events.clear()
            result=study.prepare_group_plan(self.folder,self.doc,self.provider)
        self.assertEqual(len(self.calls),calls)
        self.assertEqual([(e['stage'],e['percent'])for e in self.events],
                         [('split_start',3),('split_done',10),('group_start',11),('group_done',20)])
        self.assertTrue(result['groupingConfirmed'])


if __name__=='__main__':unittest.main()
