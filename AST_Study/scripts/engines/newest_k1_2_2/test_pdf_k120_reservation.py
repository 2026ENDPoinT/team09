"""Local prediction and bounded settlement fixtures; no network or real wallet."""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from pdf_credit_billing import Billing, RATE, available, balance, wallet_lock
from pdf_k120_reservation import estimate, VERSION


def policy(usd):
    return {'strategy':'newest-k1-2-2','reservationPolicy':VERSION,
        'customerSettlementPolicy':'available-balance-v1','reservationMultiplier':1.3,
        'userEstimatedUsd':str(Decimal(str(usd))/Decimal('1.3')),
        'customerReservedUsd':str(usd),'providerUpperBoundUsd':'.2'}


class PredictionTests(unittest.TestCase):
    def test_expected_cost_not_output_cap_and_no_payload_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider=SimpleNamespace(folder=Path(tmp),model='gpt-6-luna',ledger={'requests':[]})
            entry={'strategy':'newest-k1-2-2','kind':'region_study','reservedUsd':.015,
                'inputTokenBound':41000,'maxOutputTokens':18000,'imageInputTokenEstimate':5000,
                'imageDimensions':[[1000,1200]],'payloadHash':'h'}
            payload={'blocks':[{'text':'개념의 정의와 작동 원리를 설명해요.'*10}]}
            messages=[{'content':[{'type':'text','text':'Teach the source.'*800},
                                  {'type':'image_url','image_url':{'url':'data:image/png;base64,'+'A'*200000}}]}]
            before=json.dumps([entry,payload,messages])
            result=estimate(provider,entry,payload=payload,messages=messages,max_output=18000)
            self.assertEqual(json.dumps([entry,payload,messages]),before)
            self.assertAlmostEqual(result['customerReservedUsd'],result['userEstimatedUsd']*1.3)
            self.assertLess(result['customerReservedUsd'],entry['reservedUsd']/2)
            self.assertLess(result['reservationInputTokens'],41000)
            self.assertEqual(result['providerUpperBoundUsd'],.015)
            entry['strategy']='newest-k1-1-3'
            self.assertEqual(estimate(provider,entry),{})

    def test_same_task_confirmed_usage_calibrates_and_unknown_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample={'strategy':'newest-k1-1-3','kind':'region_study','state':'settled',
                'payloadHash':'same','estimatedUsd':.002,'serverTerminalStatus':'completed',
                'usage':{'prompt_tokens':8000,'completion_tokens':2000}}
            provider=SimpleNamespace(folder=Path(tmp),model='gpt-6-luna',ledger={'requests':[
                sample,{**sample,'state':'usage_unknown','estimatedUsd':.2},
                {**sample,'serverTerminalStatus':'cancelled','estimatedUsd':.0001}]})
            entry={'strategy':'newest-k1-2-2','kind':'region_study','payloadHash':'same',
                'reservedUsd':.015,'inputTokenBound':40000}
            result=estimate(provider,entry,max_output=18000)
            self.assertEqual(result['userEstimatedUsd'],.002)
            self.assertEqual(result['customerReservedUsd'],.0026)
            self.assertEqual(result['reservationEstimateSamples'],1)


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'wallet.json'
        self.path.write_text(json.dumps({'liveBilling':True,'purchases':[{'credits':'100'}],
            'baselineCredits':'0','highWaterCredits':'0','creditHolds':{},'creditCharges':{},'creditOperations':{}}))
        self.billing=Billing(self.path,'operation','summary')

    def state(self):
        with wallet_lock(self.path) as wallet:return json.loads(json.dumps(wallet,default=str))

    def hold(self,ident,credits):
        usd=Decimal(credits)/RATE
        self.billing.reserve(ident,usd,reservation_metadata=policy(usd))

    def test_overrun_cannot_consume_other_holds_or_make_balance_negative(self):
        self.hold('first',20);self.hold('second',50)
        receipt=self.billing.settle('first',Decimal(80)/RATE)
        self.assertEqual(Decimal(receipt['credits']),50)
        self.assertEqual(receipt['payer'],'shared')
        self.assertGreater(Decimal(receipt['synesisCoveredUsd']),0)
        state=self.state()
        self.assertEqual(balance(state),50);self.assertEqual(available(state),0)
        self.assertEqual(Decimal(state['creditHolds']['second']['credits']),50)
        self.billing.settle('second',Decimal(70)/RATE)
        self.assertEqual(balance(self.state()),0)
        self.assertFalse(self.state()['creditHolds'])

    def test_free_and_repeated_settlement_do_not_recharge_or_reserve(self):
        self.hold('free',20)
        self.billing.settle('free',0)
        before=self.state()
        self.billing.settle('free',.1);self.hold('free',20)
        self.assertEqual(self.state(),before)
        self.assertEqual(balance(before),100)
        self.hold('same',20);state=self.state();self.hold('same',20)
        self.assertEqual(self.state(),state)

    def test_unknown_then_confirmed_remains_fully_service_funded(self):
        self.hold('unknown',20);self.billing.settle('unknown')
        self.assertEqual(available(self.state()),100)
        self.hold('unknown',20)
        self.assertFalse(self.state()['creditHolds'])
        receipt=self.billing.settle('unknown',.1)
        self.assertEqual(receipt['payer'],'synesis')
        self.assertEqual(Decimal(receipt['customerChargeUsd']),0)
        self.assertEqual(Decimal(receipt['synesisCoveredUsd']),Decimal('.1'))
        self.assertEqual(balance(self.state()),100)

    def test_legacy_policy_keeps_previous_settlement(self):
        self.billing.reserve('legacy',Decimal(20)/RATE)
        receipt=self.billing.settle('legacy',Decimal(30)/RATE)
        self.assertEqual(Decimal(receipt['credits']),30)
        self.assertNotIn('reservationPolicy',receipt)


if __name__=='__main__':unittest.main()
