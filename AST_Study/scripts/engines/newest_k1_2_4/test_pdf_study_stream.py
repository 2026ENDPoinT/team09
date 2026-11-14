"""Offline streaming previews: learner field isolation, ordering and paid-response invariants."""
import copy
import io
import json
import threading
import unittest
import urllib.request
from unittest.mock import patch
from pdf_study_stream import PreviewJson,StudyPreview,PreviewPublication
import pdf_study_connection as connection
from test_pdf_study_connection import created,sse
from test_pdf_responses_transport import native
from test_pdf_responses_provider import ResponsesProviderTests


def teaching(title='원리',text='정의와 조건이에요.'):
 return {'concepts':[{'title':title,'sourceSetup':{'observedRelations':['PRIVATE_RELATION'],
  'boundaryChecks':['PRIVATE_CHECK'],'interpretation':'PRIVATE_SETUP'},'segments':[
  {'kind':'definition','text':text,'blockIds':['PRIVATE_ID']},
  {'kind':'explanation','text':'둘째 설명이에요.','blockIds':['PRIVATE_ID']},
  {'kind':'easyExplanation','text':'PRIVATE_EASY','blockIds':['PRIVATE_ID']},
  {'kind':'uncertain','text':'PRIVATE_UNCERTAIN','blockIds':['PRIVATE_ID']}],
  'standardKnowledgeUsed':False}],'tables':[],'sequences':[],'excludedBlocks':[],
  'uncertainBlocks':[],'metadata':{'concepts':[{'title':'PRIVATE_NESTED','segments':[{'kind':'definition','text':'PRIVATE_METADATA'}]}]}}


class PreviewParserTests(unittest.TestCase):
 def test_worked_method_is_previewed_without_private_fields_or_overwriting_main(self):
  value=teaching('다음 이론','MAIN')
  method,=teaching('지수 치환','METHOD')['concepts']
  method['principle']={'text':method['segments'].pop(0)['text'],'blockIds':['PRIVATE_ID']}
  value={'workedMethods':[method],**value}
  got=[];preview=StudyPreview([((),0)],lambda i,body:got.append(body),interval=0)
  for char in json.dumps(value,ensure_ascii=False):preview.feed(char)
  self.assertIn('### 지수 치환\n\nMETHOD',got[-1])
  self.assertIn('### 다음 이론\n\nMAIN',got[-1])
  self.assertNotIn('PRIVATE',got[-1])
  self.assertTrue(any('METHOD' in body and 'MAIN' not in body for body in got))

 def test_equation_preview_waits_for_complete_tex(self):
  got=[];preview=StudyPreview([((),0)],lambda i,body:got.append(body),interval=0)
  preview.feed(r'{"workedMethods":[],"concepts":[{"title":"공식","segments":[{"kind":"equation","text":"x=')
  self.assertEqual(got,[])
  preview.feed('1"}]}]}')
  self.assertIn('$$x=1$$',got[-1])

 def test_preview_never_publishes_segments_tagged_as_examples(self):
  got=[];preview=StudyPreview([((),0)],lambda i,body:got.append(body),interval=0)
  value=teaching()
  value['concepts'][0]['segments'].append({'contentRole':'instance','kind':'explanation','text':'PRIVATE_ANSWER'})
  for char in json.dumps(value,ensure_ascii=False):preview.feed(char)
  self.assertTrue(got)
  self.assertTrue(all('PRIVATE' not in body for body in got))

 def test_alternate_delivery_resets_partial_json_without_mixing_or_duplication(self):
  got=[];p=StudyPreview([((),0)],lambda i,b:got.append(b),interval=0)
  p.feed('{"concepts":[{"title":"중단된 제목","segments":[{"kind":"definition","text":"OLD')
  self.assertIn('OLD',got[-1]);p.reset()
  for char in json.dumps(teaching('새 제목','NEW'),ensure_ascii=False):p.feed(char)
  self.assertFalse(p.parser.invalid);self.assertIn('NEW',got[-1])
  self.assertNotIn('OLD',got[-1]);self.assertNotIn('중단된 제목',got[-1])

 def test_each_character_decodes_math_split_unicode_pairs_and_only_learner_text(self):
  updates=[];decoder=StudyPreview([((),0)],lambda i,body:updates.append((i,body)),interval=0)
  text='각막 👁과 \\(x^2=1\\), 따옴표 "조건"과 줄바꿈\n둘째 줄이에요.'
  wire=json.dumps(teaching(text=text),ensure_ascii=True)
  for char in wire:decoder.feed(char)
  self.assertFalse(decoder.parser.invalid);self.assertTrue(updates)
  self.assertIn(text,updates[-1][1]);self.assertNotIn('PRIVATE',updates[-1][1])
  for _,body in updates:body.encode('utf-8')
  self.assertTrue(any('각막' in body and '둘째 설명'not in body for _,body in updates[:-1]))
 def test_unescaped_korean_and_all_delimiters_inside_string_are_not_json_structure(self):
  updates=[];decoder=StudyPreview([((),0)],lambda i,b:updates.append(b),interval=0)
  wire=json.dumps(teaching(text='한글 {"concepts":[]} > [1, 2] \\ 경로'),ensure_ascii=False)
  for start in range(0,len(wire),7):decoder.feed(wire[start:start+7])
  self.assertIn('한글 {"concepts":[]} > [1, 2] \\ 경로',updates[-1])
 def test_batch_unit_names_cannot_cross_publish_or_read_metadata(self):
  updates=[];decoder=StudyPreview([(('u0',),8),(('u1',),3)],lambda i,b:updates.append((i,b)),interval=0)
  value={'u0':teaching('첫 단위','FIRST'),'u1':teaching('둘째 단위','SECOND'),'u2':teaching('외부','PRIVATE_THIRD')}
  wire=json.dumps(value,ensure_ascii=False)
  for start in range(0,len(wire),13):decoder.feed(wire[start:start+13])
  first=[b for i,b in updates if i==8][-1];second=[b for i,b in updates if i==3][-1]
  self.assertIn('FIRST',first);self.assertNotIn('SECOND',first);self.assertIn('SECOND',second);self.assertNotIn('FIRST',second)
  self.assertNotIn('PRIVATE',first+second)
 def test_text_before_kind_waits_for_complete_supported_kind(self):
  decoder=StudyPreview([((),0)],lambda i,b:self.values.append(b),interval=0);self.values=[]
  decoder.feed('{"concepts":[{"title":"원리","segments":[{"text":"SAFE","kind":"defin')
  self.assertEqual(self.values,[])
  decoder.feed('ition"}]}]}');self.assertIn('SAFE',self.values[-1])
 def test_duplicate_keys_and_incomplete_unicode_never_emit_broken_utf8(self):
  values=[];p=StudyPreview([((),0)],lambda i,b:values.append(b),interval=0)
  p.feed('{"concepts":[{"title":"a","segments":[{"kind":"definition","text":"앞\\uD83D')
  self.assertEqual(values[-1],'### a\n\n앞')
  p.feed('\\uDC41"}],"title":"second"}]}');self.assertTrue(p.parser.invalid)
  for value in values:value.encode('utf-8')
 def test_easy_explanation_only_and_source_setup_only_never_preview(self):
  value=teaching();value['concepts'][0]['segments']=value['concepts'][0]['segments'][2:]
  got=[];p=StudyPreview([((),0)],lambda *x:got.append(x));p.feed(json.dumps(value));self.assertEqual(got,[])


