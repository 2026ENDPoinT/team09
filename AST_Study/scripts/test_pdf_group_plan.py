"""Two-stage admission and paid-plan cache contracts; no network transports."""
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import shutil
import copy

import pdf_ai
import pdf_new_concept_ver99_study as engine
from pdf_credit_billing import Billing, InsufficientCredits, balance, wallet_lock

class GroupPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.folder=self.root/'pdf'/'doc';self.folder.mkdir(parents=True)
        self.doc={'documentId':'doc','fingerprint':'fixture','pages':[{'number':1,'nativeText':'정의와 조건','label':'1'}]}
        self.block={'id':'b','page':1,'kind':'text','text':'정의와 조건','bbox':[0,0,1,1],
                    'visualOnly':False,'hasVisual':False,'planRole':'teaching'}
        self.wallet=self.root/'credits-wallet.json'
    def fund(self,credits):
        self.wallet.write_text(json.dumps({'liveBilling':True,'baselineCredits':'0','highWaterCredits':'0',
            'purchases':[{'credits':str(credits)}],'creditHolds':{},'creditOperations':{},'creditCharges':{}}))
    def test_eight_won_gate_exact_boundary_and_holds(self):
        threshold=Decimal(8)/Decimal('2.3');self.fund(threshold)
        billing=Billing(self.wallet,'plan','planning');billing.planning_admission()
        with wallet_lock(self.wallet) as wallet:self.assertEqual(balance(wallet),threshold)
        self.fund(threshold-Decimal('.000001'))
        with self.assertRaisesRegex(InsufficientCredits,'최소 8원'):billing.planning_admission()
        self.fund(threshold+1)
        Billing(self.wallet,'other','chat').reserve('hold',Decimal('2')*Decimal('2.3')/1400)
        with self.assertRaises(InsufficientCredits):billing.planning_admission()
    def test_groups_are_persisted_and_reused_without_study_or_images(self):
        provider=SimpleNamespace(model='gpt-6-luna',billing=None)
        groups=[{'title':'정의','blocks':[self.block]}]
        with patch.object(engine,'extract',return_value=[self.block]),patch.object(engine,'plan_groups',return_value=(groups,[])) as planning,patch.object(engine,'render_crops',side_effect=AssertionError('no images')):
            first=engine.prepare_group_plan(self.folder,self.doc,provider)
            second=engine.prepare_group_plan(self.folder,self.doc,provider)
        self.assertEqual(planning.call_count,1)
        self.assertTrue(first['groupingConfirmed']);self.assertTrue(second['groupingConfirmed'])
        self.assertEqual(first['estimateWorkload']['grouping'],'cached_plan')
        self.assertGreater(first['costEstimateUsd'],0)
        root=engine.root_path(self.folder,self.doc,'new-concept-v99',provider.model,'document',0)
        self.assertTrue((root/'plan.json').is_file());self.assertTrue((root/'manifest.json').is_file())
        self.assertFalse((root/'result.json').exists())
    def test_low_wallet_stops_before_extraction_or_planner(self):
        self.fund(0)
        provider=SimpleNamespace(model='gpt-6-luna',billing=Billing(self.wallet,'plan','planning'))
        with patch.object(engine,'extract',side_effect=AssertionError('no extraction')):
            with self.assertRaises(pdf_ai.CreditExceeded):engine.prepare_group_plan(self.folder,self.doc,provider)

    def test_planning_failure_never_persists_a_confirmed_page_fallback(self):
        for error in (pdf_ai.MissingPaidResponseError('missing paid response'),
                      pdf_ai.AiResponseError('HTTP error'),InterruptedError('cancelled')):
            with self.subTest(error=type(error).__name__):
                provider=SimpleNamespace(model='gpt-6-luna',billing=None,
                                         complete=lambda *a,**k:(_ for _ in ()).throw(error))
                with patch.object(engine,'extract',return_value=[self.block]):
                    with self.assertRaises(type(error)):
                        engine.prepare_group_plan(self.folder,self.doc,provider)
                root=engine.root_path(self.folder,self.doc,'new-concept-v99',provider.model,'document',0)
                self.assertFalse((root/'plan.json').exists())
                self.assertFalse((root/'manifest.json').exists())

    def test_failed_or_outdated_plan_is_replaced_once_and_then_reused(self):
        provider=SimpleNamespace(model='gpt-6-luna',billing=None)
        root=engine.root_path(self.folder,self.doc,'new-concept-v99',provider.model,'document',0)
        root.mkdir(parents=True)
        (root/'plan.json').write_text(json.dumps({'groups':[{'title':'③','blocks':[self.block]}],
            'warnings':[{'stage':'plan','error':'AiResponseError'}]}))
        groups=[{'title':'정의','blocks':[self.block]}]
        with patch.object(engine,'extract',return_value=[self.block]),patch.object(engine,'plan_groups',return_value=(groups,[])) as planning:
            engine.prepare_group_plan(self.folder,self.doc,provider)
            engine.prepare_group_plan(self.folder,self.doc,provider)
        self.assertEqual(planning.call_count,1)
        self.assertTrue(engine.usable_plan(json.loads((root/'plan.json').read_text())))

    def test_textless_scan_bypasses_text_planning_without_error_fallback(self):
        blank={**self.block,'text':'','kind':'visual','hasVisual':True,'visualOnly':True}
        provider=SimpleNamespace(model='gpt-6-luna')
        groups,warnings=engine.plan_groups(self.folder,provider,[blank],self.folder)
        self.assertEqual(groups[0]['blocks'],[blank]);self.assertFalse(warnings)
        self.assertTrue(engine.usable_plan(json.loads((self.folder/'plan.json').read_text())))

    def test_textless_scan_clears_stale_skip_annotations_and_records_direct_vision(self):
        blank={**self.block,'text':'','kind':'visual','hasVisual':True,'visualOnly':True,
               'planRole':'exercise','planRoleBeforeVisualGuard':'navigation'}
        provider=SimpleNamespace(model='gpt-6-luna')
        groups,_=engine.plan_groups(self.folder,provider,[blank],self.folder)
        self.assertNotIn(groups[0]['blocks'][0].get('planRole'),('exercise','navigation','decoration'))
        plan=json.loads((self.folder/'plan.json').read_text())
        self.assertEqual(plan['assignmentRecovery']['semanticGroupingStatus'],'direct_visual')

    def test_explicit_missing_response_retry_calls_once_and_keeps_duplicate_guard(self):
        calls=[]
        def transport(body):
            calls.append(body)
            return {'choices':[{'finish_reason':'stop','message':{'content':'{"groups":[]}'}}],
                    'usage':{'prompt_tokens':10,'completion_tokens':5}}
        first=pdf_ai.Provider(self.folder,True,.1,transport=transport)
        first.complete({'task':'grouping fixture'})
        shutil.rmtree(self.folder/'generated')
        blocked=pdf_ai.Provider(self.folder,True,.1,transport=transport)
        with self.assertRaises(pdf_ai.MissingPaidResponseError):blocked.complete({'task':'grouping fixture'})
        self.assertEqual(len(calls),1)
        retry=pdf_ai.Provider(self.folder,True,.1,transport=transport,retry_missing_responses=True)
        retry.complete({'task':'grouping fixture'})
        retry.complete({'task':'grouping fixture'})
        self.assertEqual(len(calls),2)
        self.assertTrue(retry.ledger['requests'][0]['retryOfMissingResponse'])
        shutil.rmtree(self.folder/'generated')
        with self.assertRaises(pdf_ai.MissingPaidResponseError):retry.complete({'task':'grouping fixture'})
        self.assertEqual(len(calls),2)

    def test_neighbors_skip_footer_and_keep_the_explicit_classification_parent(self):
        def b(i,text,kind='text',heading='income'):
            return {'id':str(i),'page':1 if i<4 else 2,'kind':kind,'text':text,'headingId':heading}
        blocks=[b(0,'기업이 발생시키는 4가지 종류의 비용'),b(1,'① 매출원가'),
                b(2,'② 판매 및 일반관리비'),b(3,'47','page_number'),b(4,'③ 지급이자'),
                b(5,'④ 세금'),b(6,'6.2. 재무상태표','heading','balance')]
        job={'blocks':blocks[4:6]}
        neighbors=engine.job_neighbors(blocks,job,{b['id']:i for i,b in enumerate(blocks)})
        text=' '.join(n['text'] for n in neighbors)
        self.assertIn('4가지 종류',text);self.assertIn('② 판매',text)
        self.assertNotIn('47',text);self.assertNotIn('재무상태표',text)

    def margin_fixture(self):
        blocks=[]
        for page in range(1,4):
            for n,(text,box) in enumerate([
                ('강의명 · 담당 교수',[.12,.0554,.38,.0646]),
                ('© 2026 Course author. All rights reserved.',[.12,.0825,.50,.0917]),
                (f'{page}쪽에서 새롭게 배우는 본문',[.12,.30,.70,.34])]):
                blocks.append({**self.block,'id':f'p{page}f{n}','page':page,'text':text,'bbox':box})
        return blocks

    def test_omitted_repeated_headers_recover_locally_and_keep_every_source(self):
        # This fixture deliberately exercises sparse legacy source-ID replies,
        # including omitted interior furniture; range transport has its own tests.
        legacy=patch.object(engine,'PLAN_TRANSPORT','ids');legacy.start();self.addCleanup(legacy.stop)
        blocks=self.margin_fixture();calls=[]
        def complete(payload,**kwargs):
            calls.append(payload)
            return {'groups':[{'title':'학습 본문','blockIds':[b['id'] for b in payload['targets'] if b['id'].endswith('f2')],'role':'teaching','continuesPrevious':False}]}
        provider=SimpleNamespace(model='gpt-6-luna',complete=complete)
        groups,warnings=engine.plan_groups(self.folder,provider,blocks,self.folder)
        self.assertEqual(len(calls),1);self.assertFalse(warnings)
        self.assertEqual(len(groups),1,'recovered headers must not split a teaching topic into per-page jobs')
        by_id={b['id']:b for g in groups for b in g['blocks']}
        self.assertEqual(list(by_id),[b['id'] for b in blocks])
        self.assertEqual(len([b for b in by_id.values() if b['planRole']=='decoration']),6)
        self.assertEqual(len([b for b in by_id.values() if b['planRole']=='teaching']),3)
        self.assertTrue(engine.usable_plan(json.loads((self.folder/'plan.json').read_text())))
        audit=json.loads((self.folder/'plan-local-recovery.json').read_text())
        self.assertEqual(len(audit['blockIds']),6);self.assertEqual(audit['additionalRecoveryApiRequests'],0)

    def test_window_recovery_uses_full_document_repetition_evidence(self):
        # Pin the old wire contract, preserving the source-recovery assertion
        # when the production default switches to contiguous integer ranges.
        legacy=patch.object(engine,'PLAN_TRANSPORT','ids');legacy.start();self.addCleanup(legacy.stop)
        blocks=self.margin_fixture();(self.folder/'blocks.json').write_text(json.dumps(blocks))
        provider=SimpleNamespace(model='gpt-6-luna',complete=lambda *a,**k:{'groups':[{'title':'본문','blockIds':['p3f2'],'role':'teaching'}]})
        groups,_=engine.plan_groups(self.folder,provider,blocks[-3:],self.folder)
        self.assertEqual([b['id'] for g in groups for b in g['blocks']],['p3f0','p3f1','p3f2'])

    def test_repeated_furniture_does_not_hide_missing_body(self):
        blocks=self.margin_fixture()
        provider=SimpleNamespace(model='gpt-6-luna',complete=lambda *a,**k:{'groups':[]})
        groups,warnings=engine.plan_groups(self.folder,provider,blocks,self.folder)
        self.assertFalse(warnings)
        assigned=[b for g in groups for b in g['blocks']]
        self.assertEqual([b['id'] for b in assigned],[b['id'] for b in blocks])
        self.assertTrue(all(b['planRole']=='uncertain' for b in assigned if b['id'].endswith('f2')))
        self.assertTrue(all(b['planRole']=='decoration' for b in assigned if not b['id'].endswith('f2')))

    def test_furniture_requires_exact_text_distinct_pages_and_margin_geometry(self):
        blocks=self.margin_fixture();self.assertEqual(len(engine.repeated_margin_ids(blocks)),6)
        for change in ('middle','heading','visual','changing_text','single_page'):
            with self.subTest(change=change):
                values=json.loads(json.dumps([b for b in blocks if b['id'].endswith('f0')]))
                for i,b in enumerate(values):
                    if change=='middle':b['bbox']=[.12,.4,.38,.42]
                    if change=='heading':b['kind']='heading'
                    if change=='visual':b['hasVisual']=True
                    if change=='changing_text':b['text']=f'Chapter {i+1}'
                    if change=='single_page':b['page']=1
                self.assertEqual(engine.repeated_margin_ids(values),set())

    def test_incomplete_assignment_is_recovered_without_semantic_confirmation_or_review(self):
        calls=[]
        def complete(*args,**kwargs):
            calls.append(args)
            return {'groups':[]}
        provider=SimpleNamespace(model='gpt-6-luna',complete=complete)
        groups,warnings=engine.plan_groups(self.folder,provider,[self.block],self.folder)
        self.assertEqual(len(calls),1);self.assertFalse(warnings)
        self.assertEqual(groups[0]['blocks'][0]['planRole'],'uncertain')
        plan=json.loads((self.folder/'plan.json').read_text())
        self.assertTrue(engine.usable_plan(plan,blocks=[self.block]))
        self.assertEqual(plan['assignmentRecovery']['semanticGroupingStatus'],'locally_recovered')
        self.assertEqual(plan['assignmentRecovery']['localUncertainBlockIds'],['b'])
        self.assertEqual(plan['assignmentRecovery']['additionalRecoveryApiRequests'],0)

    def test_partial_success_preserves_original_missing_source_through_prepare_and_cache(self):
        other={**self.block,'id':'c','text':'멱급수의 수렴·발산 판정','planRole':'exercise'}
        blocks=[copy.deepcopy(self.block),other];calls=[]
        def complete(*args,**kwargs):
            calls.append(args)
            return {'groups':[{'title':'정의','role':'teaching','first':0,'last':0,
                               'continuesPrevious':False}]}
        provider=SimpleNamespace(model='gpt-6-luna',billing=None,complete=complete)
        with patch.object(engine,'extract',side_effect=lambda *a:copy.deepcopy(blocks)):
            first=engine.prepare_group_plan(self.folder,self.doc,provider)
            second=engine.prepare_group_plan(self.folder,self.doc,provider)
        root=engine.root_path(self.folder,self.doc,'new-concept-v99',provider.model,'document',0)
        plan=json.loads((root/'plan.json').read_text());manifest=json.loads((root/'manifest.json').read_text())
        actual={b['id']:b for job in manifest['jobs'] for b in job['blocks']}
        self.assertEqual(actual['c']['planRole'],'uncertain')
        self.assertEqual(actual['c']['text'],other['text'])
        self.assertEqual(first['locallyRecoveredSourceCount'],1)
        self.assertTrue(first['groupingLocallyRecovered']);self.assertTrue(second['groupingLocallyRecovered'])
        self.assertEqual(len(calls),1)
        self.assertTrue(engine.usable_plan(plan,blocks=blocks))
        self.assertEqual(plan['sourcePartition']['sourceCount'],2)

    def test_corrupt_cached_partitions_are_replaced_once_against_independent_sources(self):
        canonical=[self.block,{**self.block,'id':'c','text':'두 번째 중요한 설명'}]
        root=engine.root_path(self.folder,self.doc,'new-concept-v99','gpt-6-luna','document',0)
        root.mkdir(parents=True)
        for corruption in ('missing','duplicate','unknown','modified'):
            with self.subTest(corruption=corruption):
                source=copy.deepcopy(canonical)
                if corruption=='missing':source.pop()
                if corruption=='duplicate':source[1]=copy.deepcopy(source[0])
                if corruption=='unknown':source[1]['id']='not-in-source'
                if corruption=='modified':source[1]['text']='삭제된 조건'
                # Historical status alone must not establish exact coverage.
                plan={'groups':[{'title':'역사적 계획','blocks':source}], 'status':'confirmed',
                      'warnings':[],'plannerIdentity':engine.planner_identity()}
                (root/'plan.json').write_text(json.dumps(plan));(root/'blocks.json').write_text(json.dumps(canonical))
                calls=[]
                def complete(*a,**k):
                    calls.append(a)
                    return {'groups':[{'title':'원리','role':'teaching','blockIds':['b','c']}]}
                provider=SimpleNamespace(model='gpt-6-luna',billing=None,complete=complete)
                with patch.object(engine,'extract',side_effect=lambda *a:copy.deepcopy(canonical)):
                    engine.prepare_group_plan(self.folder,self.doc,provider)
                    engine.prepare_group_plan(self.folder,self.doc,provider)
                self.assertEqual(len(calls),1)
                self.assertTrue(engine.usable_plan(json.loads((root/'plan.json').read_text()),blocks=canonical))

    def test_legacy_exact_plan_does_not_need_another_paid_request(self):
        root=engine.root_path(self.folder,self.doc,'new-concept-v99','gpt-6-luna','document',0)
        root.mkdir(parents=True)
        plan={'groups':[{'title':'원리','blocks':[self.block]}], 'status':'confirmed',
              'warnings':[],'plannerIdentity':engine.planner_identity()}
        (root/'plan.json').write_text(json.dumps(plan));(root/'blocks.json').write_text(json.dumps([self.block]))
        provider=SimpleNamespace(model='gpt-6-luna',billing=None,
                                 complete=lambda *a,**k:(_ for _ in ()).throw(AssertionError('no paid call')))
        with patch.object(engine,'extract',side_effect=AssertionError('valid cached source')):
            self.assertTrue(engine.prepare_group_plan(self.folder,self.doc,provider)['groupingConfirmed'])

    def test_invalid_top_level_response_still_stops_before_any_confirmed_plan(self):
        for raw in (None,[],{}, {'groups':None}):
            provider=SimpleNamespace(model='gpt-6-luna',complete=lambda *a,**k:raw)
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                engine.plan_groups(self.folder,provider,[self.block],self.folder)
            self.assertFalse((self.folder/'plan.json').exists())

    def test_canonical_duplicate_rejected_before_any_paid_request(self):
        provider=SimpleNamespace(model='gpt-6-luna',complete=lambda *a,**k:(_ for _ in ()).throw(AssertionError('no paid call')))
        with self.assertRaises(ValueError):
            engine.plan_groups(self.folder,provider,[self.block,copy.deepcopy(self.block)],self.folder)

    def test_range_transport_repairs_gaps_conflicts_and_invalid_bounds_without_clipping(self):
        blocks=[{**self.block,'id':str(i),'text':f'중요 원리 {i}'} for i in range(4)]
        raw={'groups':[{'first':0,'last':1,'role':'exercise','title':'예제'},
                       {'first':1,'last':2,'role':'teaching','title':'설명'},
                       {'first':3,'last':99,'role':'navigation','title':'잘못된 범위'}]}
        provider=SimpleNamespace(model='gpt-6-luna',complete=lambda *a,**k:raw)
        with patch.object(engine,'PLAN_TRANSPORT','ranges'):
            groups,_=engine.plan_groups(self.folder,provider,blocks,self.folder)
        actual=[b for g in groups for b in g['blocks']]
        self.assertEqual([b['id'] for b in actual],[str(i) for i in range(4)])
        self.assertEqual([b['planRole'] for b in actual],['exercise','uncertain','teaching','uncertain'])
    def test_generate_checks_confirmed_estimate_not_caller_zero(self):
        self.fund(1)
        (self.folder/'document.json').write_text(json.dumps(self.doc))
        request=self.folder/'request.json'
        request.write_text(json.dumps({'strategy':'new-concept-v99','scope':'document','page':0,
                                       'creditBilling':True,'approvedEstimateUsd':0}))
        root=engine.root_path(self.folder,self.doc,'new-concept-v99','gpt-6-luna','document',0)
        root.mkdir(parents=True);(root/'plan.json').write_text('{}')
        original=pdf_ai.Provider
        def provider(*args,**kwargs):
            return original(*args,**kwargs,transport=lambda body:(_ for _ in ()).throw(AssertionError('no network')))
        argv=['pdf_ai.py','generate','--folder',str(self.folder),'--request',str(request),'--allow-remote','--max-usd','1']
        with patch.object(sys,'argv',argv),patch.object(pdf_ai,'Provider',side_effect=provider),patch('pdf_page_analysis.hydrate'),patch.object(engine,'reading_plan',return_value={'totalCostEstimateUsd':.02,'cachedPages':0}),patch.object(engine,'generate',side_effect=AssertionError('no generation')):
            with self.assertRaises(pdf_ai.CreditExceeded):pdf_ai.main()

if __name__=='__main__':unittest.main()
