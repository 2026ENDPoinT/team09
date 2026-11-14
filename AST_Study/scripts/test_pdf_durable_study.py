"""Full synthetic new-upload workflow; no credentials or network."""
import threading,unittest
from unittest.mock import patch
import pdf_new_concept_ver99_study as study
import test_pdf_speed_pipeline as fixture

class DurableStudyTests(unittest.TestCase):
 def test_every_unit_is_durable_while_opening_units_keep_source_priority(self):
  f=fixture.CropPipelineTests('test_first_request_starts_before_all_local_crops_finish');f.setUp()
  self.addCleanup(f.doCleanups);self.addCleanup(f.tearDown);f.set_unit_count(20)
  class Provider(fixture.FakeProvider):
   def __init__(self,complete):self.local=threading.local();super().__init__(complete)
   @property
   def context(self):return getattr(self.local,'context',{})
   @context.setter
   def context(self,value):self.local.context=value
  modes={};order=[];lock=threading.Lock()
  def complete(payload,**kwargs):
   source=payload['blocks'][0]['id']
   with lock:modes[source]=p.context.get('studyDurable',False);order.append(source)
   return f.reply(source)
  p=Provider(complete)
  with patch.object(study,'DURABLE_STUDY_BODY',True):
   # These are native-text-only sources. No image means no image ownership row.
   result,_=f.run_pipeline(lambda _:None,provider=p,worker_limit=14,crop_result=lambda blocks:([],[]))
  self.assertTrue(result['processingComplete']);self.assertEqual(len(modes),20)
  self.assertEqual(set(order[:2]),{'source0','source1'})
  self.assertEqual(sum(modes.values()),20)

if __name__=='__main__':unittest.main()

# These fixtures exercise the same provider used by the whole-upload pipeline.
import io,json
import pdf_ai as ai
from test_pdf_responses_provider import ResponsesProviderTests
from test_pdf_study_connection import sse,created
from test_pdf_study_chat import sse as chat_sse,chunk

class DurableProviderTests(ResponsesProviderTests):
 def install_commentary(self,*,usage=True):
  cancelled={'id':'resp_fixture','status':'cancelled','output':[],
             'usage':{'input_tokens':20,'output_tokens':1,'total_tokens':21}if usage else None}
  def open_reply(req,timeout):
   if req.full_url.endswith('/cancel')or req.method=='GET':
    r=io.StringIO(json.dumps(cancelled));r.headers={};return r
   if req.full_url.endswith('/responses'):
    return sse([created(),{'type':'response.output_item.added','item':{'id':'commentary','phase':'commentary','type':'message'}}])
   return chat_sse([chunk('{"ok":true}'),chunk(finish='stop',usage={'prompt_tokens':10,'completion_tokens':5})])
  self.opener.side_effect=open_reply
 def test_confirmed_commentary_is_stopped_then_exact_input_uses_one_alternate_route(self):
  self.install_commentary();p=self.provider(mode='chat');p.context={'kind':'region_study','studyDurable':True}
  with self.assertRaises(ai.StudyDeliveryFallback)as error:p.complete(self.payload,**self.options)
  old=p.ledger['requests'][0];self.assertTrue(old['safeForegroundFallback']);self.assertEqual(old['state'],'settled')
  p.context={'kind':'region_study','studyDurable':False}
  self.assertEqual(p.complete(self.payload,**self.options,study_recovery=error.exception.request_id),{'ok':True})
  self.assertTrue(old['foregroundRecoveryConsumed']);self.assertEqual(len(p.ledger['requests']),2)
  self.assertEqual([call.args[0].method for call in self.opener.call_args_list],['POST','POST','GET','POST'])
  body=json.loads(self.opener.call_args.args[0].data);self.assertEqual(json.loads(body['messages'][1]['content']),self.payload)
  # The successful alternate is reusable; another caller never pays again.
  self.assertEqual(p.complete(self.payload,**self.options),{'ok':True});self.assertEqual(self.opener.call_count,4)
 def test_unknown_original_charge_remains_reserved_and_same_budget_can_stop_fallback(self):
  self.install_commentary(usage=False);p=self.provider(mode='chat');p.context={'kind':'region_study','studyDurable':True}
  with patch('pdf_study_connection.RECOVERY_READS',1),self.assertRaises(ai.StudyDeliveryFallback)as error:
   p.complete(self.payload,**self.options)
  old=p.ledger['requests'][0];self.assertEqual(old['state'],'usage_unknown');self.assertEqual(p.spent,old['reservedUsd'])
  p.max_usd=p.spent;p.context={'kind':'region_study'};before=self.opener.call_count
  with self.assertRaises(ai.BudgetExceeded):p.complete(self.payload,**self.options,study_recovery=error.exception.request_id)
  self.assertEqual(self.opener.call_count,before);self.assertFalse(old.get('foregroundRecoveryConsumed',False))
 def test_request_with_no_confirmed_server_termination_cannot_authorize_another_post(self):
  p=self.provider(mode='chat')
  with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options,study_recovery='a'*32)
  self.opener.assert_not_called();self.assertEqual(p.ledger['requests'],[])
 def test_user_cancel_stops_acknowledged_server_job_and_settles_genuine_usage(self):
  cancelled={'id':'resp_fixture','status':'cancelled','output':[],
             'usage':{'input_tokens':20,'output_tokens':1,'total_tokens':21}}
  def open_reply(req,timeout):
   if req.full_url.endswith('/cancel')or req.method=='GET':
    r=io.StringIO(json.dumps(cancelled));r.headers={};return r
   return sse([created()])
  self.opener.side_effect=open_reply;p=self.provider(mode='responses')
  def cancel(folder):
   if any(e.get('responseId')for e in p.ledger['requests']):raise InterruptedError('User cancelled')
  with patch.object(ai,'check_cancel',cancel),self.assertRaises(InterruptedError):p.complete(self.payload,**self.options)
  self.assertEqual(p.ledger['requests'][0]['state'],'settled')
  self.assertEqual(p.ledger['requests'][0]['usage']['completion_tokens'],1)
  self.assertEqual([c.args[0].method for c in self.opener.call_args_list],['POST','POST','GET'])