class PublicationTests(unittest.TestCase):
 def setUp(self):
  self.events=[];self.now=[1.0]
  self.jobs=[{'title':'주제 '+str(i),'blocks':[{'page':i+1}]}for i in range(5)]
  self.pub=PreviewPublication(self.jobs,[0,1],set(),scope='document',page=0,strategy='new-concept-v99',
   emit=lambda kind,**v:self.events.append({'type':kind,**v}),clock=lambda:self.now[0])
 def test_opening_previews_release_without_serializing_generation(self):
  self.pub.update(4,'tail');self.pub.update(1,'second');self.assertEqual(self.events,[])
  self.pub.update(0,'first')
  self.assertEqual([x['unit']for x in self.events],[1,2,5]);self.assertTrue(all(x['preview']for x in self.events))
  self.assertEqual(self.events[0]['summary']['visualPages'],[1])
 def test_100ms_cadence_first_text_immediate_and_final_text_before_settlement(self):
  self.pub.update(0,'a');self.pub.update(0,'ab');self.pub.update(0,'abc')
  self.assertEqual(len(self.events),1)
  self.pub.settle(0,True)
  self.assertEqual([x['summary']['body']for x in self.events],['a','abc'])
  self.pub.update(0,'late');self.assertEqual(len(self.events),2)
  self.assertEqual([x['sequence']for x in self.events],[1,2])
 def test_failed_opening_clears_only_visible_preview_and_releases_following_units(self):
  self.pub.update(0,'first');self.pub.update(1,'second');self.pub.update(2,'tail')
  self.pub.settle(0,False)
  self.assertTrue(self.events[-1]['discard']);self.assertEqual(self.events[-1]['unit'],1)
  self.pub.update(0,'late bad preview');self.assertTrue(self.events[-1]['discard'])
 def test_failure_without_preview_still_unlocks_second(self):
  self.pub.update(1,'second');self.pub.settle(0,False)
  self.assertEqual([x['unit']for x in self.events],[2])
 def test_cached_or_skipped_opening_units_do_not_deadlock_streaming_tail(self):
  publication=PreviewPublication(self.jobs,[0,1],{0,1},scope='document',page=0,strategy='new-concept-v99',
   emit=lambda kind,**v:self.events.append(v))
  publication.update(4,'tail after cached opening')
  self.assertEqual(self.events[0]['unit'],5)
 def test_concurrent_unit_snapshots_remain_distinct_monotone_and_valid_json(self):
  self.pub.settle(0,True);self.pub.settle(1,True)
  def worker(index):
   for n in range(10):self.pub.update(index,'unit '+str(index)+' / '+str(n))
   self.pub.settle(index,True)
  threads=[threading.Thread(target=worker,args=(i,))for i in (2,3,4)]
  for thread in threads:thread.start()
  for thread in threads:thread.join()
  for i in (2,3,4):
   events=[e for e in self.events if e['unit']==i+1]
   self.assertEqual([e['sequence']for e in events],list(range(1,len(events)+1)))
   self.assertTrue(all('unit '+str(i) in e['summary']['body']for e in events))
  json.dumps(self.events,ensure_ascii=False).encode('utf-8')


