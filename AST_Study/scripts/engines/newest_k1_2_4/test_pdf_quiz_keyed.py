"""Offline keyed slots, metadata provenance and lossless partial responses."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_quiz as quiz
from pdf_quiz_keyed import scoped_question_schema, decode_keyed_questions
from pdf_quiz_targets import wire_assignment
from test_pdf_quiz import fixture, planned
from test_pdf_quiz_targets import target_plan, slot_answers
from test_pdf_quiz_parallel import ConcurrentProvider


class KeyedQuestionTests(unittest.TestCase):
    def setUp(self):
        self.document, self.request = fixture(8, list(quiz.TYPES))
        self.config, self.outline, catalog, self.concepts, self.sources = quiz.context(self.document, self.request)
        self.raw_plan = target_plan(8, list(quiz.TYPES), units=2)
        self.plan = quiz.validate_plan(self.raw_plan, catalog, self.config)
        units = self.plan['allocations']
        self.job = {'unitId': 'packed', 'units': units, 'conceptIds': ['c1', 'c2'],
                    'counts': dict.fromkeys(quiz.TYPES, 2)}

    def test_schema_requires_every_owned_key_with_one_metadata_free_definition(self):
        base = quiz._schema('questions'); original = copy.deepcopy(base)
        scoped = scoped_question_schema(base, self.job)
        schema = scoped['json_schema']['schema']
        keys = [t['id'] for unit in self.job['units'] for t in unit['targets']]
        self.assertEqual(schema['properties']['questions']['required'], keys)
        self.assertEqual(set(schema['properties']['questions']['properties']), set(keys))
        self.assertFalse(schema['properties']['questions']['additionalProperties'])
        for prop in schema['properties']['questions']['properties'].values():
            self.assertIn(prop['$ref'], ('#/$defs/question','#/$defs/question_mcq','#/$defs/question_essay','#/$defs/question_ox'))
        definition = schema['$defs']['question']
        for key in ('type', 'targetId', 'unitId', 'conceptIds'):
            self.assertNotIn(key, definition['properties'])
            self.assertNotIn(key, definition['required'])
        self.assertEqual(base, original)
        self.assertEqual(scoped_question_schema(base, wire_assignment(self.job)), scoped)

    def test_ox_wire_schema_rejects_answer_with_explanation(self):
        scoped=scoped_question_schema(quiz._schema('questions'),self.job)['json_schema']['schema']
        self.assertEqual(scoped['$defs']['question_ox']['properties']['answer']['enum'],['O','X'])
        answer_schema=scoped['$defs']['question_ox']['properties']['answer']
        self.assertNotIn('enum',scoped['$defs']['question']['properties']['answer'])

    def test_legacy_count_schema_and_array_response_stay_unchanged(self):
        base = quiz._schema('questions')
        legacy = planned()['allocations'][0]
        self.assertIs(scoped_question_schema(base, legacy), base)
        raw = {'questions': [{'type': 'ox', 'stem': 'legacy', 'targetId': 'old'}]}
        self.assertEqual(decode_keyed_questions(raw, self.job), raw)

    def test_metadata_always_comes_from_original_assignment(self):
        target = self.job['units'][0]['targets'][0]
        body = {'stem': '문제', 'type': 'essay', 'conceptIds': ['unrelated'],
                'targetId': 'other', 'unitId': 'other', 'answer': 'O'}
        raw = {'questions': {target['id']: body}}
        original = copy.deepcopy(raw)
        question = decode_keyed_questions(raw, self.job)['questions'][0]
        self.assertEqual(raw, original)
        self.assertEqual(question['type'], target['type'])
        self.assertEqual(question['targetId'], target['id'])
        self.assertEqual(question['unitId'], self.job['units'][0]['unitId'])
        self.assertEqual(question['conceptIds'], target['conceptIds'])
        self.assertEqual(question['rawQuestion'], body)
        self.assertTrue(question['warnings'])

    def test_unknown_keys_and_malformed_values_are_never_discarded(self):
        target = self.job['units'][0]['targets'][0]
        raw = {'questions': {target['id']: None, 'unexpected': {'stem': '추가 원문', 'type': 'ox',
                'unitId': self.job['units'][0]['unitId'], 'conceptIds': ['c1']}, 'broken': '원래 문자열'}}
        questions = decode_keyed_questions(raw, self.job)['questions']
        self.assertEqual(len(questions), 3)
        self.assertIsNone(questions[0]['rawQuestion'])
        self.assertEqual(questions[1]['stem'], '추가 원문')
        self.assertIsNone(questions[1]['type'])
        self.assertIsNone(questions[1]['unitId'])
        self.assertEqual(questions[2]['rawQuestion'], '원래 문자열')
        self.assertTrue(all(q['warnings'] for q in questions))

    def test_missing_keys_do_not_create_blank_questions(self):
        tid = self.job['units'][0]['targets'][0]['id']
        result = decode_keyed_questions({'questions': {tid: {'stem': '한 개'}}}, self.job)
        self.assertEqual(len(result['questions']), 1)
        self.assertEqual(result['questions'][0]['targetId'], tid)

    def test_input_bound_uses_actual_assignment_schema_size(self):
        payload = quiz.generation_payload(self.config, self.outline, self.plan, self.job,
                                          self.concepts, self.sources, [], 'fixed')
        base = quiz._schema('questions')
        scoped = scoped_question_schema(base, self.job)
        bound = quiz.input_bound(payload, 'prompt', base)
        messages = [{'role': 'system', 'content': 'prompt'},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        expected = len(json.dumps(messages, ensure_ascii=False).encode()) + 2048 + len(json.dumps(scoped).encode())
        self.assertEqual(bound, expected)
        self.assertEqual(bound, quiz.input_bound(payload, 'prompt', scoped))
        # A flat-task experiment can omit the nested wire assignment without
        # making the schema-size admission bound revert to the legacy array.
        payload['tasks'] = copy.deepcopy(payload['assignment']['tasks'])
        payload.pop('assignment')
        self.assertEqual(quiz.input_bound(payload, 'prompt', base),
                         quiz.input_bound(payload, 'prompt', scoped))

    def run_generation(self, change=lambda raw: raw):
        def answer(payload):
            raw = slot_answers(payload)
            raw['questions'] = {q['targetId']: {k: v for k, v in q.items()
                              if k not in ('type', 'unitId', 'targetId', 'conceptIds')}
                                for q in raw['questions']}
            return change(raw)
        provider = ConcurrentProvider(self.raw_plan, answer)
        with tempfile.TemporaryDirectory() as folder, patch.object(quiz, 'emit'), \
                patch('socket.socket.connect', side_effect=AssertionError('no network')):
            result = quiz.generate(Path(folder), self.document, self.request, provider)
        self.assertEqual(len(provider.calls), 1 + (8 + quiz.MAX_BATCH_QUESTIONS - 1) // quiz.MAX_BATCH_QUESTIONS)
        self.assertEqual(result['refillRounds'], 0)
        self.assertFalse(result['errors'], result['errors'])
        return result, provider

    def test_separated_contract_through_complete_offline_pipeline(self):
        kinds={t['id']:t['type'] for u in self.plan['allocations'] for t in u['targets']}
        def convert(raw):
            for tid,q in raw['questions'].items():
                if kinds[tid]=='mcq':
                    answer=q.pop('answer'); wrong=q.pop('distractors');q.pop('keyPoints')
                    q['options']=[{'optionId':'O01','text':answer,'explanation':q['explanation']}]+[
                        {'optionId':f'O0{i}',**o} for i,o in enumerate(wrong,2)]
                    q['correctOptionId']='O01'
                elif kinds[tid]=='essay':
                    q['exampleAnswer']=q.pop('answer');q['commonRequirements']=q.pop('keyPoints')
                    q.pop('options',None);q['conditionalRequirements']=[{'condition':'방법 B','requirement':'B 전제'}]
                    q['acceptedAliases']=[]
            return raw
        result,_=self.run_generation(convert)
        self.assertEqual(len(result['questions']),8)
        for q in result['questions']:
            if q['type'] in ('mcq','essay'):
                self.assertEqual(q['answerContractVersion'],'study-answer-v1')
                self.assertIn('rawGenerationQuestion',q)
                self.assertNotIn('warnings',q)
            if q['type']=='essay':self.assertIn('조건: 방법 B → 요구: B 전제',q['keyPoints'])
            if q['type']=='mcq':self.assertEqual(next(o for o in q['options'] if o['id']==q['answer'])['optionId'],'O01')

    def test_full_pipeline_decodes_before_quotes_calculations_and_answer_assembly(self):
        result, provider = self.run_generation()
        self.assertEqual(len(result['questions']), 8)
        self.assertEqual({q['targetId'] for q in result['questions']}, {f't{i}' for i in range(1, 9)})
        expected = {t['id']: (u['unitId'], t['type'], t['conceptIds'])
                    for u in self.plan['allocations'] for t in u['targets']}
        for q in result['questions']:
            self.assertEqual((q['unitId'], q['type'], q['conceptIds']), expected[q['targetId']])
            self.assertTrue(q['evidence'])
        returned_keys = []
        for payload, options, _ in provider.calls[1:]:
            schema = options['response_format']['json_schema']['schema']
            keys = schema['properties']['questions']['required']
            self.assertLessEqual(len(keys), quiz.MAX_BATCH_QUESTIONS)
            self.assertEqual(set(keys), {t['targetId'] for t in payload['assignment']['tasks']})
            returned_keys.extend(keys)
        self.assertEqual(set(returned_keys), set(expected))
        self.assertEqual(len(returned_keys), len(set(returned_keys)))

    def test_pipeline_partial_malformed_and_surplus_are_shown_without_retry(self):
        def damage(raw):
            keys = list(raw['questions'])
            raw['questions'] = {keys[0]: raw['questions'][keys[0]], keys[1]: None,
                                'unknown': {'stem': '모르는 목표의 생성 문항'}, 'string': '생성 문자열'}
            return raw
        result, _ = self.run_generation(damage)
        jobs = (8 + quiz.MAX_BATCH_QUESTIONS - 1) // quiz.MAX_BATCH_QUESTIONS
        self.assertEqual(len(result['questions']), 4 * jobs)
        self.assertEqual(result['unfilled'], max(0, 8 - 4 * jobs))
        self.assertEqual(sum(bool(q.get('warnings')) for q in result['questions']), 3 * jobs)


if __name__ == '__main__':
    unittest.main()
