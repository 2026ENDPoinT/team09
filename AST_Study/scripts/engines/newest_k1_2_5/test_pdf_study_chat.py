"""No paid calls: foreground study streaming, genuine termination and usage."""
import io,json,unittest
from unittest.mock import patch
from pdf_study_chat import collect,request_once
from pdf_study_connection import StudyConnectionError
from test_pdf_responses_provider import ResponsesProviderTests
from test_pdf_responses_transport import FORMAT
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import threading


def sse(chunks,done=True):
 stream=io.BytesIO(b''.join(('data: '+json.dumps(c)+'\n\n').encode()for c in chunks)+(b'data: [DONE]\n\n'if done else b''))
 stream.headers={'Content-Type':'text/event-stream'};return stream

def chunk(text=None,finish=None,usage=None):
 value={'id':'chatcmpl_fixture','model':'gpt-6-luna','choices':[{'index':0,'delta':{'content':text}if text is not None else{},'finish_reason':finish}]}
 if usage is not None:value['usage']=usage
 return value


class ChatStreamTests(unittest.TestCase):
 def test_stream_preserves_actual_service_tier_including_fast_downgrade(self):
  first=chunk('{}');first['service_tier']='default'
  value=collect(sse([first,chunk(finish='stop',usage={'prompt_tokens':12,'completion_tokens':7})]))
  self.assertEqual(value['service_tier'],'default')
 def test_raw_json_is_forwarded_before_terminal_and_usage_stays_exact(self):
  got=[];updates=[];usage={'prompt_tokens':12,'completion_tokens':8,'prompt_tokens_details':{'cached_tokens':5}}
  result=collect(sse([chunk('{"concepts":['),chunk(']}'),chunk(finish='stop'),chunk(usage=usage)]),on_delta=got.append,update=lambda **x:updates.append(x))
  self.assertEqual(got,['{"concepts":[',']}']);self.assertEqual(result['choices'][0]['message']['content'],'{"concepts":[]}')
  self.assertEqual(result['usage'],usage);self.assertEqual(result['choices'][0]['finish_reason'],'stop')
  self.assertTrue(any('firstFinalTextSeconds'in x for x in updates))
 def test_missing_done_never_promotes_a_complete_json_to_success(self):
  with self.assertRaises(StudyConnectionError)as error:collect(sse([chunk('{"ok":true}'),chunk(finish='stop')],done=False))
  self.assertEqual(error.exception.study_partial_response['content'],'{"ok":true}')
  self.assertFalse(error.exception.study_partial_response['terminalReceived'])
 def test_callback_failure_does_not_fail_paid_completion(self):
  def broken(_):raise ValueError('display only')
  self.assertEqual(collect(sse([chunk('{}'),chunk(finish='stop')]),on_delta=broken)['choices'][0]['finish_reason'],'stop')
 def test_cancellation_preserves_partial_without_fabricating_usage(self):
  n=[0]
  def check():
   n[0]+=1
   if n[0]>1:raise InterruptedError('cancel')
  with self.assertRaises(InterruptedError)as error:collect(sse([chunk('{'),chunk('}')]),check=check)
  self.assertEqual(error.exception.study_partial_response['content'],'{');self.assertIsNone(error.exception.study_partial_response['usage'])
 def test_active_long_content_is_not_cut_at_absolute_header_deadline(self):
  now=[0]
  class Active(io.BytesIO):
   def readline(self,*args):now[0]+=4;return super().readline(*args)
  wire=sse([chunk('x')for _ in range(16)]+[chunk(finish='stop')]);stream=Active(wire.getvalue());stream.headers=wire.headers
  self.assertEqual(collect(stream,clock=lambda:now[0])['choices'][0]['message']['content'],'x'*16);self.assertGreater(now[0],45)
 def test_keepalive_is_not_token_progress(self):
  now=[0]
  class Ping(io.BytesIO):
   def readline(self,*args):now[0]+=11;return b': ping\n\n'
  stream=Ping();stream.headers={'Content-Type':'text/event-stream'}
  with self.assertRaises(StudyConnectionError):collect(stream,clock=lambda:now[0])
  self.assertLessEqual(now[0],44)
 def test_response_id_change_is_not_merged(self):
  changed=chunk('b');changed['id']='chatcmpl_other'
  with self.assertRaises(StudyConnectionError):collect(sse([chunk('a'),changed]))
 def test_output_length_and_refusal_remain_truthful(self):
  value=collect(sse([chunk('incomplete'),chunk(finish='length',usage={'prompt_tokens':2,'completion_tokens':7})]))
  self.assertEqual(value['choices'][0]['finish_reason'],'length');self.assertEqual(value['usage']['completion_tokens'],7)
 def test_complete_json_padding_is_bounded_without_promoting_a_terminal_or_usage(self):
  with self.assertRaises(StudyConnectionError)as error:
   collect(sse([chunk('{"ok":true}'),chunk(' '*257),chunk(' '*10000)]),schema=FORMAT['json_schema']['schema'])
  evidence=error.exception.study_partial_response
  self.assertEqual(evidence['completeJsonCandidate'],{'ok':True});self.assertIsNone(evidence['usage'])
  self.assertFalse(evidence['terminalReceived']);self.assertEqual(evidence['streamEvents'],2)
 def test_duplicate_fields_are_not_silently_replaced(self):
  with self.assertRaises(StudyConnectionError):
   collect(sse([chunk('{"ok":true,"ok":false}'),chunk(finish='stop')]),schema=FORMAT['json_schema']['schema'])
 def test_long_spaces_and_repeated_words_inside_teaching_string_are_retained(self):
  schema={'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}
  text='수식과 긴 설명 '+(' '*500)+' 같은 말 '*400;raw=json.dumps({'text':text})
  value=collect(sse([chunk(raw[i:i+17])for i in range(0,len(raw),17)]+[chunk(finish='stop')]),schema=schema)
  self.assertEqual(json.loads(value['choices'][0]['message']['content']),{'text':text})


class ChatRecoveryTests(unittest.TestCase):
 def request(self):
  return urllib.request.Request('https://api.openai.com/v1/chat/completions',data=json.dumps({'response_format':FORMAT}).encode(),
                               headers={'Authorization':'Bearer test-only'},method='POST')
 def terminal(self):
  return {'id':'chatcmpl_fixture','choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],
          'usage':{'prompt_tokens':12,'completion_tokens':7}}
 def test_lost_stream_recovers_the_same_original_without_another_post(self):
  calls=[];updates=[];evidence=[]
  def opener(req,timeout):
   calls.append(req)
   return sse([chunk('{"ok":')],done=False)if req.method=='POST'else io.StringIO(json.dumps(self.terminal()))
  value=request_once(self.request(),open_url=opener,update=lambda **x:updates.append(x),on_partial=evidence.append)
  self.assertEqual(value,self.terminal());self.assertEqual([r.method for r in calls],['POST','GET'])
  self.assertTrue(calls[-1].full_url.endswith('/chatcmpl_fixture'))
  self.assertEqual(evidence[0]['content'],'{"ok":');self.assertTrue(any(x.get('recoveredOriginalResponse')for x in updates))
 def test_optional_overview_without_receipt_does_not_add_recovery_wait(self):
  request=self.request();body=json.loads(request.data);body.update(store=True,metadata={'synesis_request_id':'a'*32})
  request.data=json.dumps(body).encode();calls=[];updates=[]
  def opener(req,timeout):calls.append(req.method);raise OSError('connection ended before headers')
  with self.assertRaises(StudyConnectionError):
   request_once(request,open_url=opener,update=lambda **x:updates.append(x),recover_without_id=False,
                sleep=lambda _:self.fail('optional overview inserted a recovery wait'))
  self.assertEqual(calls,['POST']);self.assertTrue(any(x.get('recoverySkipped')=='optional_overview_without_receipt'for x in updates))
 def test_optional_overview_with_receipt_still_recovers_its_original(self):
  calls=[]
  def opener(req,timeout):
   calls.append(req.method)
   return sse([chunk('{"ok":')],done=False)if req.method=='POST'else io.StringIO(json.dumps(self.terminal()))
  value=request_once(self.request(),open_url=opener,update=lambda **x:None,recover_without_id=False)
  self.assertEqual(value,self.terminal());self.assertEqual(calls,['POST','GET'])
 def test_mismatched_or_pending_recovery_never_becomes_paid_success(self):
  calls=[]
  def opener(req,timeout):
   calls.append(req.method)
   return sse([chunk('{')],done=False)if req.method=='POST'else io.StringIO(json.dumps({**self.terminal(),'id':'chatcmpl_other'}))
  with self.assertRaises(StudyConnectionError):
   request_once(self.request(),open_url=opener,update=lambda **x:None,sleep=lambda _:None)
  self.assertEqual(calls,['POST','GET','GET','GET'])
 def test_lost_before_acknowledgement_has_no_guessed_get_or_resend(self):
  calls=[]
  def opener(req,timeout):calls.append(req.method);raise TimeoutError('silent headers')
  with self.assertRaises(StudyConnectionError):request_once(self.request(),open_url=opener,update=lambda **x:None)
  self.assertEqual(calls,['POST'])
 def tagged_request(self):
  request=self.request();body=json.loads(request.data);body.update(store=True,metadata={'synesis_request_id':'a'*32})
  request.data=json.dumps(body).encode();return request
 def test_exact_request_tag_recovers_without_an_id_or_duplicate_generation(self):
  calls=[];updates=[];terminal={**self.terminal(),'metadata':{'synesis_request_id':'a'*32}}
  def opener(req,timeout):
   calls.append(req)
   if req.method=='POST':raise BrokenPipeError('lost before headers')
   return io.StringIO(json.dumps({'data':[terminal],'has_more':False}))
  value=request_once(self.tagged_request(),open_url=opener,update=lambda **x:updates.append(x))
  self.assertEqual(value,terminal);self.assertEqual([r.method for r in calls],['POST','GET'])
  self.assertIn('metadata%5Bsynesis_request_id%5D='+('a'*32),calls[1].full_url)
  self.assertTrue(any(x.get('chatCompletionId')=='chatcmpl_fixture'for x in updates))
 def test_request_tag_lookup_rejects_missing_wrong_and_ambiguous_metadata(self):
  for returned in [[],[{**self.terminal(),'metadata':{'synesis_request_id':'b'*32}}],
                   [{**self.terminal(),'metadata':{'synesis_request_id':'a'*32}}]*2]:
   with self.subTest(returned=returned):
    calls=[]
    def opener(req,timeout):
     calls.append(req.method)
     if req.method=='POST':raise TimeoutError('lost headers')
     return io.StringIO(json.dumps({'data':returned,'has_more':False}))
    with self.assertRaises(StudyConnectionError):request_once(self.tagged_request(),open_url=opener,update=lambda **x:None,sleep=lambda _:None)
    self.assertEqual(calls,['POST','GET','GET','GET'])
 def test_request_tag_recovery_keeps_actual_length_finish_and_usage(self):
  terminal={**self.terminal(),'metadata':{'synesis_request_id':'a'*32}}
  terminal['choices']=[{'message':{'content':'{"ok":'},'finish_reason':'length'}]
  def opener(req,timeout):
   if req.method=='POST':raise TimeoutError('lost headers')
   return io.StringIO(json.dumps({'data':[terminal],'has_more':False}))
  value=request_once(self.tagged_request(),open_url=opener,update=lambda **x:None)
  self.assertEqual(value['choices'][0]['finish_reason'],'length');self.assertEqual(value['usage'],terminal['usage'])
 def test_output_anomaly_is_not_accepted_through_read_only_recovery(self):
  calls=[]
  def opener(req,timeout):calls.append(req.method);return sse([chunk('{"ok":true}'+(' '*257))])
  with self.assertRaises(StudyConnectionError):request_once(self.request(),open_url=opener,update=lambda **x:None)
  self.assertEqual(calls,['POST'])


class ChatProviderTests(ResponsesProviderTests):
 def provider(self,*,mode=None,retry=False):
  value=super().provider(mode=mode,retry=retry);value.study_recovery_reads=1;return value
 def test_provider_live_study_callback_and_native_usage(self):
  self.opener.side_effect=lambda *a,**k:sse([chunk('{"ok":'),chunk('true}'),chunk(finish='stop'),chunk(usage={'prompt_tokens':10,'completion_tokens':5})])
  seen=[];p=self.provider();self.assertEqual(p.complete(self.payload,**self.options,on_study_delta=seen.append),{'ok':True})
  self.assertEqual(''.join(seen),'{"ok":true}');self.assertEqual(p.ledger['requests'][0]['usage']['completion_tokens'],5)
  self.assertEqual(self.opener.call_args.kwargs['timeout'],45)
 def test_lost_study_stream_keeps_receipt_and_blocks_duplicate_post(self):
  self.opener.side_effect=lambda *a,**k:sse([chunk('{"ok":')],done=False)
  p=self.provider()
  import pdf_ai as ai
  with patch('pdf_study_chat.RECOVERY_READS',1),self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
  e=p.ledger['requests'][0];path=self.paths(e)[0]
  self.assertEqual(json.loads(path.with_suffix('.stream.partial.json').read_text())['id'],'chatcmpl_fixture')
  self.assertEqual(json.loads(path.with_suffix('.receipt.json').read_text())['chatCompletionId'],'chatcmpl_fixture')
  with self.assertRaises(ai.MissingPaidResponseError):p.complete(self.payload,**self.options)
  self.assertEqual([c.args[0].method for c in self.opener.call_args_list],['POST','GET'])
 def test_failed_original_keeps_unknown_usage_without_blocking_a_distinct_sibling(self):
  import pdf_ai as ai
  reads=patch('pdf_study_chat.RECOVERY_READS',1);reads.start();self.addCleanup(reads.stop)
  p=self.provider();self.opener.side_effect=TimeoutError('silent headers')
  with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
  self.assertEqual(p.ledger['requests'][0]['state'],'failed_or_uncertain')
  p.billing.settle.assert_called_once_with(p.ledger['requests'][0]['requestId'],None)
  self.opener.side_effect=lambda *a,**k:sse([chunk('{"ok":true}'),chunk(finish='stop',usage={'prompt_tokens':3,'completion_tokens':4})])
  self.assertEqual(p.complete({**self.payload,'other':'independent'},**self.options),{'ok':True})
  self.assertEqual([call.args[0].method for call in self.opener.call_args_list],['POST','GET','POST'])
 def test_wire_change_reuses_an_existing_paid_answer_without_a_post(self):
  from test_pdf_responses_transport import native
  self.reply(native());old=self.provider(mode='responses')
  self.assertEqual(old.complete(self.payload,**self.options),{'ok':True})
  new=self.provider(mode='chat');self.assertEqual(new.complete(self.payload,**self.options),{'ok':True})
  self.assertEqual(self.opener.call_count,1);self.assertFalse(new.ledger['requests'])
 def test_new_process_retry_flag_cannot_repay_an_unconfirmed_original(self):
  import pdf_ai as ai
  self.opener.side_effect=TimeoutError('Unconfirmed original')
  first=self.provider()
  with self.assertRaises(ai.AiResponseError):first.complete(self.payload,**self.options)
  before=self.opener.call_count
  restarted=self.provider(retry=True)
  with self.assertRaises(ai.MissingPaidResponseError):restarted.complete(self.payload,**self.options)
  self.assertEqual(self.opener.call_count,before);self.assertEqual(restarted.ledger['requests'],[])
 def test_wire_change_does_not_bypass_an_uncertain_paid_attempt(self):
  import pdf_ai as ai
  old=self.provider(mode='responses');self.opener.side_effect=TimeoutError('silent response')
  with self.assertRaises(ai.AiResponseError):old.complete(self.payload,**self.options)
  new=self.provider(mode='chat')
  with self.assertRaises(ai.MissingPaidResponseError):new.complete(self.payload,**self.options)
  self.assertEqual(self.opener.call_count,1);self.assertFalse(new.ledger['requests'])
 def test_title_only_roadmap_streams_without_changing_prompt_or_adding_teaching(self):
  self.opener.side_effect=lambda *a,**k:sse([chunk('{"ok":true}'),chunk(finish='stop',usage={'prompt_tokens':3,'completion_tokens':4})])
  p=self.provider();p.context={'kind':'summary_reduce','strategy':'outline'}
  value=p.complete({'task':'lecture_flow_from_headings','topics':[]},**self.options)
  self.assertEqual(value,{'ok':True});body=json.loads(self.opener.call_args.args[0].data)
  self.assertEqual(body['messages'][0]['content'],[{'type':'text','text':self.options['system_prompt'],'prompt_cache_breakpoint':{'mode':'explicit'}}])
  self.assertTrue(body['stream']);self.assertEqual(p.ledger['requests'][0]['timeoutSeconds'],45)
 def test_early_failure_does_not_poison_other_requests_still_waiting_for_first_text(self):
  import pdf_ai as ai
  reads=patch('pdf_study_chat.RECOVERY_READS',1);reads.start();self.addCleanup(reads.stop)
  waiting=threading.Event();release=threading.Event();p=self.provider()
  def opener(req,timeout):
   body=json.loads(req.data);payload=json.loads(body['messages'][1]['content'])
   if payload.get('slot')=='slow':
    waiting.set()
    if not release.wait(3):raise AssertionError('Sibling did not release')
   if payload.get('slot')=='fail':raise TimeoutError('only this connection failed')
   return sse([chunk('{"ok":true}'),chunk(finish='stop',usage={'prompt_tokens':3,'completion_tokens':4})])
  self.opener.side_effect=opener
  with ThreadPoolExecutor(max_workers=2)as pool:
   slow=pool.submit(p.complete,{**self.payload,'slot':'slow'},**self.options)
   self.assertTrue(waiting.wait(3))
   try:
    with self.assertRaises(ai.AiResponseError):p.complete({**self.payload,'slot':'fail'},**self.options)
    self.assertFalse(p._study_connection_failed.is_set())
   finally:release.set()
   self.assertEqual(slow.result(),{'ok':True})
  self.assertEqual(p._study_connections,0)
  self.assertEqual(p.complete({**self.payload,'slot':'third'},**self.options),{'ok':True})
 def test_proven_local_upload_queue_failure_releases_hold_and_allows_later_send(self):
  import pdf_ai as ai
  from pdf_study_http import RequestNotSentError
  p=self.provider();self.opener.side_effect=RequestNotSentError('local_connection_queue')
  with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
  entry=p.ledger['requests'][0]
  self.assertEqual(entry['state'],'not_sent');self.assertEqual(entry['estimatedUsd'],0)
  self.assertNotIn('sentAtMs',entry);p.billing.settle.assert_called_once_with(entry['requestId'],0)
  self.opener.side_effect=lambda *a,**k:sse([chunk('{"ok":true}'),chunk(finish='stop',usage={'prompt_tokens':3,'completion_tokens':4})])
  self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})

if __name__=='__main__':unittest.main()
