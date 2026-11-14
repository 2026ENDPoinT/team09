"""Trusted batch envelopes retain normal caps, pixels and failure accounting."""
import io
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch
import urllib.error

import pdf_ai as ai


class BatchEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('No network'))
        self.guard.start();self.addCleanup(self.guard.stop)
        self.reply={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':20,
                     'prompt_tokens_details':{'cached_tokens':0,'cache_write_tokens':0}}}
        self.payload={'task':'region_teaching_batch','units':{},'imageOrder':[]}
        self.image={'width':20,'height':20,'data':'data:image/png;base64,unchanged',
                    'sourceLabel':'Original source label'}

    def provider(self):
        send=Mock(return_value=self.reply)
        p=ai.Provider(self.folder/str(len(list(self.folder.iterdir()))),True,1,transport=send)
        return p,send

    def test_normal_four_image_ceiling_still_rejects_before_reservation(self):
        p,send=self.provider()
        with self.assertRaises(ValueError):p.complete(self.payload,image=[self.image]*5)
        self.assertEqual(p.ledger['requests'],[]);send.assert_not_called()

    def test_trusted_eight_and_sixteen_preserve_every_image_and_per_unit_output_ceiling(self):
        for count in (8,16):
            with self.subTest(count=count):
                p,send=self.provider();p.context={'kind':'region_study','reasoningEffort':'none'}
                result=p.complete(self.payload,image=[self.image]*count,image_limit=count,
                                  max_output=18000*(count//4))
                self.assertEqual(result,{'ok':True})
                body=send.call_args.args[0]
                images=[v['image_url'] for v in body['messages'][1]['content'] if v['type']=='image_url']
                self.assertEqual(images,[{'url':self.image['data'],'detail':'high'}]*count)
                self.assertEqual(body['max_completion_tokens'],18000*(count//4))
                self.assertEqual(body['reasoning_effort'],'none')
                self.assertEqual(len(p.ledger['requests']),1)
                self.assertRegex(p.ledger['requests'][0]['responseCacheKey'],r'^[a-f0-9]{64}$')

    def test_invalid_explicit_caps_and_overflow_never_send(self):
        for limit in (True,8.0,0,5,32):
            p,send=self.provider()
            with self.assertRaises(ValueError):p.complete(self.payload,image=[self.image],image_limit=limit)
            send.assert_not_called()
        p,send=self.provider()
        with self.assertRaises(ValueError):p.complete(self.payload,image=[self.image]*9,image_limit=8)
        send.assert_not_called()

    def test_context_bound_still_checks_the_whole_batch_before_sending(self):
        p,send=self.provider();p.input_bound_limit=10
        with self.assertRaises(ai.ContextBudgetExceeded):
            p.complete(self.payload,image=[self.image]*8,image_limit=8)
        send.assert_not_called();self.assertEqual(p.ledger['requests'],[])

    def test_api_schema_diagnostics_redact_secrets_and_keep_uncertain_reservation(self):
        secret='sk-local-test-secret'
        detail={'error':{'type':'invalid_request_error','param':'response_format',
                         'message':'Invalid schema; hidden value '+secret}}
        error=urllib.error.HTTPError('https://api.openai.com/v1/chat/completions',400,'Bad request',{},
                                    io.BytesIO(json.dumps(detail).encode()))
        with patch.object(ai,'api_key',return_value=secret),patch.object(ai.urllib.request,'urlopen',side_effect=error):
            p=ai.Provider(self.folder/'error',True,1);p.rate_directory=self.folder/'slots'
            with self.assertRaises(ai.AiResponseError):p.complete(self.payload)
        entry=p.ledger['requests'][0]
        self.assertEqual(entry['state'],'failed_or_uncertain')
        self.assertEqual(entry['apiError']['param'],'response_format')
        self.assertNotIn(secret,p.ledger_path.read_text())
        self.assertIn('[redacted]',entry['apiError']['message'])
        self.assertGreater(p.spent,0)


if __name__=='__main__':unittest.main()
