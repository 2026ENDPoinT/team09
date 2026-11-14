"""No network: idempotent foreground cancellation, private receipts and charges."""
import io
import json
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from pdf_k120_control import ForegroundControl
from test_pdf_responses_transport import native


class ForegroundControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.entry={'requestId':'request_fixture','state':'reserved','reservedUsd':.1,
                    'responseCacheKey':'private','logicalResponseCacheKey':'canonical'}
        self.provider=SimpleNamespace(_lock=threading.RLock(),spent=.1,key='fixture',
            model='gpt-6-luna',ledger={'requests':[self.entry]},ledger_path=self.folder/'usage.json',
            settle_credits=Mock())
        self.cache=self.folder/'private.json';self.canonical=self.folder/'canonical.json'
        self.canonical.write_text('{"winner":"unchanged"}')
        self.control=ForegroundControl(self.provider,self.entry,self.cache)
        self.socket=Mock();self.control.bind_socket(self.socket)
        self.calls=[]
        self.opener=patch('pdf_k120_control.urllib.request.urlopen',side_effect=self.open)
        self.opener.start();self.addCleanup(self.opener.stop)
        sleep=patch('pdf_k120_control.time.sleep',return_value=None);sleep.start();self.addCleanup(sleep.stop)
        self.reply=native()

    def open(self,request,timeout):
        self.calls.append(request)
        self.socket.shutdown.assert_called()
        self.assertEqual(request.method,'GET');self.assertNotIn('/cancel',request.full_url)
        if isinstance(self.reply,Exception):raise self.reply
        return io.StringIO(json.dumps(self.reply))

    def test_loser_receipt_settled_once_and_only_private_cache_written(self):
        self.control.acknowledge('resp_fixture')
        self.control.stop();self.control.stop()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.entry['state'],'settled')
        self.assertAlmostEqual(self.provider.spent,self.entry['estimatedUsd'])
        self.provider.settle_credits.assert_called_once_with(self.entry)
        self.assertEqual(json.loads(self.cache.read_text()),{'ok':True})
        self.assertEqual(json.loads(self.canonical.read_text()),{'winner':'unchanged'})
        self.assertEqual(json.loads(self.cache.with_suffix('.stop.receipt.json').read_text()),native())

    def test_normal_stream_settlement_winner_cannot_be_charged_again(self):
        self.entry.update(state='settled',estimatedUsd=.0001)
        self.provider.spent=.0001
        self.control.acknowledge('resp_fixture');self.control.stop()
        self.assertEqual(self.provider.spent,.0001)
        self.assertEqual(self.entry['estimatedUsd'],.0001)

    def test_404_does_not_release_hold_or_create_success(self):
        self.reply=urllib.error.HTTPError('https://api.openai.com',404,'not stored',{},None)
        self.control.acknowledge('resp_fixture');self.control.stop();self.control.stop()
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.provider.spent,.1);self.assertEqual(self.entry['state'],'reserved')
        self.provider.settle_credits.assert_not_called();self.assertFalse(self.cache.exists())
        self.assertEqual(self.entry['foregroundStopReceiptHttpStatus'],404)

    def test_no_id_stop_closes_header_socket_without_any_get(self):
        self.control.stop()
        self.socket.shutdown.assert_called_once()
        self.assertEqual(self.calls,[])
        another=Mock();self.control.bind_socket(another);another.shutdown.assert_called_once()
        self.assertEqual(self.provider.spent,.1)

    def test_late_id_after_stop_recovers_without_blocking_acknowledgement(self):
        self.control.stop()
        finished=threading.Event();original=self.control._recover
        def recover(ident):
            try:original(ident)
            finally:finished.set()
        self.control._recover=recover
        self.control.acknowledge('resp_fixture')
        self.assertTrue(finished.wait(2))
        self.control.acknowledge('resp_fixture');self.control.stop()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.entry['state'],'settled')

    def test_wrong_response_identity_is_not_billed_or_cached(self):
        self.reply['id']='resp_someone_else'
        self.control.acknowledge('resp_fixture');self.control.stop()
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.provider.spent,.1)
        self.assertFalse(self.cache.exists());self.provider.settle_credits.assert_not_called()

    def test_bad_json_still_bills_real_usage_without_publishing_result(self):
        self.reply['output'][1]['content'][0]['text']='{"ok":true,"ok":false}'
        self.control.acknowledge('resp_fixture');self.control.stop()
        self.assertEqual(self.entry['state'],'settled')
        self.assertFalse(self.cache.exists());self.assertTrue(self.entry['foregroundStopResultInvalid'])

    def test_terminal_without_usage_keeps_reserve_and_receipt(self):
        self.reply.pop('usage');self.control.acknowledge('resp_fixture');self.control.stop()
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.entry['state'],'usage_unknown');self.assertEqual(self.provider.spent,.1)
        self.assertNotIn('estimatedUsd',self.entry)
        self.assertTrue(self.cache.with_suffix('.stop.receipt.json').is_file())

    def test_nonprivate_result_never_overwrites_canonical_cache(self):
        self.entry['responseCacheKey']='canonical'
        control=ForegroundControl(self.provider,self.entry,self.canonical)
        control.bind_socket(self.socket);control.acknowledge('resp_fixture');control.stop()
        self.assertEqual(json.loads(self.canonical.read_text()),{'winner':'unchanged'})
        self.assertFalse(self.canonical.with_suffix('.responses.raw.json').exists())

    def test_schema_invalid_complete_json_keeps_only_receipt(self):
        control=ForegroundControl(self.provider,self.entry,self.cache,
            schema={'type':'object','properties':{'different':{'type':'string'}},'required':['different']})
        control.bind_socket(self.socket);control.acknowledge('resp_fixture');control.stop()
        self.assertFalse(self.cache.exists());self.assertEqual(self.entry['state'],'settled')


if __name__=='__main__':unittest.main()
