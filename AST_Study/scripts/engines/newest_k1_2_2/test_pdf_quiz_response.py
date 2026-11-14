"""Offline single-answer assembly through generation, validation and shuffling."""
import copy
import unittest

import pdf_quiz as quiz
from pdf_quiz_response import assemble_answers
from pdf_quiz_review import shuffle_display_options
from test_pdf_quiz import fixture, planned, question
import test_pdf_quiz_instructions as instruction_tests


def draft():
    q = question('mcq')
    q.pop('options')
    q.update(answer='lunes', explanation='단수형과 복수형이 같은 lunes이다.',
             distractors=[{'text': text, 'explanation': '형태를 바꾸어 틀리다.'}
                          for text in ('luneses','luness','lune')])
    return {'questions':[q], 'unfilled':0, 'reason':''}


class QuizResponseTests(unittest.TestCase):
    def test_passage_and_task_have_explicit_boundaries_without_changing_answer(self):
        raw = draft()
        q = raw['questions'][0]
        q.update(type='ox', passage='동아시아의 성장에는 국제 체제와 군사적 긴장이 작용했다.',
                 stem='제시문에 따르면 발전 조건을 지도자 개인의 능력만으로 설명할 수 있다.',
                 answer='X', distractors=[])
        before = copy.deepcopy(raw)
        item = assemble_answers(raw)['questions'][0]
        self.assertEqual(item['answer'], 'X')
        self.assertTrue(item['stem'].startswith('### 제시문\n'))
        self.assertIn('\n\n### 판단할 진술\n제시문에 따르면', item['stem'])
        self.assertNotIn('passage', item)
        self.assertEqual(assemble_answers({'questions': [item]})['questions'][0], item)
        self.assertEqual(raw, before)

    def test_all_generation_body_schemas_require_passage_with_no_extra_call(self):
        from pdf_quiz_keyed import scoped_question_schema
        schema = quiz._schema('questions')
        self.assertIn('passage', schema['json_schema']['schema']['properties']['questions']['items']['required'])
        for kind in ('mcq','ox','essay','word'):
            assignment = {'unitId': 'u1', 'targets': [{'id': 't1', 'type': kind, 'conceptIds': ['c1']}]}
            scoped = scoped_question_schema(schema, assignment)['json_schema']['schema']
            body = scoped['$defs'].get('question_'+kind, scoped['$defs']['question'])
            self.assertEqual(body['properties']['passage']['type'], 'string')
            self.assertIn('passage', body['required'])

    def test_empty_passage_does_not_invent_material_and_legacy_keeps_text(self):
        raw = draft();raw['questions'][0]['passage'] = ''
        q = assemble_answers(raw)['questions'][0]
        self.assertTrue(q['stem'].startswith('### 문제\n'))
        self.assertNotIn('### 제시문', q['stem'])
        legacy = {'questions':[question('ox')],'unfilled':0,'reason':''}
        self.assertEqual(assemble_answers(legacy), legacy)

    def test_single_answer_contract_without_experimental_field_order(self):
        schema = quiz._schema('questions')['json_schema']['schema']['properties']['questions']['items']
        keys = list(schema['properties'])
        self.assertLess(keys.index('answer'), keys.index('distractors'))
        self.assertNotIn('verification', keys)
        self.assertEqual(assemble_answers(draft())['questions'][0]['options'][0]['explanation'],
                         draft()['questions'][0]['explanation'])

    def test_answer_text_and_explanation_have_one_origin_even_after_shuffle(self):
        raw = draft(); before = copy.deepcopy(raw)
        result = assemble_answers(raw)
        self.assertEqual(raw, before)
        document, request = fixture(1, ['mcq'])
        *_, concepts, sources = quiz.context(document, request)
        assignment = planned({'ox':0,'mcq':1,'word':0,'essay':0})['allocations'][0]
        items, rejected = quiz.validate_questions(result,assignment,concepts,sources,set())
        self.assertEqual((len(items),rejected),(1,0))
        for seed in ('one','two','three'):
            shuffle_display_options(items,seed)
            item = items[0]
            correct = next(o for o in item['options'] if o['id']==item['answer'])
            self.assertEqual(correct['text'],raw['questions'][0]['answer'])
            self.assertEqual(correct['explanation'],item['explanation'])
            self.assertEqual({o['text'] for o in item['options']},{'lunes','luneses','luness','lune'})

    def test_schema_cannot_independently_emit_correct_option_or_answer_id(self):
        schema = quiz._schema('questions')['json_schema']['schema']
        props = schema['properties']['questions']['items']['properties']
        self.assertNotIn('options',props)
        self.assertNotIn('id',props['distractors']['items']['properties'])
        self.assertEqual(props['distractors']['maxItems'],3)
        self.assertLess(list(props).index('answer'),list(props).index('distractors'))

    def test_duplicate_correct_answer_is_shown_with_warning_not_repaired(self):
        raw = draft(); raw['questions'][0]['distractors'][0]['text']='lunes'
        document,request=fixture(1,['mcq']);*_,concepts,sources=quiz.context(document,request)
        assignment=planned({'ox':0,'mcq':1,'word':0,'essay':0})['allocations'][0]
        items,rejected=quiz.validate_questions(assemble_answers(raw),assignment,concepts,sources,set())
        self.assertEqual((len(items),rejected),(1,0))
        self.assertTrue(items[0]['warnings'])
        self.assertEqual(items[0]['options'][0]['text'],items[0]['options'][1]['text'])

    def test_malformed_distractors_and_non_mcq_choices_stay_invalid(self):
        for choices in (None,[],[{}, {}, {}], [{'id':'B','text':'x','explanation':'y'}]*3):
            raw=draft();raw['questions'][0]['distractors']=choices
            assembled=assemble_answers(raw)['questions'][0]
            self.assertIsNone(assembled['options'])
            self.assertEqual(assembled['distractors'], choices)
        raw=draft();raw['questions'][0]['type']='essay'
        self.assertIsNone(assemble_answers(raw)['questions'][0]['options'])
        raw['questions'][0]['distractors']=[]
        self.assertEqual(assemble_answers(raw)['questions'][0]['options'],[])

    def test_existing_saved_workbook_is_not_reinterpreted(self):
        raw={'questions':[question('mcq')],'unfilled':0,'reason':''}
        self.assertEqual(assemble_answers(raw),raw)

    def test_actual_generation_uses_same_two_calls_with_new_wire_answer(self):
        document,request=fixture(1,['mcq'])
        def answer(payload):
            raw=instruction_tests.wire_answers(payload)
            for item in raw['questions']:
                options=item.pop('options')
                correct=next(o for o in options if o['id']==item['answer'])
                item['distractors']=[{k:o[k] for k in ('text','explanation')}
                                     for o in options if o is not correct]
                item['answer']=correct['text']
            return raw
        harness=instruction_tests.QuizInstructionFlowTests()
        output,calls=harness.run_request(document,request,
            planned({'ox':0,'mcq':1,'word':0,'essay':0}),answer)
        self.assertEqual((len(output['questions']),len(calls),output['refillRounds']),(1,2,0))

    def test_shared_targets_survive_single_answer_assembly(self):
        document,request=fixture(2,['mcq'])
        plan={'allocations':[{'unitId':'u1','conceptIds':['c1'], 'targets':[
            {'type':'mcq','conceptIds':['c1'],'goal':'정의에 맞는 사례'},
            {'type':'mcq','conceptIds':['c1'],'goal':'적용 조건의 구별'}]}],
            'unallocated':0,'reason':''}
        def answer(payload):
            from test_pdf_quiz_targets import slot_answers
            return slot_answers(payload)
        output,calls=instruction_tests.QuizInstructionFlowTests().run_request(document,request,plan,answer)
        self.assertEqual((len(output['questions']),len(calls)),(2,2))
        self.assertEqual({q['targetId'] for q in output['questions']},{'t1','t2'})
        for q in output['questions']:
            self.assertEqual(next(o['explanation'] for o in q['options'] if o['id']==q['answer']),q['explanation'])


if __name__ == '__main__':
    unittest.main()