class ConnectionPreviewTests(unittest.TestCase):
 def test_only_final_text_reaches_callback_before_terminal_native_object(self):
  value=native();events=[created(),{'type':'response.output_item.added','item':{'id':'comment','phase':'commentary'}},
   {'type':'response.output_text.delta','item_id':'comment','delta':'PRIVATE_COMMENTARY'},
   {'type':'response.output_item.added','item':{'id':'final','phase':'final_answer'}},
   {'type':'response.output_text.delta','item_id':'final','delta':'{"ok":'},
   {'type':'response.output_text.delta','item_id':'final','delta':'true}'},
   {'type':'response.completed','response':value}]
  received=[];native_received=[]
  req=urllib.request.Request('https://api.openai.com/v1/responses',data=b'{"background":true,"text":{"format":{"schema":{"type":"object"}}}}',method='POST')
  got=connection.request_once(req,open_url=lambda *a,**k:sse(events),update=lambda **v:native_received.append(v.get('networkPhase')),
   on_delta=lambda v:received.append((v,list(native_received))))
  self.assertEqual([x[0]for x in received],['{"ok":','true}']);self.assertEqual(got,value)
  self.assertTrue(all('response_received'not in state for _,state in received))
 def test_display_callback_error_does_not_repeat_or_recover_paid_request(self):
  calls=[];value=native()
  def opener(req,timeout):calls.append(req.method);return sse([created(),{'type':'response.output_text.delta','delta':'{"ok":true}'},{'type':'response.completed','response':value}])
  req=urllib.request.Request('https://api.openai.com/v1/responses',data=b'{}',method='POST')
  def bad(_):raise ValueError('display failed')
  self.assertEqual(connection.request_once(req,open_url=opener,update=lambda **v:None,on_delta=bad),value);self.assertEqual(calls,['POST'])
 def test_cancelled_stream_has_no_forced_complete_preview_or_new_post(self):
  calls=[];checks=[0];received=[]
  def check():
   checks[0]+=1
   if checks[0]>3:raise InterruptedError('cancel')
  def opener(req,timeout):calls.append(req.method);return sse([created()]+[{'type':'response.output_text.delta','delta':'a'}]*10)
  req=urllib.request.Request('https://api.openai.com/v1/responses',data=b'{}',method='POST')
  with self.assertRaises(InterruptedError):connection.request_once(req,open_url=opener,update=lambda **v:None,check=check,on_delta=received.append)
  self.assertEqual(calls,['POST']);self.assertLess(len(received),10)


class ProviderPreviewTests(ResponsesProviderTests):
 def test_study_delta_hook_leaves_request_identity_usage_and_terminal_cache_authoritative(self):
  p=self.provider(mode='responses');value=native();seen=[]
  self.opener.side_effect=None
  self.opener.return_value=sse([created(),{'type':'response.output_text.delta','delta':'{"ok":true}'},{'type':'response.completed','response':value}])
  self.assertEqual(p.complete(self.payload,on_study_delta=seen.append,**self.options),{'ok':True})
  self.assertEqual(seen,['{"ok":true}']);self.assert_settled_native(p,value)
  self.assertEqual(self.opener.call_count,1)
  other=self.provider(mode='responses');cached=[]
  self.assertEqual(other.complete(self.payload,on_study_delta=cached.append,**self.options),{'ok':True})
  self.assertEqual(cached,[]);self.assertEqual(self.opener.call_count,1)
 def test_preview_cancellation_preserves_unknown_usage_hold_and_does_not_repost(self):
  import pdf_ai as ai
  p=self.provider(mode='responses')
  cancelled={'id':'resp_fixture','status':'cancelled','output':[],'usage':None}
  def reply(req,timeout):
   if req.method=='GET'or req.full_url.endswith('/cancel'):
    value=io.StringIO(json.dumps(cancelled));value.headers={};return value
   return sse([created(),{'type':'response.output_text.delta','delta':'{"ok":true}'}])
  self.opener.side_effect=reply
  def cancel(_):raise InterruptedError('user cancelled preview generation')
  with patch('pdf_study_connection.RECOVERY_READS',1),self.assertRaises(InterruptedError):p.complete(self.payload,on_study_delta=cancel,**self.options)
  entry=p.ledger['requests'][0]
  self.assertEqual([call.args[0].method for call in self.opener.call_args_list],['POST','POST','GET'])
  self.assertEqual(entry['state'],'usage_unknown')
  self.assertNotIn('estimatedUsd',entry);p.billing.settle.assert_called_once_with(entry['requestId'],None)
  self.assertTrue(self.paths(entry)[0].with_suffix('.receipt.json').exists())
  with self.assertRaises(ai.AiResponseError):p.complete(self.payload,on_study_delta=lambda _:None,**self.options)
  self.assertEqual(self.opener.call_count,3)


