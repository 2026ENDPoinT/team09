import copy
import json
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import pdf_newest_k1_1_1 as engine
from pdf_json_wire import label_images
from pdf_newest_k1_1_1_guard import crossed_evidence, ensure_owned, SourceOwnershipError
from pdf_pipeline import write_json
from test_pdf_newest_k1_1_1 import block, response

A=['The alpha source uniquely explains one structure.', 'A separate alpha clause describes its operation.']
B=['The beta source uniquely explains another structure.', 'A separate beta clause describes its conditions.']
def request(text, name):return {'job':{'id':name,'blocks':[{'text':' '.join(text)}]}}
def quoted(quotes):
 r=response('a');r['concepts'][0]['sourceSetup']['sourceQuotes']=quotes;return r

class OwnershipTests(unittest.TestCase):
 def test_crossed_literals_require_two_independent_rival_only_quotes(self):
  with self.assertRaises(SourceOwnershipError):ensure_owned(quoted(B),request(A,'a'),[request(B,'b')])
  for quotes,own in [(B[:1],A),(B+B[:1],A+B),(B[:1]*2,A),([],A)]:
   self.assertFalse(crossed_evidence(quoted(quotes),request(own,'a'),[request(B,'b')]))
  self.assertFalse(crossed_evidence(quoted(B),request([],'a'),[request(B,'b')]))

 def test_envelopes_preserve_images_and_payload_for_both_api_routes(self):
  for route,image_kind,text_kind in [('messages','image_url','text'),('input','input_image','input_text')]:
   for image_count in (0,2):
    units={name:{'text':name+' 원문','crops':[{'page':i+1,'blockIds':[name]}]}for i,name in enumerate(('u0','u1'))}
    payload={'task':'region_teaching_batch','units':units,'imageOrder':[{'unit':name,'cropIndex':0}for name in list(units)[:image_count]],'unitEnvelopeVersion':'k1.1.1-v1'}
    images=[{'type':image_kind,'image_url':{'url':'unchanged-'+str(i)}}for i in range(image_count)]
    body={route:[{}, {'content':[{'type':text_kind,'text':json.dumps(payload)}]+images}]}
    before=copy.deepcopy(body);actual,count=label_images(body,'region_teaching_batch')
    self.assertEqual(body,before);self.assertEqual(count,image_count)
    contents=actual[route][1]['content'];text=[v.get('text','')for v in contents]
    a=next(i for i,v in enumerate(text)if v.startswith('BEGIN UNIT u0'))
    b=next(i for i,v in enumerate(text)if v.startswith('BEGIN UNIT u1'))
    self.assertLess(a,b)
    self.assertEqual(json.loads(text[a].split('\n',1)[1])['source'],units['u0'])
    self.assertEqual([v for v in contents if v['type']==image_kind],images)
    if image_count:self.assertLess(contents.index(images[0]),b)
    payload.pop('unitEnvelopeVersion');body[route][1]['content'][0]['text']=json.dumps(payload)
    old,_=label_images(body,'region_teaching_batch')
    self.assertEqual(json.loads(old[route][1]['content'][0]['text']),payload)

 def test_pair_retries_only_rejected_unit_and_reuses_valid_result(self):
  self.run_lifecycle(False)

 def test_failed_single_retry_is_bounded_and_wrong_prose_never_published(self):
  self.run_lifecycle(True)

 def run_lifecycle(self,bad_retry):
  blocks=[{**block(i),'text':' '.join([f'Unique source {i} has its own complete definition.',f'Independent source {i} explains an exclusive example.'])}for i in range(8)]
  groups=[{'title':f'주제 {i}','description':'정의와 예시','blocks':[b]}for i,b in enumerate(blocks)]
  doc={'documentId':'ownership-test','fingerprint':'ownership-test','pages':[{'number':b['page'],'label':str(b['page']),'nativeText':b['text']}for b in blocks]}
  class Provider:
   model='gpt-6-luna';billing=None;context={};ledger={'requests':[]};transport=object()
   def complete(self,payload,**kw):return {'body':'정의와 예시를 살펴봐요.','topicIds':['k1']}
  calls=[];events=[];victim=[];rival=[]
  def complete(provider,payload,**kw):
   calls.append(copy.deepcopy(payload))
   if payload['task']=='region_teaching_batch':
    result={name:response(unit['blocks'][0]['id'])for name,unit in payload['units'].items()}
    if not victim:
     names=list(result);u=payload['units'][names[0]];other=payload['units'][names[1]]
     victim.append(u['blocks'][0]['id']);rival.extend(other['blocks'][0]['text'].split('. ')[:2])
     result[names[0]]['concepts'][0]['sourceSetup']['sourceQuotes']=rival
     result[names[0]]['concepts'][0]['segments'][0]['text']='CROSS_OWNERSHIP_REJECT_ME'
    return result
   raw=response(payload['blocks'][0]['id'])
   if victim and payload['blocks'][0]['id']==victim[0] and bad_retry:
    raw['concepts'][0]['sourceSetup']['sourceQuotes']=rival
    raw['concepts'][0]['segments'][0]['text']='CROSS_OWNERSHIP_REJECT_ME'
   if kw.get('on_study_delta'):kw['on_study_delta'](json.dumps(raw))
   return raw
  with tempfile.TemporaryDirectory()as tmp,ExitStack()as stack:
   stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('offline')))
   for name,value in {'SOURCE_ID_ALIASES':False,'TRANSPORT_BATCH_ALIASES':False,'TRANSPORT_BALANCED':False}.items():stack.enter_context(patch.object(engine,name,value))
   folder=Path(tmp);provider=Provider();root=engine.root_path(folder,doc,'newest-k1-1-1',provider.model,'document',0)
   write_json(root/'plan.json',engine.plan_record(groups,[],provider.model,[],blocks=blocks))
   stack.enter_context(patch.object(engine,'extract_layout',return_value=copy.deepcopy(blocks)))
   stack.enter_context(patch.object(engine,'render_crops',return_value=([],[])))
   stack.enter_context(patch.object(engine,'emit',side_effect=lambda kind,**kw:events.append((kind,kw))))
   stack.enter_context(patch('pdf_ai.complete_study_delivery',side_effect=complete))
   stack.enter_context(patch('pdf_ai.run_usage',return_value={}))
   result=engine.generate(folder,doc,provider)
   self.assertTrue(victim)
   retries=[p for p in calls if p['task']=='region_teaching' and p['blocks'][0]['id']==victim[0]]
   self.assertEqual(len(retries),1)
   self.assertNotIn('CROSS_OWNERSHIP_REJECT_ME',json.dumps(events))
   self.assertEqual(result['processingComplete'],not bad_retry,result.get('failedUnits'))
   if not bad_retry:
    count=len(calls);self.assertTrue(engine.generate(folder,doc,provider)['cacheHit']);self.assertEqual(len(calls),count)

if __name__=='__main__':unittest.main()
