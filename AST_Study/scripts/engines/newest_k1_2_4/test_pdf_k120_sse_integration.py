"""K120 Provider through SSE parsing/race/cancellation; no external network."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

import pdf_ai as ai
import test_pdf_k120_provider as provider_fixture
from test_pdf_study_connection import sse,created
from test_pdf_responses_transport import native


class ForegroundSseIntegrationTests(unittest.TestCase):
    setUp=provider_fixture.ForegroundProviderTests.setUp
    provider=provider_fixture.ForegroundProviderTests.provider
    make=provider_fixture.ForegroundProviderTests.make

    def test_real_sse_path_publishes_final_deltas_and_settles_native_usage(self):
        p=self.make();deltas=[]
        def open_url(req,timeout):
            self.assertEqual(req.method,'POST')
            return sse([created(),
                {'type':'response.output_text.delta','item_id':'msg','delta':'{"ok":'},
                {'type':'response.output_text.delta','item_id':'msg','delta':'true}'},
                {'type':'response.completed','response':native()}])
        self.opener.side_effect=open_url
        self.assertEqual(ai.complete_study_delivery(p,self.payload,on_study_delta=deltas.append,
            **self.options),{'ok':True})
        self.assertEqual(''.join(deltas),'{"ok":true}')
        self.assertEqual(self.opener.call_count,1)
        self.assertEqual(p.ledger['requests'][0]['state'],'settled')
        self.assertAlmostEqual(p.spent,p.ledger['requests'][0]['estimatedUsd'])

    def test_four_commentary_failures_exhaust_race_without_fifth_delivery_fallback(self):
        p=self.make();p.study_no_id_hedge=True;posts=[];gets=[]
        def open_url(req,timeout):
            if req.method=='POST':
                self.assertNotIn('/cancel',req.full_url)
                ident='resp_fixture_'+str(len(posts));posts.append(req)
                return sse([{'type':'response.created','response':{'id':ident,'status':'in_progress'}},
                    {'type':'response.output_item.added','item':{'id':'comment','phase':'commentary'}}])
            gets.append(req)
            value=native();value['id']=req.full_url.rsplit('/',1)[1]
            value['status']='cancelled'
            return io.StringIO(json.dumps(value))
        self.opener.side_effect=open_url
        with self.assertRaises(ai.AiResponseError)as failure:
            ai.complete_study_delivery(p,self.payload,**self.options)
        self.assertTrue(failure.exception.study_hedge_exhausted)
        self.assertEqual(len(posts),4);self.assertEqual(len(gets),4)
        self.assertEqual(len(p.ledger['requests']),4)
        self.assertTrue(all(e['state']=='settled'for e in p.ledger['requests']))
        self.assertTrue(all(e['clientStopReason']=='unexpected_commentary'for e in p.ledger['requests']))

    def test_user_cancel_registered_before_headers_closes_creation_socket_without_id(self):
        p=self.make();registered={};connection=Mock();calls=[]
        def open_url(req,timeout,**options):
            calls.append(req)
            self.assertEqual(req.method,'POST')
            self.assertEqual(len(registered),1,'Cancellation must be installed before POST')
            options['on_socket'](connection)
            next(iter(registered.values()))()
            connection.shutdown.assert_called()
            options['on_socket'](None)
            raise InterruptedError('fixture user cancelled before headers')
        p.study_http_transport=SimpleNamespace(open=open_url)
        with patch('pdf_worker_control.register',side_effect=lambda key,callback:registered.update({key:callback})),\
                patch('pdf_worker_control.unregister')as unregister:
            with self.assertRaises(InterruptedError):p.complete(self.payload,**self.options)
        self.assertEqual(len(calls),1);self.assertNotIn('responseId',p.ledger['requests'][0])
        unregister.assert_called_once()
        self.assertGreater(p.spent,0,'Ambiguous post must retain provider cost hold')


if __name__=='__main__':unittest.main()
