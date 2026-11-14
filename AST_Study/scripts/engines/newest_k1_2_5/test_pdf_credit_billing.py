"""Offline billing contracts; transports are fixtures and never call paid APIs."""
import json
from decimal import Decimal
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pdf_credit_billing import Billing, RATE, InsufficientCredits, balance, available, wallet_lock
from pdf_ai import Provider, CreditExceeded

def process_reserve(args):
    path,index=args
    try: Billing(path,'process-'+str(index),'summary').reserve(str(index),Decimal(4)/RATE);return True
    except InsufficientCredits:return False

class CreditBillingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'credits-wallet.json'
        self.wallet(100)
    def wallet(self, credits):
        self.path.write_text(json.dumps({'version':1,'liveBilling':True,'baselineCredits':0,
            'highWaterCredits':0,'purchases':[{'credits':str(credits)}],
            'creditOperations':{},'creditCharges':{},'creditHolds':{}}))
    def state(self):
        with wallet_lock(self.path) as wallet:return wallet
    def test_free_chat_is_counted_once_without_debit(self):
        billing=Billing(self.path,'free-chat','chat');billing.record();billing.record()
        self.assertEqual(len(self.state()['creditOperations']),1)
        self.assertEqual(balance(self.state()),100)
        self.assertEqual(self.state()['creditOperations']['free-chat']['credits'],'0')

    def test_admission_is_ninety_five_percent_and_does_not_charge(self):
        self.wallet('9.5')
        Billing(self.path,'first','summary').admission(Decimal(10)/RATE)
        self.assertEqual(balance(self.state()),Decimal('9.5'))
        self.wallet('9.49')
        with self.assertRaisesRegex(InsufficientCredits,'생성을 하지 못했어요'):Billing(self.path,'first','summary').admission(Decimal(10)/RATE)




    def test_parallel_calls_cannot_reserve_same_balance(self):
        self.wallet(10)
        def worker(i):
            billing=Billing(self.path,str(i),'summary')
            try:billing.reserve(str(i),Decimal(4)/RATE);return True
            except InsufficientCredits:return False
        with ThreadPoolExecutor(max_workers=8) as pool:accepted=list(pool.map(worker,range(8)))
        self.assertEqual(sum(accepted),2)
        self.assertAlmostEqual(float(available(self.state())),2)
    def test_separate_processes_share_the_same_reservation_lock(self):
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        self.wallet(10)
        with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
            accepted=list(pool.map(process_reserve,[(str(self.path),i) for i in range(8)]))
            self.assertAlmostEqual(float(available(self.state())),2)
        self.assertEqual(sum(accepted),2)
        self.assertAlmostEqual(float(available(self.state())),10)

    def test_settlement_is_idempotent_and_frees_unused_reservation(self):
        billing=Billing(self.path,'run','summary')
        billing.reserve('request',Decimal(20)/RATE)
        billing.settle('request',Decimal(7)/RATE)
        billing.settle('request',Decimal(7)/RATE)
        self.assertAlmostEqual(float(balance(self.state())),93)
        self.assertEqual(self.state()['creditHolds'],{})
        self.assertAlmostEqual(float(self.state()['creditOperations']['run']['credits']),7)
    def test_unknown_usage_retains_evidence_without_holding_funds(self):
        billing=Billing(self.path,'chat','chat');billing.reserve('r',Decimal(4)/RATE)
        billing.settle('r');billing.settle('r')
        self.assertEqual(self.state()['creditOperations']['chat']['unknownRequests'],1)
        self.assertAlmostEqual(float(available(self.state())),100)
        self.assertFalse(self.state()['creditHolds'])
        self.assertIn('r',self.state()['creditPendingRequests'])
    def test_provider_bills_each_response_and_cache_does_not_bill_twice(self):
        calls=[]
        def transport(body):
            calls.append(body)
            return {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],
                    'usage':{'prompt_tokens':100,'completion_tokens':100}}
        provider=Provider(Path(self.tmp.name)/'doc',True,1,transport=transport)
        provider.billing=Billing(self.path,provider.ledger['operationId'],'summary')
        self.assertEqual(provider.complete({'task':'fixture'}),{'ok':True})
        state=self.state();paid=Decimal(state['creditOperations'][provider.ledger['operationId']]['credits'])
        self.assertGreater(paid,0);self.assertLess(balance(state),100)
        provider.complete({'task':'fixture'})
        self.assertEqual(len(calls),1);self.assertEqual(balance(self.state()),balance(state))
    def test_insufficient_credit_stops_before_transport(self):
        self.wallet(0);calls=[]
        provider=Provider(Path(self.tmp.name)/'doc',True,1,transport=lambda body:calls.append(body))
        provider.billing=Billing(self.path,'run','summary')
        with self.assertRaises(CreditExceeded):provider.complete({'task':'fixture'})
        self.assertEqual(calls,[]);self.assertTrue(provider.billing.exhausted)
        self.assertEqual(provider.ledger['requests'],[])

    def test_credit_stop_preserves_completed_ver99_units(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import pdf_new_concept_ver99_study as study
        folder=Path(self.tmp.name)/'doc';folder.mkdir()
        blocks=[{'id':name,'page':1,'kind':'text','text':name*500,'bbox':[0,0,1,1],
                 'planRole':'teaching','localRole':'teaching','hasVisual':False} for name in ['a','b']]
        groups=[{'title':b['id'],'blocks':[b]} for b in blocks]
        jobs=[{**g,'id':g['title'],'topicIndex':i} for i,g in enumerate(groups)]
        doc={'documentId':'fixture','fingerprint':'fixture','pages':[{'label':'1','nativeText':'fixture'}]}
        summary={'title':'완료된 첫 설명','body':'첫 설명은 보관돼요.','parts':[{'title':'첫 설명','body':'첫 설명은 보관돼요.','evidence':[],'visualPages':[1],'standardKnowledgeUsed':False}],
                 'evidence':[],'visualPages':[],'standardKnowledgeUsed':False}
        class FixtureProvider:
            model='gpt-6-luna'
            def __init__(self):
                self.folder=folder;self.billing=SimpleNamespace(exhausted=False);self.ledger={'requests':[]};self.calls=0
            def complete(self,*args,**kwargs):
                self.calls+=1
                if self.calls>1:
                    self.billing.exhausted=True
                    raise CreditExceeded('크레딧 부족')
                return {'summary':summary,'concepts':[{'name':'첫 설명','aliases':[],'definition':'정의','explanation':'첫 설명은 보관돼요.','easyExplanation':'쉬운 설명','evidence':[],'visualPages':[1],'standardKnowledgeUsed':False}],'coverage':[{'blockId':'a','page':1,'state':'covered'}]}
        provider=FixtureProvider()
        with patch.object(study,'extract',return_value=blocks),patch.object(study,'plan_groups',return_value=(groups,[])), \
             patch.object(study,'jobs_for',return_value=jobs),patch.object(study,'plain_cover_ids',return_value=set()), \
             patch.object(study,'lead_with_visual_page',return_value=(groups,[])), \
             patch.object(study,'OWNED_TEACHING',False), \
             patch.object(study,'render_crops',return_value=([],[])),patch.object(study,'validate',side_effect=lambda raw,*_:raw), \
             patch.dict('os.environ',{'SYNESIS_SUMMARY_SERIAL':'1'}):
            result=study.generate(folder,doc,provider)
        self.assertTrue(result['creditStopped']);self.assertFalse(result['processingComplete'])
        self.assertEqual(result['kind'],'partial');self.assertEqual(len(result['sections']),1)
        self.assertEqual(result['sections'][0]['body'],'첫 설명은 보관돼요.')
        self.assertEqual(provider.calls,2)
        self.assertTrue(list(folder.glob('generated/new-concept-v99/*/partial.json')))

if __name__=='__main__':unittest.main()
