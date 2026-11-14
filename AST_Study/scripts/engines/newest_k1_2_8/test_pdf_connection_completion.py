"""Lost sockets, receipt ownership and repeat-charge protection. No paid APIs."""
import copy,io,json,tempfile,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
import urllib3
from pdf_study_http import StudyHttpTransport
from pdf_study_upload import ProgressHTTPPool,ProgressHTTPConnection,_POLICY
from test_pdf_study_upload import receiver,request
from test_pdf_study_pooled_http import server
import test_pdf_study_chat as chat_fixture
from test_pdf_study_chat import sse,chunk
from pdf_study_chat import request_once
from pdf_study_receipts import stored_original
from pdf_ai import Provider
from pdf_credit_billing import Billing,wallet_lock


class UploadCompletionTests(unittest.TestCase):
    def test_incomplete_length_framed_json_can_reconnect_but_only_one_full_body_arrives(self):
        body=json.dumps({'source':'x'*200000}).encode()
        attempts=[]
        class DropOnce(ProgressHTTPConnection):
            def send(self,data):
                if not getattr(self,'_synesis_sending_headers',True)and not attempts:
                    attempts.append(1);super().send(data[:32768]);raise TimeoutError('Lost before remaining body was attempted')
                return super().send(data)
        with receiver()as(url,records),patch.object(ProgressHTTPPool,'ConnectionCls',DropOnce):
            transport=StudyHttpTransport();fields={}
            try:
                with transport.open(request(url,body),3,update=lambda **x:fields.update(x))as stream:
                    self.assertEqual(json.load(stream)['bytes'],len(body))
                self.assertEqual(sum('sha256'in r for r in records),1)
                self.assertEqual(fields['reconnectSafety'],'complete_json_body_never_attempted')
                self.assertEqual(fields['unsentConnectionReconnects'],1)
            finally:transport.close()

    def test_last_chunk_might_have_arrived_so_successful_count_is_not_used_as_proof(self):
        transport=StudyHttpTransport();body=json.dumps({'source':'x'*20000}).encode()
        def ambiguous(*args,**kwargs):
            policy=_POLICY.value;policy.phase='uploading_request';policy.write_attempted=True
            policy.body_sent=len(body)-10;policy.body_attempted_upper=len(body)
            raise urllib3.exceptions.ProtocolError('Last send failed without exact count')
        try:
            with patch.object(transport.pool,'request',side_effect=ambiguous)as call:
                with self.assertRaises(urllib.error.URLError)as error:
                    transport.open(request('https://api.openai.com/v1/chat/completions',body),3)
                self.assertEqual(call.call_count,1)
                self.assertFalse(getattr(error.exception,'request_not_sent',False))
        finally:transport.close()

    def test_three_unsent_connection_interruptions_recover_without_duplicate_post(self):
        with server('normal')as(url,records,_,__):
            t=StudyHttpTransport(max_unsent_attempts=4);original=t.pool.request;n=[0]
            def interrupted(*args,**kwargs):
                n[0]+=1
                if n[0]<4:raise urllib3.exceptions.NewConnectionError(None,'not connected')
                return original(*args,**kwargs)
            try:
                with patch.object(t.pool,'request',side_effect=interrupted):
                    with t.open(request(url,b'{}'),5)as stream:self.assertEqual(json.load(stream),{'ok':True})
                self.assertEqual(len(records),1);self.assertEqual(n[0],4)
            finally:t.close()


