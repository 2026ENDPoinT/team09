import copy
import importlib
import unittest
from pdf_study_review import reconcile_coverage,repair_serialized_closer,numerical_guards,reading_effort,section_source_context,continuation_visual_context
from test_pdf_newest_k1_1_1 import block,response

class AccountingTests(unittest.TestCase):
 def test_missing_equations_remain_reviewable_without_guessing(self):
  from pdf_study_review import missing_expression_slot
  self.assertTrue(missing_expression_slot('합한 결과는 \n이고, 크기도 구해요.'))
  self.assertTrue(missing_expression_slot('성분은 \n, \n예요.'))
  for text in ['합한 결과는\n\\(x=3\\)\n이에요.','나누면\n두 값을 비교할 수 있어요.','성분은 아래와 같아요.\n의미를 살펴봐요.','```text\n성분은 \n, \n```']:
   self.assertFalse(missing_expression_slot(text))
  for version in ('2','3'):
   e=importlib.import_module('pdf_newest_k1_1_'+version);bs=self.make();raw=response('a')
   for segment in raw['concepts'][0]['segments']:
    if segment['kind']=='explanation':segment['text']='합한 결과는 \n이고, 크기도 구해요.'
   val=e.validate(raw,{'id':'j','title':'test','blocks':bs},{'documentId':'d','pages':[{'label':'1'}]})
   self.assertTrue(any(c['blockId']=='a'and c['state']=='needs_review'for c in val['coverage']))
   self.assertNotIn('합한 결과는',val['summary']['body'])
 def test_context_never_exceeds_target_image_capacity(self):
  from pdf_study_review import continuation_context_images
  # No rendering or filesystem access when all image slots belong to targets.
  self.assertEqual(continuation_context_images('/does-not-exist',[],{},available_images=0),[])
 def test_background_image_only_for_isolated_same_section_tail(self):
  image={'id':'figure','page':1,'headingId':'h','bbox':[.1,.2,.8,.6],'hasVisual':True}
  tail={'id':'claim','page':1,'headingId':'h','bbox':[.4,.8,.7,.86],'text':'결론'}
  blocks=[image,tail];before=copy.deepcopy(blocks)
  result=continuation_visual_context(blocks,{'blocks':[tail]})
  self.assertEqual(len(result),1);self.assertNotIn(result[0]['id'],[b['id']for b in blocks])
  self.assertEqual(result[0]['bbox'],[.1,.2,.8,.86]);self.assertEqual(blocks,before)
  self.assertEqual(continuation_visual_context(blocks,{'blocks':blocks}),[])
  for changed in [dict(image,page=2),dict(image,headingId='other'),dict(image,hasVisual=False)]:
   self.assertEqual(continuation_visual_context([changed,tail],{'blocks':[tail]}),[])
 def test_math_lines_keep_content_and_reject_incomplete_or_code(self):
  text='평균은\nv_{avg}=d/\\Delta t\n예요.'
  self.assertEqual(repair_serialized_closer(text),'평균은\n\\(v_{avg}=d/\\Delta t\\)\n예요.')
  for text in ['```text\nx=\\Delta t\n```','\n    x=\\Delta t\n','\n\\Delta t +\n','\n\\frac{x}{\n','$$\nx=\\Delta t\n$$','\nWe use \\Delta t here\n']:
   self.assertEqual(repair_serialized_closer(text),text)
 def test_split_section_recovers_native_premise_past_images(self):
  bs=[{'id':'a','text':'처음의 높이와 속력이 서로 달라요.','page':1,'headingId':'h','kind':'text'}]
  bs += [{'id':str(i),'text':'','page':1,'headingId':'h','kind':'visual'}for i in range(10)]
  bs += [{'id':'end','text':'그러므로 만나요.','page':1,'headingId':'h','kind':'text'},
         {'id':'other','text':'다른 페이지 문제예요.','page':2,'headingId':'h','kind':'text'}]
  job={'blocks':[bs[-2]]};before=copy.deepcopy(bs)
  context=section_source_context(bs,job,[])
  self.assertEqual([x['text']for x in context],[bs[0]['text']])
  self.assertTrue(context[0]['backgroundOnly']);self.assertEqual(bs,before)
  self.assertEqual(len(section_source_context(bs,job,context)),1)
 def test_reasoning_is_selective_and_keeps_explicit_setting(self):
  plain=[{'id':'s','text':'일반적인 설명 문장이에요.','hasVisual':False}]
  self.assertEqual(reading_effort(plain),'none')
  code=[{'id':'s','text':'if (i < 7) recur(i + 1);'}]
  self.assertEqual(reading_effort(code),'low')
  visual=[{'id':'s','text':'a b c','hasVisual':True,'bbox':[.1,.1,.8,.8]}]
  self.assertEqual(reading_effort(visual),'low')
  visual[0]['bbox']=[.1,.1,.15,.15]
  self.assertEqual(reading_effort(visual),'none')
  self.assertEqual(reading_effort(plain,'low'),'low')
 def test_computed_guard_ids_follow_wire_aliases(self):
  from test_pdf_source_aliases import fixture
  from pdf_source_aliases import encode
  from pdf_newest_k1_1_3 import STUDY_FORMAT
  payload,job,ids,_=fixture()
  payload['sourceConditionChecks']=[{'blockId':ids[0],'expression':'if (i < 7)','samples':[True,False]}]
  original=copy.deepcopy(payload)
  wire,_,_=encode(payload,STUDY_FORMAT,job)
  self.assertEqual(wire['sourceConditionChecks'][0]['blockId'],'a')
  self.assertEqual(wire['sourceConditionChecks'][0]['samples'],[True,False])
  self.assertEqual(payload,original)
 def test_comparison_truth_does_not_guess_branch_action(self):
  for op,expected in [('<',[True,False,False]),('>=',[False,True,True]),('!=',[True,False,True])]:
   out=numerical_guards([{'id':'s','text':'if (level '+op+' 7) recurse(level + 1);'}])
   self.assertEqual([x['conditionTrue']for x in out[0]['samples']],expected)
   self.assertNotIn('action',out[0])
  self.assertEqual(numerical_guards([{'id':'s','text':'if (a < f())'}]),[])
 def test_serialized_closer_repairs_only_complete_non_code_math(self):
  self.assertEqual(repair_serialized_closer(r'값 \(y_f=0\u000a)이에요.'),r'값 \(y_f=0\)이에요.')
  self.assertEqual(repair_serialized_closer(r'값 \\(x=2\\)예요.'),r'값 \(x=2\)예요.')
  self.assertEqual(repair_serialized_closer(r'`\\(x=2\\)`'),r'`\\(x=2\\)`')
  for text in [r'`\(y_f=0\u000a)`',r'\(x={\u000a)',r'\(설명\u000a)',r'\(x+\u000a)']:
   self.assertEqual(repair_serialized_closer(text),text)
 def make(self,kind='text',text='배우는 주제',box=None):
  b=block(0);b.update(id='a',page=1,kind=kind,text=text,wordIds=['w'],bbox=box or [.03,.04,.3,.09],fontSize=24)
  peer=copy.deepcopy(b);peer.update(id='b',text='구체적인 본문을 설명해요.',bbox=[.05,.2,.8,.4])
  return [b,peer]
 def cv(self,reason='응답에 이 영역의 처리 여부가 빠졌어요.'):
  return [{'blockId':'a','page':1,'state':'needs_review','reason':reason},{'blockId':'b','page':1,'state':'summarized','reason':'covered'}]
 def test_heading_cross_unit_requires_taught_body(self):
  bs=self.make();cs=self.cv();reconcile_coverage(cs,bs);self.assertEqual(cs[0]['state'],'context')
  cs=self.cv();cs[1]['state']='pending_summary';reconcile_coverage(cs,bs);self.assertEqual(cs[0]['state'],'needs_review')
 def test_caption_cannot_discard_full_problem_or_figure(self):
  for t in ['[2021 기출]','네','Graph Search']:
   bs=self.make('visual',t,[0,.1,1,.9]);bs[0]['hasVisual']=True
   cs=self.cv('기사·사례·도식의 중요한 내용이 빠졌는지 확인이 필요해요: 제목뿐이에요.')
   reconcile_coverage(cs,bs);self.assertEqual(cs[0]['state'],'needs_review')
 def test_explicit_uncertainty_and_math_remain(self):
  for reason in ['local_output_check: numeric_equality','판독할 수 없는 조건이에요.']:
   cs=self.cv(reason);reconcile_coverage(cs,self.make());self.assertEqual(cs[0]['state'],'needs_review')
  cs=self.cv();cs[0]['reviewKind']='content';reconcile_coverage(cs,self.make());self.assertEqual(cs[0]['state'],'needs_review')
 def test_formula_not_heading(self):
  for t in ['F=ma','if (n < 4)','x → y','값을 구하라']:
   cs=self.cv();reconcile_coverage(cs,self.make(text=t));self.assertEqual(cs[0]['state'],'needs_review')
 def test_page_number_but_not_numerical_teaching(self):
  for box,expected in [([.94,.94,.95,.96],'context'),([.5,.4,.51,.42],'needs_review')]:
   cs=self.cv();reconcile_coverage(cs,self.make('visual','4',box));self.assertEqual(cs[0]['state'],expected)
 def test_supported_supplement_and_missing_main_definition_differ(self):
  for v in ('2','3'):
   engine=importlib.import_module('pdf_newest_k1_1_'+v)
   bs=self.make();bs[1].update(kind='visual',hasVisual=True);job={'id':'j','title':'test','blocks':bs};doc={'documentId':'d','pages':[{'label':'1'}]}
   raw=response('a');second=copy.deepcopy(raw['concepts'][0]);second['title']='사례';second['segments']=[s for s in second['segments'] if s['kind']!='definition']
   for s in second['segments']:s['blockIds']=['b']
   raw['concepts'].append(second)
   val=engine.validate(copy.deepcopy(raw),job,doc)
   self.assertFalse(any(c['state']=='needs_review' for c in val['coverage']))
   raw['concepts']=raw['concepts'][1:];val=engine.validate(raw,job,doc)
   self.assertTrue(any(c['state']=='needs_review' and c['blockId']=='b' for c in val['coverage']))
if __name__=='__main__':unittest.main()
