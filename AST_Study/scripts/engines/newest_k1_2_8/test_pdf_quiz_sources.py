"""Offline source-ID transport and exact-quote restoration contracts."""
import copy
import unittest

import pdf_quiz as quiz
from pdf_quiz_sources import resolve_generation_quotes, wire_generation_payload
from pdf_quiz_transport import pack_generation_jobs, validate_job
from test_pdf_quiz import fixture, planned, question


def source(text, sid='s1'):
    return {'sourceId': sid, 'text': text, 'sourceKind': 'saved_concept', 'pages': [2, 1],
            'standardKnowledgeUsed': True, 'originalSourceIds': ['native-2', 'native-1'],
            'extractionTrace': {'version': 3}}


class QuizSourceTransportTests(unittest.TestCase):
    def test_passages_preserve_all_newlines_latex_and_unicode_exactly(self):
        text = ('첫 줄\n\n\\(\\lambda(x)=\\alpha x\\)\n'
                '$$\\int_0^L x\\,dm$$\n결합 문자 e\u0301 / 한글 한 / 🙂 / 끝\r\n') * 17
        payload = {'sources': [source(text)]}
        wire, quotes = wire_generation_payload(payload)
        passages = wire['sources'][0]['quotes']
        self.assertGreater(len(passages), 1)
        self.assertTrue(all(0 < len(q['text']) <= 240 for q in passages))
        self.assertEqual([q['quoteId'] for q in passages], [f'q{i+1}' for i in range(len(passages))])
        self.assertEqual(''.join(q['text'] for q in passages), text)
        for q in passages:
            self.assertEqual(quotes['s1', q['quoteId']], q['text'])
        raw = {'questions': [{'evidence': [{'sourceId': 's1', 'quoteId': q['quoteId']} for q in passages]}]}
        restored = resolve_generation_quotes(raw, quotes)
        self.assertEqual(''.join(q['quote'] for q in restored['questions'][0]['evidence']), text)
        self.assertTrue(all('quoteId' not in q for q in restored['questions'][0]['evidence']))

    def test_source_is_sent_once_with_only_required_metadata(self):
        original = source('공통 본문\n기준 조건')
        wire, quotes = wire_generation_payload({'sources': [original, copy.deepcopy(original)]})
        self.assertEqual(len(wire['sources']), 1)
        sent = wire['sources'][0]
        self.assertEqual(set(sent), {'sourceId', 'sourceKind', 'pages', 'standardKnowledgeUsed', 'quotes'})
        self.assertEqual(sent['pages'], [2, 1])
        self.assertEqual(sent['sourceKind'], 'saved_concept')
        self.assertIs(sent['standardKnowledgeUsed'], True)
        self.assertEqual(quotes, {('s1', 'q1'): original['text']})

    def test_same_source_id_with_conflicting_text_or_metadata_is_rejected(self):
        original = source('원래 본문')
        for key, value in [('text', '다른 본문'), ('sourceKind', 'native'), ('pages', [1, 2]),
                           ('standardKnowledgeUsed', False), ('originalSourceIds', ['different']),
                           ('extractionTrace', {'version': 4})]:
            with self.subTest(key=key):
                conflicting = {**copy.deepcopy(original), key: value}
                with self.assertRaisesRegex(ValueError, '메타데이터'):
                    wire_generation_payload({'sources': [original, conflicting]})

    def test_inputs_and_multi_unit_assignment_plan_outline_are_not_mutated(self):
        units = [{'unitId': 'one', 'conceptIds': ['c1'], 'counts': {'ox': 1}, 'focus': '첫 조건'},
                 {'unitId': 'two', 'conceptIds': ['c2'], 'counts': {'mcq': 1}, 'focus': '둘째 조건'}]
        payload = {'sources': [source('공유 원문')], 'outline': [{'title': '원래 목차'}],
                   'assignment': {'unitId': 'transport-0', 'units': units, 'conceptIds': ['c1', 'c2']},
                   'plan': {'allocations': units}, 'concepts': [{'id': 'c1', 'sourceIds': ['s1']}]}
        before = copy.deepcopy(payload)
        wire, quotes = wire_generation_payload(payload)
        self.assertEqual(payload, before)
        for key in ('outline', 'assignment', 'plan', 'concepts'):
            self.assertEqual(wire[key], payload[key])
            self.assertIsNot(wire[key], payload[key])
        raw = {'questions': [{'evidence': [{'sourceId': 's1', 'quoteId': 'q1'}]}]}
        previous = copy.deepcopy(raw)
        resolved = resolve_generation_quotes(raw, quotes)
        self.assertEqual(raw, previous)
        self.assertIsNot(resolved, raw)
        wire['assignment']['units'][0]['focus'] = '바뀐 사본'
        self.assertEqual(payload, before)

    def test_unknown_quote_rejects_only_its_question_in_a_real_multi_unit_validator(self):
        document, request = fixture(2, ['ox'])
        config, outline, _, concepts, sources = quiz.context(document, request)
        units = [planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0}, [cid], uid)['allocations'][0]
                 for uid, cid in [('one', 'c1'), ('two', 'c2')]]
        plan = {'allocations': units, 'unallocated': 0, 'reason': ''}

        def payload(assignment):
            return quiz.generation_payload(config, outline, plan, assignment, concepts, sources, [], 'source-test')
        job = pack_generation_jobs(units, payload, '', quiz._schema('questions'), 240000)[0]
        _, quotes = wire_generation_payload(payload(job))
        good, bad = question(cid='c1', stem='첫 판단'), question(cid='c2', stem='둘째 판단')
        good.update(unitId='one', evidence=[{'sourceId': 'study:c1:e1', 'quoteId': 'q1'}])
        bad.update(unitId='two', evidence=[{'sourceId': 'study:c2:e1', 'quoteId': 'q999'}])
        raw = {'questions': [good, bad], 'unfilled': 0, 'reason': ''}
        before = copy.deepcopy(raw)
        restored = resolve_generation_quotes(raw, quotes)
        self.assertEqual(raw, before)
        self.assertEqual(restored['questions'][1], bad)
        accepted, rejected = validate_job(restored, job, concepts, sources, set())
        self.assertEqual([q['unitId'] for q in accepted], ['one', 'two'])
        self.assertEqual(rejected, 0)
        self.assertTrue(accepted[1]['warnings'])
        self.assertEqual(accepted[1]['evidence'], [])

    def test_unknown_id_leaves_the_whole_question_unconverted(self):
        raw = {'questions': [{'evidence': [{'sourceId': 's1', 'quoteId': 'q1'},
                                          {'sourceId': 's2', 'quoteId': 'missing'}]}]}
        self.assertEqual(resolve_generation_quotes(raw, {('s1', 'q1'): '있는 원문'}), raw)
        raw['questions'][0]['evidence'][1] = {'sourceId': 'missing', 'quoteId': 'q1'}
        self.assertEqual(resolve_generation_quotes(raw, {('s1', 'q1'): '있는 원문'}), raw)

    def test_unknown_id_cannot_fall_back_to_a_mixed_legacy_quote(self):
        raw = {'questions': [{'evidence': [{'sourceId': 's1', 'quoteId': 'missing', 'quote': '있던 인용'}]}]}
        original = copy.deepcopy(raw)
        restored = resolve_generation_quotes(raw, {('s1', 'q1'): '있던 인용'})
        self.assertEqual(raw, original)
        self.assertNotIn('quote', restored['questions'][0]['evidence'][0])
        self.assertEqual(restored['questions'][0]['evidence'][0]['quoteId'], 'missing')

    def test_legacy_exact_quotes_and_malformed_envelopes_keep_existing_contracts(self):
        raw = {'questions': [{'evidence': [{'sourceId': 's1', 'quote': '정확한 기존 인용'}]}]}
        self.assertEqual(resolve_generation_quotes(raw, {}), raw)
        for value in (None, [], {'questions': None}, {'questions': [None, {'evidence': 'not a list'}]}):
            self.assertEqual(resolve_generation_quotes(value, {}), value)

    def test_valid_id_restores_the_original_not_a_model_retyped_quote(self):
        raw = {'questions': [{'evidence': [{'sourceId': 's1', 'quoteId': 'q1', 'quote': '모델의 재작성 오류'}]}]}
        restored = resolve_generation_quotes(raw, {('s1', 'q1'): '\\(정확한 원문\\)\n둘째 줄'})
        self.assertEqual(restored['questions'][0]['evidence'],
                         [{'sourceId': 's1', 'quote': '\\(정확한 원문\\)\n둘째 줄'}])

    def test_empty_text_remains_lossless_and_invalid_sources_fail_explicitly(self):
        wire, quotes = wire_generation_payload({'sources': [source('')]})
        self.assertEqual(wire['sources'][0]['quotes'], [])
        self.assertEqual(quotes, {})
        for payload in ({}, {'sources': None}, {'sources': [None]}, {'sources': [{'sourceId': '', 'text': 'x'}]},
                        {'sources': [{'sourceId': 's1', 'text': 1}]}):
            with self.assertRaises(ValueError):
                wire_generation_payload(payload)


if __name__ == '__main__':
    unittest.main()
