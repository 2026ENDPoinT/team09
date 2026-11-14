"""The complete generation/cache path selects cards and keeps ordinary teaching."""
import copy
import unittest
from pdf_step_flow import normalize_existing_flows
import pdf_new_concept_ver99_study as study


def fixture(count=3):
    texts=['수집 결과를 정제의 입력으로 사용한다.', '정제 결과에 의해 게시할 자료가 결정된다.']
    blocks=[{'id':f'b{i}','page':1,'kind':'text','text':text,'bbox':[0,.1+i*.2,1,.3+i*.2],
             'hasVisual':False} for i,text in enumerate(texts)]
    raw={'concepts':[{'title':'자료 처리','definition':'자료를 처리하는 원리예요.',
        'explanation':'원자료를 바꾸어 결과를 제공해요.','easyExplanation':'자료가 모습을 바꾸어 전달돼요.',
        'blockIds':['b0','b1'],'standardKnowledgeUsed':False}],
        'sequences':[{'conceptTitle':'자료 처리','title':'자료 처리 단계','orderKind':'procedure',
            'transitions':[{'fromStep':0,'toStep':1,'relation':'수집 결과가 정제 입력으로 사용돼요.',
                            'blockIds':['b0'],'sourceQuote':texts[0]},
                           {'fromStep':1,'toStep':2,'relation':'정제 결과가 게시할 자료를 결정해요.',
                            'blockIds':['b1'],'sourceQuote':texts[1]}],
            'steps':[{'title':'수집','body':'원자료를 수집해요.','blockIds':['b0']},
                     {'title':'정제','body':'수집한 자료를 정제해요.','blockIds':['b0','b1']},
                     {'title':'게시','body':'정제한 자료를 게시해요.','blockIds':['b1']}][:count]}],
        'excludedBlocks':[],'uncertainBlocks':[]}
    return blocks,raw,{'documentId':'doc','pages':[{'label':'1'}]}


def validate(blocks,raw,doc):
    return study.validate(raw,{'id':'u','title':'자료 처리','blocks':blocks},doc)


