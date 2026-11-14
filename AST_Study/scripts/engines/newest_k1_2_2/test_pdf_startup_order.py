"""No-network regressions for source-ordered previews and bounded startup work.

Reuse the existing PDF-free fixture by composition, never by inheritance: test
discovery must not rerun every CropPipelineTests test through this module.
"""
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import test_pdf_speed_pipeline as fixture_module
import pdf_new_concept_ver99_study as study


class _Probe:
    def __init__(self):
        self.condition=threading.Condition()
        self.submitted=[]
        self.started=[]
        self.returned=[]
        self.ready=[]
        self.exports=[]
        self.writes=[]
        self.active=0
        self.peak=0

    def change(self,callback):
        with self.condition:
            callback()
            self.condition.notify_all()

    def wait_for(self,predicate,timeout=4):
        with self.condition:
            return self.condition.wait_for(predicate,timeout)

    def snapshot(self,name):
        with self.condition:
            return copy.deepcopy(getattr(self,name))


def _visible_sources(result):
    return {e['sourceId'] for section in result.get('sections',[])
            for part in section.get('parts',[])for e in part.get('evidence',[])
            if e.get('sourceId','').startswith('source')}


class StartupOrderTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.CropPipelineTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.worker_limit=14

    def configure(self,count,*,weighted=False):
        self.fixture.set_unit_count(count)
        if weighted:
            # A later confirmed short preview and a large tail would have
            # displaced both leading source units under the old schedule.
            for i,b in enumerate(self.fixture.blocks):
                b['text']='정의와 조건을 원문 순서대로 보존하는 설명이에요. '*(70+i)
            self.fixture.blocks[2]['text']+='추가 조건에 관한 설명이에요. '*90
            self.fixture.blocks[7]['text']='짧지만 독립적인 정의와 조건을 설명해요. '*4
            self.assertGreater(study.work_weight([self.fixture.blocks[0]]),1600)
            self.assertGreater(study.work_weight([self.fixture.blocks[1]]),1600)
            self.assertLessEqual(study.work_weight([self.fixture.blocks[7]]),1600)
            self.assertGreater(study.work_weight([self.fixture.blocks[7]]),120)
            self.fixture.document['pages']=[{'number':i+1,'label':str(i+1),'nativeText':b['text']}
                                            for i,b in enumerate(self.fixture.blocks)]

    @staticmethod
    def request_sources(payload):
        units=list(payload['units'].values())if payload.get('task')=='region_teaching_batch'else[payload]
        return tuple(unit['blocks'][0]['id']for unit in units)

    def response(self,payload):
        if payload.get('task')=='region_teaching_batch':
            return {name:self.fixture.modern_reply(unit)for name,unit in payload['units'].items()}
        return self.fixture.modern_reply(payload)

    @contextmanager
    def running(self,complete,*,renderer=None,releases=(),wire_options=None):
        probe=_Probe();outcome={};real_executor=study.ThreadPoolExecutor
        real_export=study.hierarchy.export
        real_write=study.write_json
        titles={g['title']:g['blocks'][0]['id']for g in self.fixture.groups}

        class ObservedExecutor(real_executor):
            def submit(executor,fn,*args,**kwargs):
                if getattr(fn,'__name__','')in('work_batch','dispatch'):
                    # Count submitted request futures, including anything
                    # queued but not yet inside the FakeProvider.
                    probe.change(lambda:probe.submitted.append(tuple(args[0])))
                return super().submit(fn,*args,**kwargs)

        def observed_complete(payload,**kwargs):
            sources=self.request_sources(payload)
            def entered():
                probe.started.append(sources);probe.active+=1
                probe.peak=max(probe.peak,probe.active)
            probe.change(entered)
            try:
                return complete(payload,probe,**kwargs)
            finally:
                def returned():
                    probe.active-=1;probe.returned.append(sources)
                probe.change(returned)

        def exported(cache,result):
            real_export(cache,result)
            hierarchy=json.loads((Path(cache)/'hierarchy.json').read_text())
            hierarchy_sources={titles[node['title']]for node in hierarchy.get('nodes',[])
                               if node.get('title')in titles and node.get('sourceHeading')is not True}
            snapshot={'sources':_visible_sources(result),'hierarchySources':hierarchy_sources}
            probe.change(lambda:probe.exports.append(snapshot))

        def ready(fields):
            partial=json.loads((Path(fields['path']).parent/'partial.json').read_text())
            snapshot={'unit':fields['unit'],'partialSources':_visible_sources(partial)}
            probe.change(lambda:probe.ready.append(snapshot))

        def written(path,value):
            real_write(path,value)
            probe.change(lambda:probe.writes.append(str(path)))

        def run():
            try:
                outcome['value']=self.fixture.run_pipeline(renderer or(lambda _:None),
                    complete=observed_complete,emit=ready,crop_result=self.fixture.batch_crop,
                    worker_limit=self.fixture.worker_limit,
                    wire_options={'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8,
                                  'TRANSPORT_BALANCED':True,**(wire_options or{})})
            except BaseException as error:
                outcome['error']=error
            finally:
                probe.change(lambda:outcome.update(finished=True))

        with patch.object(study,'ThreadPoolExecutor',ObservedExecutor), \
             patch.object(study.hierarchy,'export',side_effect=exported), \
             patch.object(study,'write_json',side_effect=written):
            thread=threading.Thread(target=run,name='startup-fixture',daemon=True)
            thread.start()
            try:
                yield probe,outcome
            finally:
                for event in releases:event.set()
                thread.join(timeout=6)
                self.assertFalse(thread.is_alive(),'Fixture did not settle after releasing all fake requests')
            if 'error'in outcome:raise outcome['error']

    def test_first_two_requests_are_source_singletons_despite_later_tiny_preview(self):
        self.configure(24,weighted=True)
        with self.running(lambda payload,probe,**kw:self.response(payload))as(probe,outcome):
            self.assertTrue(probe.wait_for(lambda:outcome.get('finished')))
        result,_=outcome['value']
        self.assertTrue(result['processingComplete'])
        self.assertEqual(probe.started[:2],[('source0',),('source1',)])
        self.assertEqual(probe.submitted[:2],[(0,),(1,)])
        self.assertEqual([r['unit']for r in probe.ready[:2]],[1,2])

    def test_source1_and_tail_finishing_first_cannot_leak_into_partial_export_or_ready(self):
        self.configure(5);front0=threading.Event()
        def complete(payload,probe,**kwargs):
            if 'source0'in self.request_sources(payload):
                self.assertTrue(front0.wait(4))
            return self.response(payload)
        with self.running(complete,releases=(front0,))as(probe,outcome):
            self.assertTrue(probe.wait_for(lambda:len(probe.returned)>=4))
            self.assertFalse(probe.wait_for(lambda:bool(probe.ready),timeout=.1),
                             'A later source was announced while source0 was blocked')
            self.assertTrue(all(not e['sources']and not e['hierarchySources']for e in probe.exports))
            # Even without a ready event, a prematurely written partial file
            # would be visible to recover/export consumers.
            for path in self.fixture.folder.glob('generated/new-concept-v99/*/partial.json'):
                self.assertEqual(_visible_sources(json.loads(path.read_text())),set())
            front0.set()
            self.assertTrue(probe.wait_for(lambda:outcome.get('finished')))
        self.assertTrue(outcome['value'][0]['processingComplete'])
        self.assertEqual([r['unit']for r in probe.ready[:2]],[1,2])
        self.assertEqual(set(r['unit']for r in probe.ready),set(range(1,6)))

    def test_front0_publishes_immediately_but_tail_waits_for_front1(self):
        self.configure(5);front0=threading.Event();front1=threading.Event()
        def complete(payload,probe,**kwargs):
            sources=self.request_sources(payload)
            if 'source0'in sources:self.assertTrue(front0.wait(4))
            if 'source1'in sources:self.assertTrue(front1.wait(4))
            return self.response(payload)
        with self.running(complete,releases=(front0,front1))as(probe,outcome):
            self.assertTrue(probe.wait_for(lambda:len(probe.returned)>=3))
            front0.set()
            self.assertTrue(probe.wait_for(lambda:bool(probe.ready)))
            self.assertEqual(probe.ready[0],{'unit':1,'partialSources':{'source0'}})
            self.assertFalse(probe.wait_for(lambda:len(probe.ready)>1,timeout=.1))
            self.assertTrue(all(e['sources']<={'source0'}and e['hierarchySources']<={'source0'}
                                for e in probe.exports))
            front1.set()
            self.assertTrue(probe.wait_for(lambda:outcome.get('finished')))
        self.assertTrue(outcome['value'][0]['processingComplete'])
        self.assertEqual([r['unit']for r in probe.ready[:2]],[1,2])

    def test_failed_first_unit_releases_the_publication_gate_without_paid_retry(self):
        self.configure(5)
        def complete(payload,probe,**kwargs):
            if 'source0'in self.request_sources(payload):
                raise fixture_module.ai.AiResponseError('Fixture first source failed after send')
            return self.response(payload)
        with self.running(complete)as(probe,outcome):
            self.assertTrue(probe.wait_for(lambda:outcome.get('finished')),
                            'A failed first source permanently held later results')
        result,_=outcome['value']
        self.assertFalse(result['processingComplete'])
        self.assertEqual(len(result['failedUnits']),1)
        self.assertEqual(sum('source0'in ids for ids in probe.started),1)
        self.assertEqual([r['unit']for r in probe.ready[:1]],[2])
        self.assertEqual(set(r['unit']for r in probe.ready),{2,3,4,5})
        self.assertEqual(_visible_sources(result),{'source1','source2','source3','source4'})

    def test_cached_front_two_do_not_receive_extra_startup_slots(self):
        self.configure(24)
        _,cache=self.fixture.run_pipeline(lambda _:self.fail('Cached warmup must not render'),
            complete=lambda *a,**kw:self.fail('Cached warmup must not call an API'),
            cached=True,worker_limit=14)
        keep={f'response-{job["id"]}.json'for job in study.jobs_for(self.fixture.groups)[:2]}
        # This temporary fixture alone is edited. Leave exactly two paid raw
        # caches; all prior presentation files are rebuilt normally on resume.
        for path in cache.rglob('*'):
            if path.is_file()and path.name not in keep:path.unlink()
        study.latest_path(self.fixture.folder,'new-concept-v99','document',0).unlink(missing_ok=True)
        self.fixture.events.clear();release=threading.Event()
        def complete(payload,probe,**kwargs):
            self.assertTrue(release.wait(4))
            return self.response(payload)
        with self.running(complete,releases=(release,),
                          wire_options={'TRANSPORT_BATCH_UNITS':1,'TRANSPORT_BATCH_IMAGES':4})as(probe,outcome):
            self.assertTrue(probe.wait_for(lambda:len(probe.started)>=14))
            self.assertFalse(probe.wait_for(lambda:len(probe.submitted)>14,timeout=.1))
            self.assertEqual(probe.peak,14)
            self.assertFalse(any({'source0','source1'}&set(ids)for ids in probe.started))
            release.set()
            self.assertTrue(probe.wait_for(lambda:outcome.get('finished')))
        result,_=outcome['value']
        self.assertTrue(result['processingComplete'])
        self.assertEqual(len(probe.started),22)
        self.assertEqual(probe.peak,14)

    def test_sixteen_startup_requests_retire_to_fourteen_before_refilling(self):
        self.configure(24);release={f'source{i}':threading.Event()for i in range(24)}
        def complete(payload,probe,**kwargs):
            source=self.request_sources(payload)[0]
            self.assertTrue(release[source].wait(4))
            return self.response(payload)
        with self.running(complete,releases=tuple(release.values()),
                          wire_options={'TRANSPORT_BATCH_UNITS':1,'TRANSPORT_BATCH_IMAGES':4})as(probe,outcome):
            self.assertTrue(probe.wait_for(lambda:len(probe.started)>=16),
                            'Fresh front0/front1 did not get their two bounded startup slots')
            self.assertEqual(len(probe.submitted),16)
            self.assertEqual(probe.peak,16)
            release['source0'].set()
            self.assertTrue(probe.wait_for(lambda:any(r['unit']==1 for r in probe.ready)))
            self.assertFalse(probe.wait_for(lambda:len(probe.submitted)>16,timeout=.1))
            release['source1'].set()
            self.assertTrue(probe.wait_for(lambda:any(r['unit']==2 for r in probe.ready)))
            self.assertFalse(probe.wait_for(lambda:len(probe.submitted)>16,timeout=.1))
            third=next(ids[0]for ids in probe.started if ids[0]not in('source0','source1'))
            release[third].set()
            self.assertTrue(probe.wait_for(lambda:len(probe.started)==17),
                            'Dropping from14to13 pending requests did not refill the steady pool')
            self.assertEqual(len(probe.submitted),17)
            self.assertEqual(probe.active,14)
            self.assertFalse(probe.wait_for(lambda:len(probe.submitted)>17,timeout=.1))
            for event in release.values():event.set()
            self.assertTrue(probe.wait_for(lambda:outcome.get('finished')))
        self.assertTrue(outcome['value'][0]['processingComplete'])
        self.assertEqual(len(probe.started),24)
        self.assertEqual(probe.peak,16)

    def test_small_worker_configuration_stays_at_three_even_during_startup(self):
        self.configure(7);self.fixture.worker_limit=3;release=threading.Event()
        def complete(payload,probe,**kwargs):
            self.assertTrue(release.wait(4));return self.response(payload)
        with self.running(complete,releases=(release,),
                          wire_options={'TRANSPORT_BATCH_UNITS':1,'TRANSPORT_BATCH_IMAGES':4})as(probe,outcome):
            self.assertTrue(probe.wait_for(lambda:len(probe.started)>=3))
            self.assertFalse(probe.wait_for(lambda:len(probe.submitted)>3,timeout=.1))
            release.set()
            self.assertTrue(probe.wait_for(lambda:outcome.get('finished')))
        self.assertTrue(outcome['value'][0]['processingComplete'])
        self.assertEqual(probe.peak,3)

    def test_resume_replaces_stale_tail_only_partial_before_front_responses_arrive(self):
        self.configure(5)
        _,cache=self.fixture.run_pipeline(lambda _:self.fail('Cached fixture must not render'),
            complete=lambda *a,**kw:self.fail('Cached fixture must not call an API'),
            cached=True,worker_limit=14,
            wire_options={'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8,
                          'TRANSPORT_BALANCED':True})
        jobs=study.jobs_for(self.fixture.groups)
        keep={f'response-{job["id"]}.json'for job in jobs[2:]}
        preserved={cache/name:(cache/name).read_bytes()for name in keep}
        for path in cache.rglob('*'):
            if path.is_file()and path.name not in keep:path.unlink()
        study.latest_path(self.fixture.folder,'new-concept-v99','document',0).unlink(missing_ok=True)
        # A historical scheduler could leave this presentation even though
        # only the later paid responses are available. No raw reply is edited.
        fixture_module.write_json(cache/'partial.json',{'processingComplete':False,
            'sections':[{'title':'오래된 뒤쪽 결과','parts':[
                {'title':'tail','body':'뒤쪽에 먼저 완료된 내용이에요.',
                 'evidence':[{'sourceId':'source2'}]}]}]})
        self.assertEqual(_visible_sources(json.loads((cache/'partial.json').read_text())),{'source2'})
        release=threading.Event()
        def complete(payload,probe,**kwargs):
            self.assertTrue(set(self.request_sources(payload))<={'source0','source1'})
            self.assertTrue(release.wait(4))
            return self.response(payload)
        with self.running(complete,releases=(release,))as(probe,outcome):
            self.assertTrue(probe.wait_for(lambda:len(probe.started)>=2))
            self.assertEqual(_visible_sources(json.loads((cache/'partial.json').read_text())),set())
            self.assertEqual(probe.ready,[])
            self.assertTrue(probe.exports,'The stale projection was not re-exported')
            self.assertTrue(all(not e['sources']and not e['hierarchySources']for e in probe.exports))
            for path,before in preserved.items():self.assertEqual(path.read_bytes(),before)
            release.set()
            self.assertTrue(probe.wait_for(lambda:outcome.get('finished')))
        self.assertTrue(outcome['value'][0]['processingComplete'])
        self.assertEqual(probe.started,[('source0',),('source1',)])
        self.assertEqual([r['unit']for r in probe.ready],list(range(1,6)))
        for path,before in preserved.items():self.assertEqual(path.read_bytes(),before)

    def test_cancel_keeps_unpublished_tail_paid_raw_for_free_ordered_resume(self):
        self.configure(4);release_front=threading.Event()
        jobs=study.jobs_for(self.fixture.groups)
        tail_ids={job['id']for job in jobs[2:]}
        def cancelled(payload,probe,**kwargs):
            if {'source0','source1'}&set(self.request_sources(payload)):
                self.assertTrue(release_front.wait(4))
                raise InterruptedError('Fixture front request observes cancellation')
            return self.response(payload)
        outcome=None;probe=None;preserved={}
        with self.assertRaises(InterruptedError):
            with self.running(cancelled,releases=(release_front,))as(probe,outcome):
                def durable_tail():
                    return {Path(path).stem.removeprefix('response-')for path in probe.writes
                            if Path(path).name.startswith('response-')}>=tail_ids
                self.assertTrue(probe.wait_for(durable_tail),
                                'A completed tail reply was not durably saved before cancellation')
                self.assertEqual(probe.ready,[])
                self.assertTrue(all(not e['sources']and not e['hierarchySources']for e in probe.exports))
                paths=[Path(path)for path in probe.writes
                       if Path(path).name in {f'response-{key}.json'for key in tail_ids}]
                preserved={path:path.read_bytes()for path in paths}
                self.assertEqual(len(preserved),2)
                (self.fixture.folder/'cancel').write_text('cancel',encoding='utf-8')
                release_front.set()
                self.assertTrue(probe.wait_for(lambda:outcome.get('finished')))
        self.assertIsInstance(outcome['error'],InterruptedError)
        self.assertEqual(probe.ready,[])
        for path,before in preserved.items():self.assertEqual(path.read_bytes(),before)
        (self.fixture.folder/'cancel').unlink()
        def resumed(payload,probe,**kwargs):
            self.assertTrue(set(self.request_sources(payload))<={'source0','source1'},
                            'Resume tried to buy an already durable tail reply again')
            return self.response(payload)
        def render(source):
            self.assertIn(source,{'source0','source1'},'Cached tail was needlessly rendered again')
        with self.running(resumed,renderer=render)as(resume,outcome):
            self.assertTrue(resume.wait_for(lambda:outcome.get('finished')))
        self.assertTrue(outcome['value'][0]['processingComplete'])
        self.assertEqual(resume.started,[('source0',),('source1',)])
        self.assertEqual([r['unit']for r in resume.ready],list(range(1,5)))
        for path,before in preserved.items():self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