class DelayedReceiptTests(unittest.TestCase):
    def test_restarted_background_job_is_waited_for_without_creating_another_generation(self):
        from test_pdf_responses_transport import native
        now=[0.];calls=[]
        def opener(req,timeout):
            calls.append(req.method)
            value=native()if now[0]>40 else {'id':'resp_fixture','status':'in_progress'}
            return io.StringIO(json.dumps(value))
        value=stored_original({'inputApi':'responses','responseId':'resp_fixture'},key='fixture',
            open_url=opener,wait_window=180,check=lambda:None,
            clock=lambda:now[0],sleep=lambda s:now.__setitem__(0,now[0]+s))
        self.assertEqual(value[1],{'ok':True});self.assertEqual(set(calls),{'GET'})
        self.assertGreater(now[0],40)

    def test_delayed_stored_completion_outlives_old_twenty_second_window(self):
        f=chat_fixture.ChatRecoveryTests();now=[0.];calls=[]
        native=f.terminal()
        def opener(req,timeout):
            calls.append(req.method)
            if req.method=='POST':return sse([chunk('{"ok":')],done=False)
            if now[0]<45:raise urllib.error.HTTPError(req.full_url,404,'Still being stored',{},io.BytesIO(b'{}'))
            return io.StringIO(json.dumps(native))
        result=request_once(f.request(),open_url=opener,update=lambda **x:None,
            clock=lambda:now[0],sleep=lambda s:now.__setitem__(0,now[0]+s),
            recovery_window=180,recovery_reads=18,recovery_timeout=20)
        self.assertEqual(result,native);self.assertEqual(calls.count('POST'),1);self.assertGreater(now[0],20)

    def test_cancel_during_recovery_backoff_is_immediate_and_never_posts_again(self):
        f=chat_fixture.ChatRecoveryTests();calls=[];checks=[0]
        def opener(req,timeout):
            calls.append(req.method)
            return sse([chunk('{')],done=False)if req.method=='POST'else io.StringIO('{}')
        def check():
            checks[0]+=1
            if checks[0]>5:raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            request_once(f.request(),open_url=opener,check=check,update=lambda **x:None,
                sleep=lambda _:None,recovery_window=180,recovery_reads=18)
        self.assertEqual(calls.count('POST'),1)


class PersistedReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.tag='a'*32;self.cache='b'*64
        self.entry={'requestId':self.tag,'payloadHash':'c'*64,'inputApi':'chat','kind':'region_study',
            'unitIds':['unit'],'responseCacheKey':self.cache,'state':'failed_or_uncertain',
            'reservedUsd':.02,'sentAtMs':1,'chatCompletionId':'chatcmpl_fixture','recoveryRequestTag':self.tag}
        self.native={'id':'chatcmpl_fixture','metadata':{'synesis_request_id':self.tag},
            'choices':[{'message':{'content':'{"concepts":[]}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':20}}
        self.ledger={'operationId':'original','model':'gpt-6-luna','requests':[self.entry]}
        (self.folder/'usage').mkdir();self.path=self.folder/'usage/original.json'
        self.path.write_text(json.dumps(self.ledger))
        self.provider=Provider(self.folder,True,.1,transport=lambda _:self.fail('New generation forbidden'))
        self.calls=[]
    def opener(self,req,timeout):
        self.calls.append(req.method);self.assertEqual(req.method,'GET')
        return io.StringIO(json.dumps(self.native))
    def test_restart_recovers_exact_paid_value_and_settles_original_unknown_hold_once(self):
        wallet=self.folder/'wallet.json'
        wallet.write_text(json.dumps({'liveBilling':True,'purchases':[{'credits':'100'}],
            'highWaterCredits':0,'baselineCredits':0,'creditOperations':{},'creditHolds':{}}))
        old=Billing(wallet,'original','summary',ledger_path=self.path)
        old.reserve(self.tag,.02);old.settle(self.tag)
        self.provider.billing=Billing(wallet,'new-operation','summary')
        records=self.provider.recover_pending_study(open_url=self.opener)
        self.assertEqual(len(records),1);self.assertEqual(self.calls,['GET'])
        self.assertEqual(self.provider.ledger['requests'],[])
        self.assertEqual(json.loads((self.folder/'generated/paid-responses'/f'{self.cache}.json').read_text()),{'concepts':[]})
        with wallet_lock(wallet)as state:
            self.assertEqual(state['creditCharges'][self.tag]['operationId'],'original')
            self.assertEqual(state['creditOperations']['original']['unknownRequests'],0)
            before=copy.deepcopy(state)
        self.assertEqual(self.provider.recover_pending_study(open_url=self.opener),[])
        with wallet_lock(wallet)as state:self.assertEqual(state,before)
    def test_wrong_id_or_tag_or_duplicate_json_never_recovers_or_settles(self):
        for case in ['id','tag','duplicate','unfinished','usage']:
            with self.subTest(case=case):
                native=copy.deepcopy(self.native)
                if case=='id':native['id']='chatcmpl_other'
                elif case=='tag':native['metadata']['synesis_request_id']='d'*32
                elif case=='duplicate':native['choices'][0]['message']['content']='{"x":1,"x":2}'
                elif case=='unfinished':native['choices'][0]['finish_reason']=None
                else:native['usage']=None
                with patch.object(self,'native',native):
                    self.assertEqual(self.provider.recover_pending_study(open_url=self.opener),[])
                self.assertEqual(json.loads(self.path.read_text()),self.ledger)
                self.assertFalse((self.folder/'generated/paid-responses'/f'{self.cache}.json').exists())
    def test_ambiguous_metadata_listing_never_uses_latest_completion(self):
        entry={**self.entry};entry.pop('chatCompletionId')
        for data,more in [([self.native,self.native],False),([self.native],True),([],False)]:
            result=stored_original(entry,key='fixture',open_url=lambda req,timeout:io.StringIO(json.dumps({'data':data,'has_more':more})))
            self.assertIsNone(result)

    def test_background_original_survives_restart_and_reconciles_without_a_post(self):
        from test_pdf_responses_transport import native
        self.entry.update(inputApi='responses',responseId='resp_fixture')
        self.entry.pop('chatCompletionId');self.entry.pop('recoveryRequestTag')
        self.path.write_text(json.dumps(self.ledger));self.native=native()
        records=self.provider.recover_pending_study(open_url=self.opener)
        self.assertEqual(len(records),1);self.assertEqual(self.calls,['GET'])
        saved=json.loads((self.folder/'generated/paid-responses'/f'{self.cache}.json').read_text())
        self.assertEqual(saved,{'ok':True})
        raw=self.folder/'generated/paid-responses'/f'{self.cache}.responses.raw.json'
        self.assertEqual(json.loads(raw.read_text()),self.native)
        self.assertEqual(json.loads(self.path.read_text())['requests'][0]['responseId'],'resp_fixture')
        self.assertEqual(self.provider.recover_pending_study(open_url=self.opener),[])

    def test_background_original_rejects_wrong_ids_and_unfinished_or_ambiguous_output(self):
        from test_pdf_responses_transport import native
        entry={**self.entry,'inputApi':'responses','responseId':'resp_fixture'}
        for case in ('id','pending','usage','duplicate','commentary'):
            value=native()
            if case=='id':value['id']='resp_other'
            elif case=='pending':value['status']='in_progress'
            elif case=='usage':value['usage']=None
            elif case=='duplicate':value['output'][1]['content']=[{'type':'output_text','text':'{"x":1,"x":2}'}]
            else:value['output'][1]['phase']='commentary'
            with self.subTest(case=case):
                try:found=stored_original(entry,key='fixture',open_url=lambda req,timeout:io.StringIO(json.dumps(value)))
                except ValueError:found=None
                self.assertIsNone(found)


class LatePipelineReceiptTests(unittest.TestCase):
    def test_late_original_finishes_document_without_a_new_generation(self):
        import test_pdf_speed_pipeline as fixture
        import pdf_new_concept_ver99_study as study
        import pdf_ai as ai
        f=fixture.CropPipelineTests();f.setUp();self.addCleanup(f.doCleanups)
        calls=[];lookups=[0];recovered=[False]
        def complete(payload,**options):
            source=payload['blocks'][0]['id'];calls.append((source,options.get('cache_only',False)))
            if source=='source1'and not recovered[0]:raise ai.AiResponseError('Original stream interrupted')
            if source=='source1':self.assertTrue(options.get('cache_only'))
            return f.reply(source)
        p=fixture.FakeProvider(complete)
        def recover():
            lookups[0]+=1
            if lookups[0]==1:return []
            recovered[0]=True
            return [{'unitIds':[study.jobs_for(f.groups)[1]['id']]}]
        p.recover_pending_study=recover
        result,_=f.run_pipeline(lambda _:None,provider=p)
        self.assertTrue(result['processingComplete']);self.assertEqual(result['failedUnits'],[])
        self.assertEqual(sum(not cached for _,cached in calls),3)
        self.assertIn(('source1',True),calls)


class BoundedConnectionRepairTests(unittest.TestCase):
    def setUp(self):
        from test_pdf_responses_provider import ResponsesProviderTests
        self.f=ResponsesProviderTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.p=self.f.provider(mode='chat');self.p.study_recovery_reads=1
        self.p.context={'kind':'region_study','studyConnectionRepairAllowed':True}
        self.calls=[]

    def install(self,*,repair_fails=False,group=False):
        from test_pdf_responses_transport import native
        from test_pdf_study_connection import sse as response_sse,created
        def opener(req,timeout):
            self.calls.append(req)
            if req.full_url.endswith('/cancel'):self.fail('A transient connection loss must not cancel its background job')
            if req.method=='POST':
                if req.full_url.endswith('/chat/completions'):return sse([chunk('{"ok":')],done=False)
                if repair_fails:return response_sse([created()])
                value=native()
                if group:value['service_tier']='default'
                stream=io.StringIO(json.dumps(value));stream.headers={};return stream
            raise urllib.error.HTTPError(req.full_url,404,'No receipt yet',{},io.BytesIO(b'{}'))
        self.f.opener.side_effect=opener

    def test_only_the_lost_exact_unit_gets_one_budgeted_durable_alternate(self):
        import pdf_ai as ai
        self.install()
        resets=[]
        value=ai.complete_study_delivery(self.p,self.f.payload,on_delivery_reset=lambda:resets.append(1),**self.f.options)
        self.assertEqual(value,{'ok':True})
        self.assertEqual(resets,[1])
        self.assertEqual([r.method for r in self.calls],['POST','GET','POST'])
        old,new=self.p.ledger['requests']
        self.assertEqual(old['state'],'failed_or_uncertain');self.assertTrue(old['durableRecoveryConsumed'])
        self.assertEqual(new['durableRecoveryOf'],old['requestId'])
        self.assertAlmostEqual(self.p.spent,old['reservedUsd']+new['estimatedUsd'])
        self.p.billing.settle.assert_any_call(old['requestId'],None)
        body=json.loads(self.calls[-1].data)
        self.assertTrue(body['background']);self.assertTrue(body['stream'])
        self.assertEqual(json.loads(body['input'][1]['content'][0]['text']),self.f.payload)
        before=len(self.calls)
        self.assertEqual(ai.complete_study_delivery(self.p,self.f.payload,**self.f.options),value)
        self.assertEqual(len(self.calls),before)

    def test_failed_alternate_never_loops_and_background_is_not_cancelled_on_network_failure(self):
        import pdf_ai as ai
        self.install(repair_fails=True)
        with self.assertRaises(ai.AiResponseError):ai.complete_study_delivery(self.p,self.f.payload,**self.f.options)
        self.assertEqual(sum(r.method=='POST'for r in self.calls),2)
        self.assertEqual(len(self.p.ledger['requests']),2)
        self.assertEqual(self.p.ledger['requests'][1]['responseId'],'resp_fixture')
        before=len(self.calls)
        with self.assertRaises(ai.AiResponseError):ai.complete_study_delivery(self.p,self.f.payload,**self.f.options)
        self.assertEqual(len(self.calls),before)

    def test_repair_cannot_bypass_budget_or_release_unknown_original_reservation(self):
        import pdf_ai as ai
        self.install();original_reserve=self.p.reserve_credits;count=[0]
        def reserve(entry):
            count[0]+=1
            if count[0]==2:raise ai.BudgetExceeded('Total cap including original reserve')
            return original_reserve(entry)
        self.p.reserve_credits=reserve
        with self.assertRaises(ai.BudgetExceeded):ai.complete_study_delivery(self.p,self.f.payload,**self.f.options)
        self.assertEqual(sum(r.method=='POST'for r in self.calls),1)
        old=self.p.ledger['requests'][0]
        self.assertEqual(self.p.spent,old['reservedUsd']);self.assertFalse(old.get('durableRecoveryConsumed',False))

    def test_group_repair_retains_fast_request_and_actual_standard_downgrade(self):
        import pdf_ai as ai
        self.install(group=True);self.p.context={'kind':'region_plan','studyConnectionRepairAllowed':True}
        payload={'task':'region_groups','targets':[{'id':'s0','text':'source'}]}
        self.assertEqual(ai.complete_study_delivery(self.p,payload,**self.f.options),{'ok':True})
        body=json.loads(self.calls[-1].data)
        self.assertEqual(body['service_tier'],'fast')
        self.assertEqual(json.loads(body['input'][1]['content'][0]['text']),payload)
        self.assertEqual(self.p.ledger['requests'][1]['billedServiceTier'],'default')


if __name__=='__main__':unittest.main()
