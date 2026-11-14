"""Offline actual billing tests. All provider calls mocked; only temporary wallets are modified."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import soniox_billing as sb
from pdf_credit_billing import RATE
from credit_reservations import owner


class Response:
    status_code = 200
    def __init__(self, entries, cursor=None):
        self.data = {'usage_logs': entries, 'next_page_cursor': cursor}
    def json(self): return deepcopy(self.data)


class Session:
    def __init__(self, pages): self.pages, self.calls = list(pages), []
    def get(self, url, **kwargs):
        self.calls.append((url, deepcopy(kwargs)))
        return self.pages.pop(0)


class BillingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wallet = self.root / 'credits-wallet.json'
        self.wallet.write_text(json.dumps({'version':1, 'liveBilling':True, 'baselineCredits':'0', 'highWaterCredits':'7',
            'purchases':[{'credits':1000}], 'creditOperations':{'pdf-existing':{'category':'summary', 'credits':'7'}},
            'creditCharges':{'pdf-charge':{'usd':'0.01','credits':'7','operationId':'pdf-existing'}},
            'creditHolds':{'pdf-hold':{'credits':'3','operationId':'pdf-existing',**owner(self.wallet)}}}))
        self.initial_pdf = json.loads(self.wallet.read_text())
        self.ledger = self.create('lecture-one', 'part-1')
        self.now = datetime.now(timezone.utc)

    def create(self, lecture, part):
        ledger = self.root / (part + '.json')
        ledger.write_text(json.dumps({'lectureId':lecture, 'operationId':'voice-' + part,
            'walletPath':str(self.wallet), 'createdAt':sb.now_iso(), 'createdAtMs':1000,
            'sealed':False, 'state':'capturing', 'settledCredits':'0', 'settledUsd':'0', 'requests':{}}))
        return ledger

    def request(self, ref, model='stt-rt-v5', ledger=None):
        ledger = ledger or self.ledger
        sb.request_started(ledger, ref, model); sb.request_state(ledger, ref, 'submitted')
        sb.request_state(ledger, ref, 'completed')

    def log(self, ref, usd, identifier=None, model='stt-rt-v5'):
        return {'uuid':identifier or 'uuid-' + ref, 'request_scope':'api', 'client_reference_id':ref, 'model':model, 'cost_usd':usd}

    def settle(self, logs, ledger=None):
        session = Session([Response(logs)])
        return sb.reconcile(ledger or self.ledger, session=session, key='fake-key', now=self.now), session

    def test_realtime_reconnect_recovery_and_duplicate_pages(self):
        self.request('rt1'); self.request('rt2'); self.request('recovery', 'stt-async-v5')
        sb.seal(self.ledger, 3600000)
        rt = self.log('rt1','0.08')
        session = Session([Response([rt, self.log('unrelated','500')], 'next'),
            Response([rt, self.log('rt2','0.025'), self.log('recovery','0.015', model='stt-async-v5')])])
        result = sb.reconcile(self.ledger, session, 'fake-key', self.now)
        self.assertEqual(result['state'], 'settled')
        self.assertEqual(Decimal(result['settledUsd']), Decimal('.12'))
        self.assertEqual(Decimal(result['settledCredits']), Decimal('.12')*RATE)  # NO 1.002 multiplier
        wallet = json.loads(self.wallet.read_text())
        self.assertEqual(Decimal(wallet['highWaterCredits']), Decimal(7)+Decimal('.12')*RATE)
        self.assertEqual(wallet['creditOperations']['voice-part-1']['durationMs'], 3600000)
        self.assertFalse(wallet['creditOperations']['voice-part-1']['estimated'])
        self.assertEqual(wallet['creditOperations']['pdf-existing'],self.initial_pdf['creditOperations']['pdf-existing'])
        self.assertEqual(wallet['creditHolds'],self.initial_pdf['creditHolds'])
        self.assertEqual(wallet['creditCharges']['pdf-charge'],self.initial_pdf['creditCharges']['pdf-charge'])
        self.assertEqual(session.calls[1][1]['params']['cursor'],'next')
        self.assertEqual(session.calls[0][1]['params']['start_time'],session.calls[1][1]['params']['start_time'])
        prior = self.wallet.read_text()
        result, no_call = self.settle([], self.ledger)
        self.assertEqual(len(no_call.calls),0); self.assertEqual(prior,self.wallet.read_text())

    def test_delayed_logs_partial_then_exactly_once(self):
        self.request('rt'); self.request('recovery', 'stt-async-v5'); sb.seal(self.ledger,1000)
        result, _ = self.settle([self.log('rt','.02')])
        self.assertEqual(result['state'],'pending'); self.assertEqual(result['pendingRequests'],1)
        self.assertEqual(Decimal(result['settledUsd']),Decimal('.02'))
        result, _ = self.settle([self.log('rt','.02'),self.log('recovery','.005',model='stt-async-v5')])
        self.assertEqual(result['state'],'settled'); self.assertEqual(Decimal(result['settledUsd']),Decimal('.025'))
        self.assertEqual(len(json.loads(self.wallet.read_text())['creditCharges']),3)

    def test_missing_or_permission_failure_never_treated_as_zero(self):
        self.request('rt'); sb.seal(self.ledger,1000)
        result, _ = self.settle([]); self.assertEqual(result['state'],'pending')
        session = Session([])
        session.get = lambda *a,**k: type('Denied',(),{'status_code':403})()
        result=sb.reconcile(self.ledger,session,'fake-key',self.now)
        self.assertEqual(result['state'],'pending');self.assertEqual(result['lastError'],'usage_http_403')
        self.assertEqual(json.loads(self.wallet.read_text())['highWaterCredits'],'7')

    def test_pause_resume_separate_operations_same_lecture(self):
        self.request('first');sb.seal(self.ledger,1000); self.settle([self.log('first','.01')])
        second=self.create('lecture-one','part-2');self.request('second',ledger=second);sb.seal(second,1000)
        self.settle([self.log('second','.02')],second)
        wallet=json.loads(self.wallet.read_text());self.assertEqual(Decimal(wallet['highWaterCredits']),Decimal(7)+Decimal('.03')*RATE)
        self.assertEqual(set(wallet['creditOperations']),{'pdf-existing','voice-part-1','voice-part-2'})

    def test_crash_replay_after_debit_before_ledger_ack(self):
        self.request('rt');sb.seal(self.ledger,1000)
        original_save=sb.save
        def crash_ack(path, data):
            if Path(path)==self.ledger and data.get('state')=='settled': raise OSError('crash')
            return original_save(path,data)
        with patch.object(sb,'save',side_effect=crash_ack):
            with self.assertRaises(OSError):self.settle([self.log('rt','.03')])
        # Debit survived; its UUID makes replay safe.
        debit=json.loads(self.wallet.read_text())['highWaterCredits']
        result,_=self.settle([self.log('rt','.03')]);self.assertEqual(result['state'],'settled')
        self.assertEqual(json.loads(self.wallet.read_text())['highWaterCredits'],debit)

    def test_no_submission_has_no_charge_but_uncertain_submission_stays_pending(self):
        sb.request_started(self.ledger,'not-sent','stt-rt-v5');sb.seal(self.ledger,0,True)
        result,session=self.settle([]);self.assertEqual(result['state'],'settled');self.assertEqual(len(session.calls),0)
        second=self.create('lecture-two','unknown');self.request('uncertain',ledger=second);sb.seal(second,1000,True)
        result,_=self.settle([],second);self.assertEqual(result['state'],'pending')

    def test_invalid_cost_is_not_debited(self):
        self.request('rt');sb.seal(self.ledger,1000)
        for cost in ['NaN','-1','Infinity','bad']:
            result,_=self.settle([self.log('rt',cost)])
            self.assertEqual(result['state'],'pending')
        self.assertEqual(json.loads(self.wallet.read_text())['highWaterCredits'],'7')

    def test_key_model_scope_matching(self):
        self.request('rt');sb.seal(self.ledger,1000)
        wrong=self.log('rt','.1',model='other-model')
        result,_=self.settle([wrong]);self.assertEqual(result['state'],'pending')
        self.assertEqual(json.loads(self.wallet.read_text())['highWaterCredits'],'7')

if __name__ == '__main__': unittest.main()
