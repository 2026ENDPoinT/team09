"""Generation-control/billing regression: one generation, explicit cancel, exact schema frame."""
import copy,io,json,unittest
import pdf_ai as ai
from test_pdf_responses_provider import ResponsesProviderTests
from test_pdf_responses_transport import native
from test_pdf_study_connection import sse,created


class OutputGuardTests(ResponsesProviderTests):
 def fixture(self,delta):
  calls=[];value=native();value['status']='cancelled';value['output'][1]['status']='incomplete'
  def opener(req,timeout):
   calls.append((req.method,req.full_url))
   if req.full_url.endswith('/cancel')or req.method=='GET':return io.StringIO(json.dumps(value))
   return sse([created(),{'type':'response.output_text.delta','item_id':'msg_one','delta':delta}])
  self.opener.side_effect=opener
  return calls,value
 def test_runaway_suffix_is_cancelled_and_complete_json_not_api_status_is_recovered(self):
  p=self.provider(mode='responses');calls,native_value=self.fixture('{"ok":true}'+(' \n'*150))
  self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})
  entry=p.ledger['requests'][0]
  self.assertEqual(entry['state'],'settled');self.assertTrue(entry['clientCompletedJson'])
  self.assertEqual([m for m,u in calls],['POST','POST','GET'])
  self.assertTrue(calls[1][1].endswith('/cancel'))
  self.assertEqual(json.loads(self.paths(entry)[2].read_text()),native_value)
  self.assertEqual(json.loads(self.paths(entry)[0].with_suffix('.client-completed.json').read_text())['apiFinishStatus'],'cancelled')
  self.assert_settled_native(p,native_value)
  other=self.provider(mode='responses');self.assertEqual(other.complete(self.payload,**self.options),{'ok':True})
  self.assertEqual(len(calls),3)
 def test_stale_read_cannot_undo_confirmed_server_cancellation(self):
  import pdf_study_connection as net
  from unittest.mock import patch
  p=self.provider(mode='responses');calls=[];value=native();value['status']='cancelled';value.pop('usage',None)
  def opener(req,timeout):
   calls.append(req)
   if req.full_url.endswith('/cancel'):return io.StringIO(json.dumps(value))
   if req.method=='GET':return io.StringIO(json.dumps({'id':value['id'],'status':'in_progress'}))
   return sse([created(),{'type':'response.output_text.delta','item_id':'msg_one','delta':'{"ok":true}'+(' '*300)}])
  self.opener.side_effect=opener
  with patch.object(net.time,'sleep',return_value=None):
   response=net.request_once(__import__('urllib.request',fromlist=['Request']).Request(
    'https://api.openai.com/v1/responses',data=json.dumps({'background':True,'text':{'format':{'schema':{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}}}}).encode(),method='POST'),
    open_url=opener,update=lambda **x:None,sleep=lambda _:None)
  self.assertEqual(response.native['status'],'cancelled');self.assertEqual(response.value,{'ok':True})
  self.assertEqual([c.method for c in calls],['POST','POST','GET','GET','GET'])
  self.assertTrue(all(c.get_header('Cache-control')=='no-cache' for c in calls[2:]))
 def test_incomplete_json_padding_never_turns_into_success_or_another_paid_generation(self):
  p=self.provider(mode='responses');calls,value=self.fixture('{"ok":'+(' '*300))
  with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
  self.assertEqual([m for m,u in calls],['POST','POST','GET'])
  self.assertFalse(p.ledger['requests'][0].get('clientCompletedJson',False));self.assertEqual(p.ledger['requests'][0]['state'],'settled')
 def test_missing_required_fields_are_cancelled_without_salvage(self):
  p=self.provider(mode='responses');calls,value=self.fixture('{}'+(' '*300))
  with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
  self.assertFalse(p.ledger['requests'][0].get('clientCompletedJson',False));self.assertTrue(calls[1][1].endswith('/cancel'))
 def test_commentary_is_not_promoted_to_final_json(self):
  p=self.provider(mode='responses');value=native();calls=[]
  def opener(req,timeout):
   calls.append(req)
   return sse([created(),{'type':'response.output_item.added','item':{'id':'comment','phase':'commentary'}},
    {'type':'response.output_text.delta','item_id':'comment','delta':'{"ok":false} not final'},
    {'type':'response.output_item.added','item':{'id':'final','phase':'final_answer'}},
    {'type':'response.output_text.delta','item_id':'final','delta':'{"ok":true}'},
    {'type':'response.completed','response':value}])
  self.opener.side_effect=opener
  self.assertEqual(p.complete(self.payload,**self.options),{'ok':True});self.assertEqual(len(calls),1)
 def test_commentary_padding_is_cancelled_without_promoting_commentary(self):
  p=self.provider(mode='responses');value=native();value['status']='cancelled';calls=[]
  def opener(req,timeout):
   calls.append(req)
   if req.full_url.endswith('/cancel')or req.method=='GET':return io.StringIO(json.dumps(value))
   return sse([created(),{'type':'response.output_item.added','item':{'id':'comment','phase':'commentary'}},
    {'type':'response.output_text.delta','item_id':'comment','delta':'{"ok":true}'+(' '*300)}])
  self.opener.side_effect=opener
  with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
  self.assertEqual([c.method for c in calls],['POST','POST','GET'])
  self.assertFalse(p.ledger['requests'][0].get('clientCompletedJson',False))
 def test_long_spaces_inside_commentary_string_do_not_cancel(self):
  p=self.provider(mode='responses');value=native();calls=[]
  def opener(req,timeout):
   calls.append(req)
   return sse([created(),{'type':'response.output_item.added','item':{'id':'comment','phase':'commentary'}},
    {'type':'response.output_text.delta','item_id':'comment','delta':'{"note":"'+(' '*1000)+'"}'},
    {'type':'response.completed','response':value}])
  self.opener.side_effect=opener
  self.assertEqual(p.complete(self.payload,**self.options),{'ok':True});self.assertEqual(len(calls),1)
 def test_normal_result_keeps_source_prompt_schema_and_output_ceiling(self):
  p=self.provider(mode='responses');self.reply(native());p.complete(self.payload,**self.options)
  body=json.loads(self.opener.call_args.args[0].data)
  self.assertTrue(body['background']);self.assertTrue(body['stream'])
  self.assertEqual(body['input'][0]['content'][0]['text'],self.options['system_prompt'])
  self.assertEqual(body['max_output_tokens'],self.options['max_output'])
  self.assertEqual(body['text']['format']['schema'],self.options['response_format']['json_schema']['schema'])

if __name__=='__main__':unittest.main()
