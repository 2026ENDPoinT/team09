"""Offline regression for K1.1.3 selection and unsent reservation recovery."""
import copy
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pdf_newest_k1_1_2 as k112
import pdf_newest_k1_1_3 as k113
from pdf_ai import Provider, BudgetExceeded, CreditExceeded
from pdf_credit_billing import Billing, RATE
from pdf_k113_review import ReviewPolicy, exercise_exclusion
from pdf_study_progress_attempts import FourAttemptRace
from test_pdf_newest_k1_1_1 import block, response


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.b=block(0);self.b['id']='a'
        self.job={'id':'j','title':'개념','blocks':[self.b]}
        self.doc={'documentId':'test','pages':[{'label':'1'}]}

    def validate(self, raw, engine=k113):return engine.validate(raw,self.job,self.doc)

    def test_optional_easy_preserves_main_and_old_engine_requirement(self):
        raw=response('a');raw['concepts'][0]['segments'].pop()
        value=self.validate(copy.deepcopy(raw))
        self.assertEqual(value['coverage'][0]['state'],'summarized')
        self.assertEqual(value['concepts'][0]['easyExplanation'],'')
        old=self.validate(copy.deepcopy(raw),k112)
        self.assertEqual(old['coverage'][0]['state'],'needs_review')

    def test_missing_main_unreadability_and_missing_source_still_flag(self):
        raw=response('a');raw['concepts'][0]['segments']=[raw['concepts'][0]['segments'][0]]
        self.assertEqual(self.validate(raw)['coverage'][0]['state'],'needs_review')
        raw=response('a');raw['concepts'][0]['segments'][1]['text']='더하면\n이에요.'
        self.assertEqual(self.validate(raw)['coverage'][0]['state'],'needs_review')
        raw=response('a');raw['uncertainBlocks']=[{'blockId':'a','reason':'원문 수식을 읽을 수 없어요.'}]
        self.assertEqual(self.validate(raw)['coverage'][0]['state'],'needs_review')
        self.job['blocks'].append({**block(0),'id':'uncited','hasVisual':True})
        raw=response('a')
        self.assertEqual(self.validate(raw)['coverage'][-1]['state'],'needs_review')

    def test_declared_unnecessary_easy_is_omitted_but_useful_bridge_survives(self):
        for kind in ('none','intermediate_step'):
            raw=response('a')
            raw['concepts'][0]['sourceSetup']['learnerDifficulty']={'kind':kind,'question':''}
            value=self.validate(raw)
            self.assertEqual(bool(value['concepts'][0]['easyExplanation']),kind!='none')
            self.assertEqual(value['coverage'][0]['state'],'summarized')

    def test_rounding_is_narrow_and_source_assumptions_do_not_leak(self):
        policy=ReviewPolicy([self.b])
        text=r'\(\frac{-2.5}{-3.5}=0.714\)'
        self.assertIn(r'\approx',policy.prepare(text,['a']))
        self.assertFalse(policy.math_issues(policy.prepare(text,['a']),['a']))
        for wrong in [r'\(2+2=5\)',r'\(2+2=5.0\)',r'\(\frac{-2.5}{-3.5}=0.900\)']:
            self.assertTrue(policy.math_issues(policy.prepare(wrong,['a']),['a']))
        self.b['text']='이 문제에서는 π=3으로 계산한다.'
        policy=ReviewPolicy([self.b,{**self.b,'id':'other','text':'원주율'}])
        self.assertFalse(policy.math_issues(r'\(2\pi=6\)',['a']))
        self.assertTrue(policy.math_issues(r'\(2\pi=6\)',['other']))
        self.assertTrue(policy.math_issues(r'\(2\pi=7\)',['a']))

    def test_intact_long_formula_preserved_but_never_fill_missing_symbols(self):
        p=ReviewPolicy([self.b])
        text=r'외력이 한 일은 $W_{ext}=\int_{x_i}^{x_f}F_{ext}\,dx=\Delta U_s$예요.'
        raw=response('a');raw['concepts'][0]['segments'][1]['text']=text
        actual=self.validate(raw)
        self.assertEqual(actual['coverage'][0]['state'],'summarized')
        self.assertIn(r'\Delta U_s',actual['concepts'][0]['explanation'])
        damaged=r'\(m_2gh\u000a'+'\ni?\n는 에너지예요.'
        self.assertEqual(p.prepare(damaged,['a']),r'\(m_2gh\)는 에너지예요.')
        incomplete=r'\(m_2g+\u000a'+'\ni?\n는 에너지예요.'
        self.assertEqual(p.prepare(incomplete,['a']),incomplete)
        self.assertTrue(p.math_issues(incomplete,['a']))
        damaged=r'\(h=d\sin\theta'+'\n\ni?\n'
        self.assertEqual(p.prepare(damaged,['a']),r'\(h=d\sin\theta\)')
        self.assertTrue(p.math_issues(r'\(x=2',['a']))
        for text in ['`$x=2$`','```python\nvalue = "$x=2$"\n```','가격은 $12예요.','결과는\n이에요.']:
            self.assertEqual(p.prepare(text,['a']),text)

    def test_exercise_selection_cannot_hide_a_new_general_principle(self):
        b={**self.b,'text':'예제 1. 변위를 구하라.','planRole':'illustration','hasVisual':True}
        item={'reason':'같은 방법의 숫자 대입을 생략해요.',
              'exerciseSelection':{'kind':'worked_example','sourceQuote':'예제 1.','keptConceptTitle':''}}
        self.assertTrue(exercise_exclusion(item,b,[b],[]))
        self.assertFalse(exercise_exclusion(item,{**b,'planRole':'teaching','hasVisual':False},[b],[]))
        self.assertFalse(exercise_exclusion(item,{**b,'text':'정의: 변위는 위치 변화다.'},[b],[]))
        item['exerciseSelection']['keptConceptTitle']='새로운 조건'
        self.assertFalse(exercise_exclusion(item,b,[b],[]))
        self.assertTrue(exercise_exclusion(item,b,[b],[{'title':'새로운 조건','body':'조건 설명'}]))

    def test_visual_exercise_can_use_native_heading_but_not_cross_theory_boundary(self):
        heading={**self.b,'id':'h','text':'[2021 기출]','kind':'heading'}
        picture={**self.b,'text':'','hasVisual':True,'planRole':'teaching'}
        item={'exerciseSelection':{'kind':'worked_example','sourceQuote':'그림 속 주어진 수치를 대입한 풀이',
                                  'keptConceptTitle':'유지한 원리'}}
        parts=[{'title':'유지한 원리','body':'일반 관계와 필수 조건을 설명해요.'}]
        self.assertTrue(exercise_exclusion(item,picture,[heading,picture],parts))
        theory={**heading,'id':'theory','text':'새로운 독립 원리'}
        self.assertFalse(exercise_exclusion(item,picture,[heading,theory,picture],parts))
        self.assertFalse(exercise_exclusion(item,picture,[picture],parts))


class AdmissionTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.folder=Path(tmp.name);self.wallet=self.folder/'wallet.json'
        self.wallet.write_text(json.dumps({'version':1,'liveBilling':True,'baselineCredits':0,
            'highWaterCredits':0,'purchases':[{'credits':'10'}],
            'creditOperations':{},'creditCharges':{},'creditHolds':{}}))
        self.billing=Billing(self.wallet,'test','summary')
        self.p=SimpleNamespace(context={'strategy':'newest-k1-1-3','kind':'region_study'},
            folder=self.folder,_lock=threading.RLock(),billing=self.billing,
            ledger={'requests':[]},ledger_path=self.folder/'ledger.json')
        self.p._complete_admitted=lambda payload,**kw:Provider._complete_admitted(self.p,payload,**kw)
        self.poll=patch('pdf_k113_admission.POLL_SECONDS',.01);self.poll.start();self.addCleanup(self.poll.stop)

    def test_parallel_waiters_resume_without_consuming_attempts_or_locking_settlement(self):
        sent=[]
        def complete(payload,**kw):
            a=kw['_hedge_attempt'];a.check()
            entry={'requestId':a.token,'reservedUsd':float(Decimal(6)/RATE),'state':'reserved'}
            with self.p._lock:
                Provider.reserve_credits(self.p,entry)
                self.p.ledger['requests'].append(entry);a.entry=entry
            a.update(networkPhase='uploading_request');sent.append(a.index)
            time.sleep(.035)
            with self.p._lock:
                entry.update(state='settled',estimatedUsd=float(Decimal('.1')/RATE))
                self.billing.settle(entry['requestId'],entry['estimatedUsd'])
            return {'ok':True}
        self.p._complete_once=complete
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(FourAttemptRace(self.p,{},{}).run) for _ in range(8)]
            results=[f.result(timeout=5) for f in futures]
        self.assertEqual(results,[{'ok':True}]*8)
        self.assertEqual(sent,[0]*8)
        self.assertEqual(len(self.p.ledger['requests']),8)
        self.assertTrue(any(e.get('reservationWaitChecks',0)>4 for e in self.p.ledger['requests']))
        self.assertFalse(self.billing.exhausted)

    def test_waiting_loser_is_cancelled_without_post_and_real_shortfall_stops(self):
        self.billing.reserve('other',float(Decimal(6)/RATE))
        calls=[]
        def complete(payload,**kw):
            Provider.reserve_credits(self.p,{'requestId':'never-sent','reservedUsd':float(Decimal(6)/RATE)})
            calls.append('sent')
        self.p._complete_once=complete
        race=FourAttemptRace(self.p,{},{});a=race.attempts[0]
        race.launch(a);time.sleep(.03);a.stop('hedge_superseded')
        self.assertTrue(a.finished.wait(1));self.assertIsInstance(a.error,InterruptedError)
        self.assertFalse(calls);self.assertIsNone(a.sent)
        self.billing.settle('other',float(Decimal(6)/RATE))
        with self.assertRaises(CreditExceeded):self.p._complete_admitted({})

    def test_operation_holds_resume_but_unknown_cost_does_not_bypass_cap(self):
        self.p.spent=.9;self.p.max_usd=1
        self.p.ledger['requests']=[{'state':'reserved','reservedUsd':.9}]
        def complete(payload,**kw):
            if self.p.spent+.2>1:
                error=BudgetExceeded('operation cap');error.operation_wait_usd=.2;raise error
            return {'ok':True}
        self.p._complete_once=complete
        def release():
            with self.p._lock:
                self.p.spent=.01;self.p.ledger['requests'][0]['state']='settled'
        timer=threading.Timer(.04,release);timer.start()
        self.assertEqual(self.p._complete_admitted({}),{'ok':True});timer.join()
        self.p.spent=.9;self.p.ledger['requests'][0]['state']='usage_unknown'
        with self.assertRaises(BudgetExceeded):self.p._complete_admitted({})


if __name__=='__main__':unittest.main()