class PipelinePreviewTests(unittest.TestCase):
 def fixture(self):
  from test_pdf_speed_pipeline import CropPipelineTests
  fixture=CropPipelineTests('test_semantic_generation_has_a_hard_fourteen_request_ceiling');fixture.setUp()
  self.addCleanup(fixture.doCleanups);return fixture
 def run_streamed_pipeline(self,*,fail_first=False,invalid_first=False):
  fixture=self.fixture();seen=[];original=PreviewPublication
  def publication(*a,**kw):
   canonical_emit=kw['emit']
   def emit(kind,**values):
    seen.append((kind,copy.deepcopy(values)))
    canonical_emit(kind,**values)
   return original(*a,**{**kw,'emit':emit})
  def complete(payload,**kwargs):
   source=payload['blocks'][0]['id'];index=int(source[-1]);legacy=fixture.reply(source)
   value=teaching(legacy['concepts'][0]['title'],legacy['concepts'][0]['definition'])
   value.pop('metadata')
   for segment in value['concepts'][0]['segments']:segment['blockIds']=[source]
   value['concepts'][0]['segments']=value['concepts'][0]['segments'][:2]
   value['concepts'][0]['segments'][1]['text']=legacy['concepts'][0]['explanation']
   wire=json.dumps(value,ensure_ascii=False)
   callback=kwargs['on_study_delta'];cut=wire.index(legacy['concepts'][0]['definition'])+8
   callback(wire[:cut]);seen.append(('generation_still_open',{'unit':index+1}))
   if index==0:
    self.assertTrue(any(kind=='summary_unit_delta'and event['unit']==1 for kind,event in seen))
    self.assertFalse(list(fixture.folder.rglob('unit-00000.json')),'preview was persisted as validated teaching')
   if index==0 and fail_first:raise TimeoutError('synthetic interrupted final')
   callback(wire[cut:])
   if index==0 and invalid_first:
    callback('INVALID_TRAILING_JSON');return {'concepts':'invalid final type'}
   return value
  with patch('pdf_study_stream.PreviewPublication',side_effect=publication):
   result,cache=fixture.run_pipeline(lambda _:None,complete=complete)
  return result,cache,seen
 def test_preview_before_generation_completion_without_cache_or_concept_contamination(self):
  result,cache,seen=self.run_streamed_pipeline()
  self.assertTrue(result['processingComplete']);self.assertEqual(result['partialUnits'],3)
  self.assertIsNotNone(result['metrics']['firstPreviewSeconds'])
  self.assertLessEqual(result['metrics']['firstPreviewSeconds'],result['metrics']['firstResultSeconds'])
  self.assertEqual(len(list(cache.glob('unit-*.json'))),3)
  for kind,event in seen:
   if kind=='summary_unit_delta':
    self.assertTrue(event['preview']);self.assertEqual(event['scope'],'document')
    self.assertNotIn('PRIVATE',event['summary']['body'])
 def test_invalid_partial_json_and_rejected_final_remove_preview_without_persisting(self):
  result,cache,seen=self.run_streamed_pipeline(invalid_first=True)
  self.assertFalse(result['processingComplete']);self.assertFalse((cache/'unit-00000.json').exists())
  self.assertTrue(any(kind=='summary_unit_delta'and event['unit']==1 and event.get('discard') for kind,event in seen))
 def test_failed_generation_discards_preview_and_keeps_failure_truthful(self):
  result,cache,seen=self.run_streamed_pipeline(fail_first=True)
  self.assertFalse(result['processingComplete']);self.assertFalse((cache/'unit-00000.json').exists())
  self.assertTrue(any(kind=='summary_unit_delta'and event['unit']==1 and event.get('discard') for kind,event in seen))
  self.assertTrue(result['failedUnits'])

if __name__=='__main__':unittest.main()
