"""Transport fixtures check observable pipelining without PDF data or networking."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_new_concept_ver99_study as study
from pdf_pipeline import write_json


class FakeProvider:
    model = 'gpt-6-luna'
    billing = None

    def __init__(self, complete):
        self.ledger = {'requests': []}
        self.context = {}
        self._complete = complete

    def complete(self, payload, **kwargs):
        return self._complete(payload, **kwargs)


class CropPipelineTests(unittest.TestCase):
    def test_semantic_generation_has_a_hard_fourteen_request_ceiling(self):
        with patch.object(study, 'WORKERS', 128), patch.dict('os.environ', {'SYNESIS_SUMMARY_SERIAL':'0'}):
            self.assertEqual(study.study_workers(), 14)
        with patch.object(study, 'WORKERS', 14), patch.dict('os.environ', {'SYNESIS_SUMMARY_SERIAL':'1'}):
            self.assertEqual(study.study_workers(), 1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.lock = threading.Lock()
        self.events = []
        self.blocks = [
            {'id': f'source{i}', 'page': i+1, 'bbox': [.1, .1, .9, .7],
             'kind': 'text', 'hasVisual': False, 'planRole': 'teaching',
             'text': f'제{i+1} 주제의 정의와 조건이에요. ' + '다른 조건에서는 결과가 달라져요. '*8}
            for i in range(3)]
        self.groups = [{'title': f'주제{i+1}', 'blocks': [block]}
                       for i, block in enumerate(self.blocks)]
        self.document = {'documentId': 'synthetic-pipeline', 'fingerprint': 'fixture-only-v1',
                         'pages': [{'number': i+1, 'label': str(i+1), 'nativeText': block['text']}
                                   for i, block in enumerate(self.blocks)]}

    def record(self, kind, source=None):
        with self.lock:
            self.events.append((kind, source))

    def reply(self, source):
        return {'concepts': [{'title': f'{source}의 원리',
                             'definition': f'{source}는 조건에 따라 작동하는 원리예요.',
                             'explanation': f'{source}는 조건이 달라지면 결과도 달라져요.',
                             'easyExplanation': '같은 조건을 먼저 비교해요.',
                             'blockIds': [source], 'standardKnowledgeUsed': False}],
                'tables': [], 'sequences': [], 'excludedBlocks': [], 'uncertainBlocks': []}

    def run_pipeline(self, renderer, complete=None, emit=None, cached=False,
                     provider=None, real_overview=False, crop_result=None, wire_options=None,
                     worker_limit=3):
        def default_complete(payload, **kwargs):
            source = payload['blocks'][0]['id']
            self.record('api', source)
            return self.reply(source)

        def crop(folder, blocks, cache):
            source = blocks[0]['id']
            self.record('crop_start', source)
            renderer(source)
            self.record('crop_done', source)
            if crop_result:
                return crop_result(blocks)
            return [], [{'page': blocks[0]['page'], 'blockIds': [source]}]

        def event(kind, **fields):
            if kind == 'summary_unit_ready':
                self.record('unit_ready', fields['unit'])
                if emit:
                    emit(fields)

        provider = provider or FakeProvider(complete or default_complete)
        with ExitStack() as stack:
            # This guard is also effective if someone later accidentally adds a
            # real provider call to this fixture. No credential/data files exist.
            stack.enter_context(patch.object(socket.socket, 'connect',
                                             side_effect=AssertionError('Network forbidden in pipeline regression')))
            stack.enter_context(patch.object(study, 'PIPELINE_CROPS', True))
            stack.enter_context(patch.object(study, 'WORKERS', worker_limit))
            # These fixtures intentionally use canonical legacy replies; pin the
            # wire format independently of whichever production variant wins.
            for name, value in {'SOURCE_ID_ALIASES': False, 'OWNED_TEACHING': False,
                                'IMAGE_SOURCE_LABELS': False,'TRANSPORT_BATCH_UNITS':1,
                                'TRANSPORT_BATCH_IMAGES':4,'TRANSPORT_BALANCED':False,
                                'TRANSPORT_BATCH_ALIASES':False,
                                'TRANSPORT_BATCH_ALIAS_POOL':'exact',
                                **(wire_options or {})}.items():
                stack.enter_context(patch.object(study, name, value))
            stack.enter_context(patch.dict('os.environ', {'SYNESIS_SUMMARY_SERIAL': '0'}))
            stack.enter_context(patch.object(study, 'extract', return_value=copy.deepcopy(self.blocks)))
            stack.enter_context(patch.object(study, 'render_crops', side_effect=crop))
            stack.enter_context(patch.object(study, 'emit', side_effect=event))
            if not real_overview:
                stack.enter_context(patch('pdf_outline.overview', return_value={
                    'title': '이 강의의 흐름', 'body': '세 주제를 차례로 살펴요.',
                    'evidence': [], 'visualPages': [], 'standardKnowledgeUsed': False}))
            cache = study.root_path(self.folder, self.document, 'new-concept-v99', provider.model, 'document', 0)
            cache.mkdir(parents=True,exist_ok=True)
            write_json(cache/'plan.json', {'groups': self.groups, 'warnings': [],
                                           'plannerIdentity': study.planner_identity(provider.model),
                                           'status': 'confirmed', 'headings': []})
            if cached:
                for job in study.jobs_for(self.groups):
                    write_json(cache/f'response-{job["id"]}.json', self.reply(job['blocks'][0]['id']))
            result = study.generate(self.folder, self.document, provider)
        return result, cache

    def test_bucketed_aliases_restore_canonical_caches_without_changing_learner_text(self):
        schemas=[]
        def complete(payload, **kwargs):
            self.assertEqual(payload['blocks'][0]['id'],'a')
            self.assertEqual(payload['crops'][0]['blockIds'],['a'])
            schemas.append(kwargs['response_format'])
            return self.reply('a')
        result,cache=self.run_pipeline(lambda _:None,complete=complete,
            wire_options={'SOURCE_ID_ALIASES':True,'SOURCE_ALIAS_POOL_SIZE':32})
        self.assertTrue(result['processingComplete'])
        self.assertEqual(len(schemas),3)
        self.assertEqual(schemas[0],schemas[1])
        self.assertEqual(schemas[1],schemas[2])
        for job in study.jobs_for(self.groups):
            raw=json.loads((cache/f'response-{job["id"]}.json').read_text())
            self.assertEqual(raw['concepts'][0]['blockIds'],[job['blocks'][0]['id']])
            # Only structured IDs change, even when a prose string resembles one.
            self.assertEqual(raw['concepts'][0]['definition'],self.reply('a')['concepts'][0]['definition'])

    def test_unused_pool_alias_fails_closed_without_retry_or_canonical_cache(self):
        calls=[]
        def complete(payload, **kwargs):
            calls.append(payload)
            return self.reply('af')
        result,cache=self.run_pipeline(lambda _:None,complete=complete,
            wire_options={'SOURCE_ID_ALIASES':True,'SOURCE_ALIAS_POOL_SIZE':32})
        self.assertFalse(result['processingComplete'])
        self.assertEqual(len(calls),3)
        self.assertEqual(len(result['failedUnits']),3)
        self.assertTrue(all(x['error']=='SourceAliasError' for x in result['failedUnits']))
        self.assertEqual(list(cache.glob('response-*.json')),[])

    def test_alias_bucket_changes_wire_cache_only_not_teaching_or_scheduling_identity(self):
        with patch.object(study,'SOURCE_ID_ALIASES',True),patch.object(study,'SOURCE_ALIAS_POOL_SIZE',32):
            before=study.identity(self.document,'new-concept-v99','gpt-6-luna','document',0)
            contract=study.teaching_identity()
            with patch.object(study,'WORKERS',8):
                self.assertEqual(before,study.identity(self.document,'new-concept-v99','gpt-6-luna','document',0))
            with patch.object(study,'SOURCE_ALIAS_POOL_SIZE',64):
                self.assertNotEqual(before,study.identity(self.document,'new-concept-v99','gpt-6-luna','document',0))
                self.assertEqual(contract,study.teaching_identity())

    def set_unit_count(self,count):
        self.blocks=[{**self.blocks[0],'id':f'source{i}','page':i+1} for i in range(count)]
        self.groups=[{'title':f'독립 주제{i}','blocks':[b]} for i,b in enumerate(self.blocks)]
        self.document['pages']=[{'number':i+1,'label':str(i+1),'nativeText':b['text']}
                                for i,b in enumerate(self.blocks)]

    def modern_reply(self,payload):
        source=payload['blocks'][0]['id']
        return {'concepts':[{'title':payload['titleHint'],
            'sourceSetup':{'observedRelations':[],'boundaryChecks':[],'interpretation':''},
            'segments':[{'kind':'definition','text':'조건에 따라 결과가 달라지는 원리예요.','blockIds':[source]},
                {'kind':'explanation','text':'서로 다른 조건에서 결과가 어떻게 달라지는지 비교해요.','blockIds':[source]},
                {'kind':'easyExplanation','text':'같은 조건을 먼저 확인하고 달라진 조건을 살펴봐요.','blockIds':[source]}],
            'standardKnowledgeUsed':False}], 'tables':[],'sequences':[],
            'excludedBlocks':[],'uncertainBlocks':[]}

    def batch_crop(self,blocks):
        return [{'width':20,'height':20,'data':'data:image/png;base64,fixture'}],[
            {'page':blocks[0]['page'],'blockIds':[b['id'] for b in blocks]}]

    def test_balanced_packing_preserves_request_parallelism_and_original_units(self):
        for n,expected in ((8,8),(20,15),(34,15),(134,35)):
            self.set_unit_count(n)
            for i,job in enumerate(self.groups):
                job['blocks'][0]['text']='조건과 정의에 대한 원문이에요. '*(n-i)
            jobs=study.jobs_for(self.groups)
            order=study.generation_schedule(range(n),jobs)
            with patch.object(study,'TRANSPORT_BATCH_UNITS',4), \
                 patch.object(study,'TRANSPORT_BATCH_IMAGES',16), \
                 patch.object(study,'TRANSPORT_BALANCED',True), \
                 patch.object(study,'WORKERS',14), \
                 patch.dict('os.environ',{'SYNESIS_SUMMARY_SERIAL':'0'}):
                batches=study.transport_batches(order,jobs)
            self.assertEqual(len(batches),expected)
            self.assertEqual(batches[0],[order[0]])
            self.assertEqual(sorted(i for b in batches for i in b),list(range(n)))
            self.assertTrue(all(len(b)<=4 for b in batches))
            for group in batches:
                # Source order is now kept inside an envelope instead of
                # pairing the heaviest reply with an unrelated tail unit.
                self.assertEqual(group,sorted(group))

    def test_source_neighbor_pairing_avoids_distant_units_without_losing_workers_or_images(self):
        self.set_unit_count(36);jobs=study.jobs_for(self.groups)
        order=[0,1]+list(reversed(range(2,36)))
        with patch.object(study,'TRANSPORT_BATCH_UNITS',2),patch.object(study,'TRANSPORT_BATCH_IMAGES',8),patch.object(study,'WORKERS',14):
            groups=study.transport_batches(order,jobs,preview_indices=[0,1])
        self.assertEqual(len(groups),19)
        self.assertEqual(sorted(i for g in groups for i in g),list(range(36)))
        self.assertTrue(all(len(g)<=2 for g in groups))
        for g in groups:
            pages=[{b['page']for b in jobs[i]['blocks']}for i in g]
            if len(g)>1:self.assertLessEqual(min(abs(a-b)for a in pages[0]for b in pages[1]),1)

    def test_balanced_packing_never_exceeds_original_image_envelope(self):
        self.set_unit_count(34);jobs=study.jobs_for(self.groups)
        def runs(blocks):return [None]*4
        with patch.object(study,'TRANSPORT_BATCH_UNITS',4), \
             patch.object(study,'TRANSPORT_BATCH_IMAGES',8), \
             patch.object(study,'TRANSPORT_BALANCED',True), \
             patch.object(study,'WORKERS',14), \
             patch.object(study,'crop_runs',side_effect=runs):
            batches=study.transport_batches(list(range(34)),jobs)
        self.assertTrue(all(len(b)<=2 for b in batches))
        self.assertEqual(sorted(i for b in batches for i in b),list(range(34)))

    def test_independent_pairs_fill_fourteen_requests_not_seven_and_save_every_unit(self):
        self.set_unit_count(48)
        state={'active':0,'peak':0,'calls':0};full=threading.Event()
        def complete(payload,**kwargs):
            with self.lock:
                state['active']+=1;state['calls']+=1
                state['peak']=max(state['peak'],state['active'])
                if state['active']==14:full.set()
            try:
                if payload['task']=='region_teaching_batch':
                    self.assertEqual(kwargs['max_output'],36000)
                    self.assertEqual(kwargs['image_limit'],8)
                    self.assertTrue(full.wait(3),'Fourteen batch requests must run together')
                    return {key:self.modern_reply(unit) for key,unit in payload['units'].items()}
                return self.modern_reply(payload)
            finally:
                with self.lock:state['active']-=1
        result,cache=self.run_pipeline(lambda _:None,complete=complete,crop_result=self.batch_crop,
            worker_limit=14,wire_options={'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8})
        self.assertTrue(result['processingComplete'])
        self.assertEqual(state['peak'],14)
        self.assertEqual(state['calls'],25)
        self.assertEqual(len(list(cache.glob('response-*.json'))),48)
        self.assertEqual(len([e for e in self.events if e[0]=='unit_ready']),48)

    def test_bad_batch_child_keeps_valid_peers_and_never_retries_paid_request(self):
        self.set_unit_count(5);calls=[];bad=[]
        def complete(payload,**kwargs):
            calls.append(payload)
            if payload['task']!='region_teaching_batch':return self.modern_reply(payload)
            raw={key:self.modern_reply(unit) for key,unit in payload['units'].items()}
            if not bad:
                bad.append(payload['units']['u1']['blocks'][0]['id'])
                raw['u1']['concepts'][0]['segments'][0]['blockIds']=[
                    payload['units']['u0']['blocks'][0]['id']]
            return raw
        result,cache=self.run_pipeline(lambda _:None,complete=complete,crop_result=self.batch_crop,
            wire_options={'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8})
        self.assertFalse(result['processingComplete'])
        self.assertEqual(len(calls),4)  # Two opening singles, then a pair and single.
        self.assertEqual(len(result['failedUnits']),1)
        self.assertEqual(len(list(cache.glob('response-*.json'))),4)
        self.assertEqual(len([e for e in self.events if e[0]=='unit_ready']),4)

    def test_resume_recovers_paid_batch_peer_and_blocks_repacking_invalid_child(self):
        self.set_unit_count(4)
        owner={};calls=[];paid=[]
        def complete(payload,**kwargs):
            calls.append(payload)
            if payload['task']!='region_teaching_batch':return self.modern_reply(payload)
            raw={key:self.modern_reply(unit) for key,unit in payload['units'].items()}
            raw['u1']['concepts'][0]['segments'][0]['blockIds']=['outside']
            provider=owner['provider'];entry={**copy.deepcopy(provider.context),
                'requestId':'fixture-paid-pair','state':'settled','sentAtMs':100,
                'responseCacheKey':'a'*64,'estimatedUsd':.001}
            provider.ledger['requests'].append(entry)
            write_json(self.folder/'usage/fixture.json',{'model':provider.model,'requests':[entry]})
            write_json(self.folder/'generated/paid-responses'/('a'*64+'.json'),raw)
            paid.append(entry)
            return raw
        owner['provider']=FakeProvider(complete)
        opts={'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8}
        first,cache=self.run_pipeline(lambda _:None,provider=owner['provider'],
            crop_result=self.batch_crop,worker_limit=1,wire_options=opts)
        self.assertFalse(first['processingComplete']);self.assertEqual(len(calls),3)
        pair_ids=paid[0]['unitIds']
        # Simulate a crash after the paid envelope was durable but before one
        # valid child was saved. The invalid sibling still has no valid cache.
        (cache/f'response-{pair_ids[0]}.json').unlink()
        no_paid=FakeProvider(lambda *a,**k:self.fail('Resume cannot pay for an old batch'))
        resumed,_=self.run_pipeline(lambda _:self.fail('Recovery needs no crop rendering'),
            provider=no_paid,worker_limit=1,wire_options=opts)
        self.assertFalse(resumed['processingComplete'])
        self.assertTrue((cache/f'response-{pair_ids[0]}.json').is_file())
        self.assertEqual(resumed['metrics']['newStudyJobs'],0)
        self.assertEqual(len(resumed['failedUnits']),1)
        self.assertEqual(resumed['failedUnits'][0]['error'],'MissingPaidResponseError')
        self.assertEqual(resumed['failedUnits'][0]['unitId'],pair_ids[1])
        self.assertEqual(len(resumed['cacheReuse']['replies']),1)
        retried=[]
        def retry(payload,**kwargs):
            retried.append(payload);return self.modern_reply(payload)
        approved=FakeProvider(retry);approved.retry_missing_responses=True
        final,_=self.run_pipeline(lambda _:None,provider=approved,
            crop_result=self.batch_crop,worker_limit=1,wire_options=opts)
        self.assertTrue(final['processingComplete'])
        self.assertEqual(len(retried),1)
        self.assertEqual(retried[0]['task'],'region_teaching')

    def test_damaged_old_usage_keeps_saved_teaching_without_new_charges(self):
        def partial(payload,**kwargs):
            if payload['blocks'][0]['id']=='source2':raise ai.AiResponseError('fixture interrupted')
            return self.reply(payload['blocks'][0]['id'])
        first,_=self.run_pipeline(lambda _:None,complete=partial)
        self.assertFalse(first['processingComplete'])
        write_json(self.folder/'usage/damaged.json',{'model':'gpt-6-luna','requests':None})
        value,_=self.run_pipeline(lambda _:self.fail('Damaged ledger cannot render/retry'),
            complete=lambda *a,**k:self.fail('Damaged ledger cannot pay'))
        self.assertFalse(value['processingComplete'])
        self.assertEqual(sum(len(s['parts']) for s in value['sections']),2)
        self.assertEqual(value['failedUnits'][0]['error'],'MissingPaidResponseError')

    def test_batch_aliases_restore_all_units_and_expand_the_pool_without_truncation(self):
        self.set_unit_count(4)
        self.blocks=[{**b,'id':b['id']+'_'+str(n),'text':'원문의 정의와 핵심 조건을 보존해요.'}
                     for b in self.blocks for n in range(40)]
        self.groups=[{'title':f'주제{page}', 'blocks':[b for b in self.blocks if b['page']==page]}
                     for page in range(1,5)]
        schemas=[]
        def complete(payload,**kwargs):
            if payload['task']!='region_teaching_batch':return self.modern_reply(payload)
            schemas.append(kwargs['response_format'])
            self.assertTrue(payload['units']['u0']['blocks'][0]['id'].startswith('ua'))
            self.assertTrue(payload['units']['u1']['blocks'][0]['id'].startswith('ub'))
            self.assertEqual(len(payload['units']['u0']['blocks']),40)
            return {name:self.modern_reply(unit) for name,unit in payload['units'].items()}
        result,cache=self.run_pipeline(lambda _:None,complete=complete,crop_result=self.batch_crop,
            wire_options={'SOURCE_ID_ALIASES':True,'SOURCE_ALIAS_POOL_SIZE':32,
                'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8,'TRANSPORT_BATCH_ALIASES':True,
                'TRANSPORT_BATCH_ALIAS_POOL':32})
        self.assertTrue(result['processingComplete'])
        self.assertEqual(len(schemas),1)
        self.assertEqual(len(schemas[0]['json_schema']['schema']['$defs']['u0__studySourceId']['enum']),64)
        for path in cache.glob('response-*.json'):
            raw=json.loads(path.read_text())
            self.assertTrue(raw['concepts'][0]['segments'][0]['blockIds'][0].startswith('source'))

    def test_single_paid_history_cannot_be_silently_repacked_as_a_new_paid_pair(self):
        jobs=study.jobs_for(self.groups)
        entries=[{'requestId':f'legacy{i}','kind':'region_study','strategy':'new-concept-v99',
            'unitIds':[jobs[i]['id']],'state':'settled','sentAtMs':i+1} for i in (0,1)]
        write_json(self.folder/'usage/legacy.json',{'model':'gpt-6-luna','requests':entries})
        cache_reads=[];new_calls=[]
        def complete(payload,**kwargs):
            source=payload['blocks'][0]['id']
            if kwargs.get('cache_only'):
                cache_reads.append(source)
                if source=='source0':return self.reply(source)
                raise ai.AiResponseError('fixture missing paid cache')
            new_calls.append(source);return self.reply(source)
        opts={'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8}
        value,_=self.run_pipeline(lambda _:None,complete=complete,
            worker_limit=1,wire_options=opts)
        self.assertFalse(value['processingComplete'])
        self.assertEqual(cache_reads,['source0','source1'])
        self.assertEqual(new_calls,['source2'])
        self.assertEqual(value['failedUnits'][0]['unitId'],jobs[1]['id'])
        self.assertEqual(value['failedUnits'][0]['error'],'MissingPaidResponseError')
        self.assertEqual(value['cacheReuse']['replies'][0]['paidBatchRecovery']['kind'],
                         'paid_single_local_recovery')
        approved=FakeProvider(complete);approved.retry_missing_responses=True
        final,_=self.run_pipeline(lambda _:None,provider=approved,worker_limit=1,wire_options=opts)
        self.assertTrue(final['processingComplete'])
        self.assertEqual(new_calls,['source2','source1'])

    def test_unsent_batch_budget_or_context_failure_splits_without_losing_units(self):
        for failure in (ai.BudgetExceeded,ai.ContextBudgetExceeded):
            with self.subTest(failure=failure.__name__):
                self.set_unit_count(5);paid=[]
                def complete(payload,**kwargs):
                    if payload['task']=='region_teaching_batch':raise failure('Local unsent admission')
                    paid.append(payload['blocks'][0]['id']);return self.modern_reply(payload)
                # A new isolated cache for the second exception mode.
                self.document['fingerprint']=failure.__name__
                result,cache=self.run_pipeline(lambda _:None,complete=complete,crop_result=self.batch_crop,
                    wire_options={'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8})
                self.assertTrue(result['processingComplete'])
                self.assertEqual(len(paid),5)
                self.assertEqual(len(set(paid)),5)

    def test_twenty_jobs_fill_sixteen_startup_slots_and_publish_every_unit(self):
        self.blocks = [{**self.blocks[0], 'id':f'source{i}', 'page':i+1} for i in range(20)]
        self.groups = [{'title':f'독립 주제{i}', 'blocks':[b]} for i,b in enumerate(self.blocks)]
        self.document['pages'] = [{'number':i+1,'label':str(i+1),'nativeText':b['text']}
                                  for i,b in enumerate(self.blocks)]
        all_slots=threading.Event()
        state={'active':0,'maximum':0,'calls':0,'renders':0,'prefetchWhileActive':None}
        def render(source):
            with self.lock:
                state['renders']+=1;number=state['renders']
            if number==17:
                self.assertTrue(all_slots.wait(3),'The next unit must prepare while 16 startup requests run')
                with self.lock:state['prefetchWhileActive']=state['active']
        def complete(payload, **kwargs):
            with self.lock:
                state['active']+=1;state['calls']+=1
                state['maximum']=max(state['maximum'],state['active'])
                if state['active']==16:all_slots.set()
            self.assertTrue(all_slots.wait(3),'Available teaching work did not fill 16 startup slots')
            time.sleep(.02)
            with self.lock:state['active']-=1
            return self.reply(payload['blocks'][0]['id'])
        result,_=self.run_pipeline(render,complete,worker_limit=128)
        self.assertTrue(result['processingComplete'])
        self.assertEqual(state['maximum'],16)
        self.assertEqual(state['calls'],20)
        self.assertEqual(state['prefetchWhileActive'],16)
        self.assertEqual(result['metrics']['workers'],14)
        self.assertEqual(result['metrics']['startupWorkers'],16)
        self.assertEqual(sum(kind=='unit_ready' for kind,_ in self.events),20)

    def test_first_request_starts_before_all_local_crops_finish(self):
        first_api = threading.Event()
        renders = 0

        def render(source):
            nonlocal renders
            with self.lock:
                renders += 1
                position = renders
            # Worker acquisition order is deliberately unspecified. Let the
            # actual first rendered job start its request, whichever job it is.
            if position != 1:
                self.assertTrue(first_api.wait(2), 'Rendering was completed in bulk before the first request')

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']
            self.record('api', source)
            first_api.set()
            return self.reply(source)

        result, _ = self.run_pipeline(render, complete)
        self.assertTrue(result['processingComplete'])
        first_request = next(i for i, (event, _) in enumerate(self.events) if event == 'api')
        last_render = max(i for i, (event, _) in enumerate(self.events) if event == 'crop_done')
        self.assertLess(first_request, last_render)
        self.assertEqual(sum(kind == 'api' for kind, _ in self.events), 3)

    def test_local_rendering_stays_serial_while_requests_are_in_flight(self):
        state = {'active': 0, 'maximum': 0, 'finished': 0}
        rendered = threading.Event()

        def render(source):
            with self.lock:
                state['active'] += 1
                state['maximum'] = max(state['maximum'], state['active'])
            # Yield execution so an unbounded renderer would actually overlap.
            time.sleep(.015)
            with self.lock:
                state['active'] -= 1
                state['finished'] += 1
                if state['finished'] == 3:
                    rendered.set()

        def complete(payload, **kwargs):
            self.record('api', payload['blocks'][0]['id'])
            self.assertTrue(rendered.wait(2))
            return self.reply(payload['blocks'][0]['id'])

        result, _ = self.run_pipeline(render, complete)
        self.assertTrue(result['processingComplete'])
        self.assertEqual(state['maximum'], 1)
        self.assertEqual(state['finished'], 3)

    def test_first_unit_is_saved_and_announced_while_other_requests_wait(self):
        other_started = threading.Event()
        release_other = threading.Event()
        state = {'waiting': 0, 'finished': 0}
        observed = []

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']
            self.record('api', source)
            if source == 'source0':
                self.assertTrue(other_started.wait(2))
            else:
                with self.lock:
                    state['waiting'] += 1
                    if state['waiting'] == 2:
                        other_started.set()
                self.assertTrue(release_other.wait(2), 'First completed unit was delayed until all requests finished')
                with self.lock:
                    state['finished'] += 1
            return self.reply(source)

        def ready(fields):
            if observed:
                return
            partial = json.loads((Path(fields['path']).parent/'partial.json').read_text())
            unit = json.loads(Path(fields['path']).read_text())
            observed.append((state['waiting'], state['finished'], partial['processingComplete'],
                             unit['summary']['parts'][0]['title']))
            release_other.set()

        try:
            result, _ = self.run_pipeline(lambda _: None, complete, ready)
        finally:
            release_other.set()
        self.assertTrue(result['processingComplete'])
        self.assertEqual(observed, [(2, 0, False, 'source0의 원리')])
        self.assertIsNotNone(result['metrics']['firstResultSeconds'])

    def test_paid_replies_are_reused_without_rendering_or_api_calls(self):
        def forbidden(*args, **kwargs):
            raise AssertionError('A paid cached reply must not be rendered or bought again')

        result, cache = self.run_pipeline(forbidden, forbidden, cached=True)
        self.assertTrue(result['processingComplete'])
        self.assertEqual(len(list(cache.glob('response-*.json'))), 3)
        self.assertEqual(result['runUsage']['requests'], 0)
        self.assertEqual([event for event in self.events if event[0] in {'api', 'crop_start'}], [])
        self.assertEqual(len([event for event in self.events if event[0] == 'unit_ready']), 3)

    def test_one_render_failure_keeps_other_successes_in_partial_output(self):
        def render(source):
            if source == 'source1':
                raise OSError('Synthetic crop failure')

        result, cache = self.run_pipeline(render)
        self.assertFalse(result['processingComplete'])
        self.assertEqual(len(result['failedUnits']), 1)
        self.assertEqual(result['failedUnits'][0]['error'], 'OSError')
        self.assertFalse((cache/'result.json').exists())
        partial = json.loads((cache/'partial.json').read_text())
        titles = [p['title'] for s in partial['sections'] for p in s['parts']]
        self.assertEqual(set(titles), {'source0의 원리', 'source2의 원리'})
        self.assertEqual(set(partial['incompleteStudyPages']), {2})
        self.assertEqual(len(list(cache.glob('response-*.json'))), 2)
        self.assertEqual(len(list(cache.glob('unit-*.json'))), 2)

    def unknown_artifacts(self, provider, kind):
        """Simulate an already sent request whose usage/reply was not confirmed."""
        entry = {'requestId': 'synthetic-unknown-' + kind, 'kind': kind,
                 'state': 'failed_or_uncertain', 'reservedUsd': .0123,
                 'sentAtMs': 1234567890000, 'responseAvailable': False}
        provider.ledger['requests'].append(entry)
        ledger = self.folder/'usage'/(kind+'-unknown.json')
        raw = self.folder/'generated'/'paid-responses'/(kind+'-unknown.raw.json')
        write_json(ledger, provider.ledger)
        write_json(raw, {'partialBytes': 'Unconfirmed reply; never replace with a successful placeholder.'})
        return {path: path.read_bytes() for path in (ledger, raw)}

    def assert_untouched(self, artifacts):
        for path, original in artifacts.items():
            self.assertEqual(path.read_bytes(), original, f'Unconfirmed paid artifact changed: {path.name}')

    def test_network_failure_keeps_later_started_successes_without_retry(self):
        started = threading.Barrier(3)
        failed = threading.Event()
        first_saved = threading.Event()
        artifacts = {}

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']
            self.record('api', source)
            started.wait(timeout=3)
            if source == 'source1':
                artifacts.update(self.unknown_artifacts(provider, 'region_study'))
                failed.set()
                raise ai.AiResponseError('Synthetic failure after a request was sent; do not retry.')
            self.assertTrue(failed.wait(3))
            if source == 'source2':
                self.assertTrue(first_saved.wait(3), 'A started request was abandoned after another request failed')
            return self.reply(source)

        provider = FakeProvider(complete)
        try:
            result, cache = self.run_pipeline(lambda _: None,
                provider=provider, emit=lambda _: first_saved.set())
        finally:
            first_saved.set()
        self.assertFalse(result['processingComplete'])
        self.assertEqual(result['kind'], 'partial')
        self.assertEqual(len(result['failedUnits']), 1)
        self.assertEqual(result['failedUnits'][0]['error'], 'AiResponseError')
        self.assertEqual(set(result['incompleteStudyPages']), {2})
        self.assertEqual({part['title'] for section in result['sections'] for part in section['parts']},
                         {'source0의 원리', 'source2의 원리'})
        self.assertEqual(sorted(source for event, source in self.events if event == 'api'),
                         ['source0', 'source1', 'source2'])
        self.assertEqual(len([event for event in self.events if event[0] == 'unit_ready']), 2)
        self.assertEqual(len(list(cache.glob('response-*.json'))), 2)
        self.assertEqual(len(list(cache.glob('unit-*.json'))), 2)
        self.assertFalse((cache/'result.json').exists())
        saved = json.loads((cache/'partial.json').read_text())
        self.assertEqual(saved['sections'], result['sections'])
        self.assertEqual(result['runUsage']['unknownUsageRequests'], 1)
        self.assertEqual(result['runUsage']['uncertainReservedUsd'], .0123)
        self.assert_untouched(artifacts)

    def test_optional_overview_network_failure_uses_local_outline_without_retry_or_lost_prose(self):
        artifacts = {}

        def complete(payload, **kwargs):
            if payload.get('task') == 'lecture_flow_from_headings':
                self.record('overview_api')
                artifacts.update(self.unknown_artifacts(provider, 'summary_reduce'))
                raise ai.AiResponseError('Synthetic optional overview connection failure.')
            source = payload['blocks'][0]['id']
            self.record('api', source)
            return self.reply(source)

        provider = FakeProvider(complete)
        result, cache = self.run_pipeline(lambda _: None, provider=provider, real_overview=True)
        self.assertTrue(result['processingComplete'])
        self.assertEqual(result['kind'], 'ai_generated')
        self.assertEqual(result['failedUnits'], [])
        self.assertEqual({part['title'] for section in result['sections'] for part in section['parts']},
                         {f'source{i}의 원리' for i in range(3)})
        self.assertEqual(len([event for event in self.events if event[0] == 'api']), 3)
        self.assertEqual(len([event for event in self.events if event[0] == 'overview_api']), 1)
        self.assertEqual(len([event for event in self.events if event[0] == 'unit_ready']), 3)
        self.assertEqual(result['overview']['overviewMethod'], 'local_headings_prose')
        self.assertTrue(result['overview']['body'])
        self.assertTrue(result['metrics']['overviewLocalFallback'])
        self.assertTrue(any(note.get('stage') == 'overview' and note.get('localFallback') is True
                            and note.get('additionalApiRequests') == 0
                            for note in result['processingNotes']))
        self.assertTrue((cache/'result.json').is_file())
        self.assertEqual(len(list(cache.glob('response-*.json'))), 3)
        self.assertEqual(result['runUsage']['unknownUsageRequests'], 1)
        self.assert_untouched(artifacts)
        # Invocation-only diagnostics must not make an existing local outline
        # look like another failed API request when it is loaded from cache.
        from pdf_outline import overview
        cached_outline = overview(provider, cache, result['sections'])
        self.assertEqual(cached_outline['overviewMethod'], 'local_headings_prose')
        self.assertEqual(cached_outline['body'], result['overview']['body'])
        self.assertNotIn('localFallbackDiagnostic', cached_outline)
        self.assertEqual(len([event for event in self.events if event[0] == 'overview_api']), 1)


if __name__ == '__main__':
    unittest.main()
