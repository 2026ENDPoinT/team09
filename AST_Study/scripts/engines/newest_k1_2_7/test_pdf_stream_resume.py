"""A broken socket retrieves the original response before trying a new stream."""
import io,json,unittest,urllib.request,urllib.error
from pdf_study_connection import request_once,StudyConnectionError
from test_pdf_study_connection import sse
from test_pdf_responses_transport import native,FORMAT

def event(seq,kind,**fields):return {'sequence_number':seq,'type':kind,**fields}
def create():return event(0,'response.created',response={'id':'resp_fixture','status':'in_progress'})
def request():
 return urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps({'background':True,'stream':True,'text':{'format':FORMAT['json_schema']}}).encode(),headers={'Authorization':'Bearer fixture'},method='POST')

class ResumeTests(unittest.TestCase):
 def test_status_recovery_preserves_prefix_snapshot_and_genuine_terminal_usage(self):
  calls=[];seen=[];updates=[];snapshots=[]
  def opener(req,timeout):
   calls.append(req)
   if len(calls)==1:return sse([create(),event(1,'response.output_text.delta',item_id='answer',delta='{"ok":')])
   return io.StringIO(json.dumps(native()))
  result=request_once(request(),open_url=opener,update=lambda **x:updates.append(x),on_delta=seen.append,on_snapshot=snapshots.append,resume_stream=True)
  self.assertEqual(result,native());self.assertEqual(seen,['{"ok":'])
  self.assertEqual([r.method for r in calls],['POST','GET']);self.assertTrue(calls[1].full_url.endswith('/resp_fixture'))
  self.assertTrue(any(x.get('streamReconnects')==0 for x in updates));self.assertTrue(snapshots)
 def test_broken_resume_endpoint_is_bypassed_without_resubmitting(self):
  calls=[]
  def opener(req,timeout):
   calls.append(req)
   if req.method=='POST':return sse([create()])
   if 'stream=true'in req.full_url:raise TimeoutError('connection interruption')
   value=io.StringIO(json.dumps(native()));value.headers={};return value
  result=request_once(request(),open_url=opener,update=lambda **x:None,resume_stream=True,sleep=lambda _:None)
  self.assertEqual(result,native());self.assertEqual([r.method for r in calls],['POST','GET'])
 def test_wrong_id_from_status_read_is_never_accepted(self):
  calls=[]
  def opener(req,timeout):
   calls.append(req)
   if req.method=='POST':return sse([create()])
   wrong={**native(),'id':'resp_other'}
   if 'stream=true'in req.full_url:return sse([event(2,'response.completed',response=wrong)])
   return io.StringIO(json.dumps(wrong))
  with self.assertRaises(StudyConnectionError):request_once(request(),open_url=opener,update=lambda **x:None,resume_stream=True,sleep=lambda _:None)
  self.assertEqual(sum(r.method=='POST'for r in calls),1);self.assertLessEqual(len(calls),6)
 def test_expired_stream_cursor_is_irrelevant_to_status_recovery(self):
  calls=[]
  def opener(req,timeout):
   calls.append(req)
   if req.method=='POST':return sse([create()])
   if 'stream=true'in req.full_url:
    raise urllib.error.HTTPError(req.full_url,400,'Stream cursor expired',{},io.BytesIO(b'{}'))
   return io.StringIO(json.dumps(native()))
  result=request_once(request(),open_url=opener,update=lambda **x:None,resume_stream=True,sleep=lambda _:None)
  self.assertEqual(result,native());self.assertEqual([r.method for r in calls],['POST','GET'])
 def test_explicit_creation_http_error_never_becomes_another_request(self):
  calls=[]
  def opener(req,timeout):
   calls.append(req)
   raise urllib.error.HTTPError(req.full_url,400,'Invalid request',{},io.BytesIO(b'{}'))
  with self.assertRaises(urllib.error.HTTPError):request_once(request(),open_url=opener,update=lambda **x:None,resume_stream=True)
  self.assertEqual(len(calls),1)

if __name__=='__main__':unittest.main()
