"""Old pre-write failures can be repaired offline; ambiguous paid POSTs stay protected."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from pdf_study_receipts import proven_unsent,reconcile


def failure():
    return {'requestId':'a'*32,'state':'failed_or_uncertain','inputApi':'responses','kind':'region_plan',
        'sentAtMs':1,'reservedUsd':.01,'httpTransport':'pooled_http1_no_retries',
        'transportFailurePhase':'connecting','requestWriteAttempted':False,
        'requestBodyBytesSent':0,'requestWireBytesSent':0,'requestBodyBytesAttemptedUpperBound':0,
        'responseCacheKey':'b'*64,'errorType':'StudyConnectionError'}


class UnsentReceiptTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        (self.root/'usage').mkdir();self.path=self.root/'usage/old.json'
        self.provider=SimpleNamespace(folder=self.root,ledger_path=self.root/'usage/current.json',
            ledger={'operationId':'current','model':'fixture','requests':[]},model='fixture',
            transport=None,key='test-only',billing=None,study_recovery_window=3)
    def save(self,entries):
        self.path.write_text(json.dumps({'operationId':'old','model':'fixture','requests':entries,'category':'planning'}))
    def test_only_complete_prewrite_diagnostics_prove_no_post(self):
        entry=failure();original=copy.deepcopy(entry);self.assertTrue(proven_unsent(entry));self.assertEqual(entry,original)
        for key,value in [('requestWireBytesSent',1),('requestBodyBytesAttemptedUpperBound',1),
                          ('requestBodyBytesSent',False),('requestWriteAttempted',True),
                          ('transportFailurePhase','waiting_headers'),('httpTransport','unknown'),
                          ('responseId','resp_original'),('requestUploadComplete',True)]:
            with self.subTest(key=key):
                modified={**entry,key:value};self.assertFalse(proven_unsent(modified))
        for key in ['requestWriteAttempted','requestWireBytesSent','requestBodyBytesAttemptedUpperBound']:
            modified=copy.deepcopy(entry);del modified[key];self.assertFalse(proven_unsent(modified))
    def test_old_unsent_is_repaired_but_sent_unknown_entry_and_history_stay_intact(self):
        unsent=failure();sent={**failure(),'requestId':'c'*32,'requestWriteAttempted':True,
            'transportFailurePhase':'waiting_headers','requestBodyBytesSent':200,'requestWireBytesSent':400,
            'requestBodyBytesAttemptedUpperBound':200,'requestUploadComplete':True}
        self.save([unsent,sent]);opener=Mock(side_effect=AssertionError('No network'))
        self.assertEqual(reconcile(self.provider,open_url=opener),[]);opener.assert_not_called()
        entries=json.loads(self.path.read_text())['requests']
        self.assertEqual(entries[0]['state'],'not_sent');self.assertEqual(entries[0]['estimatedUsd'],0)
        self.assertEqual(entries[0]['sentAtMs'],unsent['sentAtMs']);self.assertEqual(entries[0]['errorType'],unsent['errorType'])
        self.assertEqual(entries[1],sent);self.assertNotIn('receiptLookupHttpStatus',entries[1])
    def test_zero_settlement_retries_after_an_interrupted_wallet_write(self):
        self.save([failure()]);self.provider.billing=SimpleNamespace(path=self.root/'wallet.json',category='planning')
        billing=Mock();billing.settle.side_effect=[OSError('fixture interrupted settlement'),None]
        opener=Mock(side_effect=AssertionError('No network'))
        with patch('pdf_credit_billing.Billing',return_value=billing):
            with self.assertRaises(OSError):reconcile(self.provider,open_url=opener)
            self.assertTrue(json.loads(self.path.read_text())['requests'][0]['notSentBillingPending'])
            reconcile(self.provider,open_url=opener)
        entry=json.loads(self.path.read_text())['requests'][0]
        self.assertEqual(entry['state'],'not_sent');self.assertNotIn('notSentBillingPending',entry)
        self.assertEqual(billing.settle.call_count,2)
        self.assertTrue(all(call.args==('a'*32,0)for call in billing.settle.call_args_list));opener.assert_not_called()


if __name__=='__main__':unittest.main()