class FlowAdmissionTests(unittest.TestCase):
    def test_real_three_stage_process_is_approved_without_a_review_call(self):
        blocks,raw,doc=fixture();before=copy.deepcopy(raw)
        value=validate(blocks,raw,doc);flow=value['summary']['parts'][0]['stepFlow']
        self.assertEqual(flow['eligibility']['policyVersion'],'ordered-process-v2')
        self.assertEqual(flow['eligibility']['transitionCount'],2)
        self.assertEqual(raw,before)
        self.assertEqual(len(value['coverage']),2)

    def test_two_stage_process_has_no_card_but_details_survive_in_both_tabs(self):
        blocks,raw,doc=fixture(2)
        value=validate(blocks,raw,doc);part=value['summary']['parts'][0];card=value['concepts'][0]
        self.assertNotIn('stepFlow',part)
        for field in (part['body'],card['explanation']):
            self.assertIn('원자료를 수집해요.',field);self.assertIn('수집한 자료를 정제해요.',field)
        self.assertEqual(len(value['concepts']),1)

    def test_three_parallel_facts_cannot_become_a_process_by_adding_order_words(self):
        blocks,raw,doc=fixture()
        blocks[0]['text']='첫째 명확한 목표를 쓴다. 둘째 충분한 맥락을 준다. 셋째 원하는 형식을 말한다.'
        blocks[1]['text']='세 원칙은 병렬적인 좋은 설명의 특징이다.'
        seq=raw['sequences'][0]
        seq['steps']=[{'title':a,'body':b,'blockIds':['b0','b1']} for a,b in
            [('목표','먼저 목표를 명확히 해요.'),('맥락','다음으로 충분한 맥락을 줘요.'),('형식','마지막으로 원하는 형식을 정해요.')]]
        for t in seq['transitions']:t['sourceQuote']=blocks[0]['text']
        value=validate(blocks,raw,doc)
        self.assertNotIn('stepFlow',value['summary']['parts'][0])
        self.assertIn('충분한 맥락',value['concepts'][0]['explanation'])

    def test_legacy_sequence_without_transition_proof_becomes_plain_not_lost(self):
        blocks,raw,doc=fixture();raw['sequences'][0].pop('transitions');raw['sequences'][0].pop('orderKind')
        value=validate(blocks,raw,doc)
        self.assertNotIn('stepFlow',value['summary']['parts'][0])
        self.assertIn('정제한 자료를 게시해요.',value['summary']['body'])
        self.assertIn('정제한 자료를 게시해요.',value['concepts'][0]['explanation'])

    def test_native_card_cannot_steal_the_surviving_part_after_an_empty_concept(self):
        blocks,raw,doc=fixture()
        bad={**raw['concepts'][0],'title':'탈락한 앞 개념','definition':'','explanation':'',
             'easyExplanation':'','_partialSupported':True}
        # Exercise the attachment join itself with one filtered-out raw concept.
        parts=[{'title':'자료 처리','body':'원래 내용','evidence':[]}]
        cards=[{'name':'자료 처리','explanation':'원래 내용','evidence':[]}]
        study.attach_step_flows(raw['sequences'],[bad]+raw['concepts'],parts,
            {b['id']:b for b in blocks},doc,cards=cards)
        self.assertEqual(parts[0]['stepFlow']['title'],'자료 처리 단계')

    def test_bad_step_reference_does_not_drop_the_ordinary_concept(self):
        blocks,raw,doc=fixture();raw['sequences'][0]['steps'][1]['blockIds']=[[]]
        value=validate(blocks,raw,doc)
        self.assertNotIn('stepFlow',value['summary']['parts'][0])
        self.assertIn('원자료를 바꾸어',value['summary']['body'])

    def test_visual_only_process_has_explicit_visual_citations_not_fake_quotes(self):
        blocks,raw,doc=fixture()
        figure={'id':'fig','page':1,'kind':'visual','text':'','bbox':[0,.1,1,.9],
                'hasVisual':True,'visualOnly':True}
        raw['concepts'][0]['blockIds']=['fig']
        for step in raw['sequences'][0]['steps']:step['blockIds']=['fig']
        for edge in raw['sequences'][0]['transitions']:edge.update(blockIds=['fig'],sourceQuote='')
        raw['sequences'][0]['transitions'][1]['relation']='정제 결과에 의해 게시할 자료가 결정돼요.'
        value=validate([figure],raw,doc);flow=value['summary']['parts'][0]['stepFlow']
        self.assertTrue(flow['eligibility']['inferredFromVisual'])
        self.assertTrue(all(s['evidence'][0]['sourceMode']=='visual' and s['evidence'][0]['quote']=='' for s in flow['steps']))

    def test_saved_fallback_preserves_all_stage_details_math_and_citations_idempotently(self):
        flow={'moduleId':'synesis.step-flow','schemaVersion':1,'variant':'a','title':'옛 카드','steps':[
            {'title':'첫 항목','body':r'원식 \(x=2\)예요.','context':'초기 조건','insight':'추가 관계',
             'evidence':[{'sourceId':'a','page':1,'quote':'source A'}]},
            {'title':'둘째 항목','body':'두 번째 설명이에요.',
             'evidence':[{'sourceId':'b','page':2,'quote':'source B'}]}]}
        result={'sections':[{'body':'기존 설명','parts':[{'title':'제목','body':'기존 설명','stepFlow':copy.deepcopy(flow)}]}],
                'concepts':[{'entries':[{'name':'제목','explanation':'개념 설명','stepFlow':copy.deepcopy(flow)}]}]}
        value=normalize_existing_flows(copy.deepcopy(result));again=normalize_existing_flows(copy.deepcopy(value))
        self.assertEqual(value,again);self.assertIn('stepFlow',result['sections'][0]['parts'][0])
        p=value['sections'][0]['parts'][0]
        self.assertNotIn('stepFlow',p)
        for detail in (r'\(x=2\)','초기 조건','추가 관계','두 번째 설명'):
            self.assertIn(detail,p['body']);self.assertIn(detail,value['concepts'][0]['entries'][0]['explanation'])
        self.assertEqual([e['sourceId'] for e in p['evidence']],['a','b'])
        self.assertEqual(value['sections'][0]['body'],p['body'])

    def test_new_policy_preserves_a_previously_approved_module(self):
        blocks,raw,doc=fixture();value=validate(blocks,raw,doc)
        flow=copy.deepcopy(value['summary']['parts'][0]['stepFlow'])
        normalize_existing_flows(value)
        self.assertEqual(flow,value['summary']['parts'][0]['stepFlow'])

    def test_fallback_deduplication_never_erases_changed_math_operators_or_case(self):
        from pdf_step_flow import append_sequence_fallback
        part={'body':'식: x+1, X > 0, a==b','evidence':[]}
        flow={'steps':[{'title':'식','body':'x-1, X < 0, a!=b','evidence':[]}]}
        append_sequence_fallback(part,flow)
        self.assertIn('x-1',part['body']);self.assertIn('X < 0',part['body']);self.assertIn('a!=b',part['body'])

    def test_single_supported_step_is_plain_teaching_not_silently_dropped(self):
        blocks,raw,doc=fixture(1)
        result=validate(blocks,raw,doc)
        self.assertNotIn('stepFlow',result['summary']['parts'][0])
        self.assertIn('원자료를 수집해요.',result['summary']['parts'][0]['body'])

    def test_fallback_preserves_numeric_prefixes_and_code_indentation(self):
        from pdf_step_flow import append_sequence_fallback
        part={'body':'식: 허용값 x=10\n```python\nif ok:\n    act()\n```','evidence':[]}
        flow={'steps':[{'title':'식','body':'허용값 x=1','context':'x=1','evidence':[]},
                       {'title':'코드','body':'```python\nif ok:\n    inspect()\nact()\n```','evidence':[]}]}
        append_sequence_fallback(part,flow)
        self.assertIn('허용값 x=1\n',part['body'])
        self.assertIn('  if ok:\n      inspect()\n  act()',part['body'])

    def test_indented_code_keeps_its_first_line_and_existing_body_whitespace(self):
        from pdf_step_flow import append_sequence_fallback
        part={'body':'    original()\n    preserved()','evidence':[]}
        flow={'steps':[{'title':'코드','body':'    x=1\n    y=2','context':'    a=3\n    b=4','evidence':[]}]}
        append_sequence_fallback(part,flow)
        self.assertTrue(part['body'].startswith('    original()\n    preserved()'))
        self.assertIn('      x=1\n      y=2',part['body'])
        self.assertIn('      a=3\n      b=4',part['body'])

if __name__=='__main__':unittest.main()
