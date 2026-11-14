"""Offline checks for cheaper transport without cross-unit scope or quotas."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_quiz as quiz
import pdf_quiz_review as review
from pdf_quiz_transport import pack_generation_jobs, validate_job
from test_pdf_quiz import FakeProvider, fixture, planned, question
from test_pdf_quiz_review import approve, verdict


def unit(uid, ids, *, ox=1, mcq=0):
    return planned({'ox': ox, 'mcq': mcq, 'word': 0, 'essay': 0}, ids, uid)['allocations'][0]


def tagged(uid, cid='c1', *, kind='ox', stem=None):
    value = question(kind, cid, stem or uid + '의 조건 확인')
    value['unitId'] = uid
    return value


def reply(questions, unfilled=0, reason=''):
    return {'questions': questions, 'unfilled': unfilled, 'reason': reason}


class QuizTransportTests(unittest.TestCase):
    def setUp(self):
        document, request = fixture(5, size=4)
        self.config, self.outline, _, self.concepts, self.sources = quiz.context(document, request)
        self.prompt = '공유 지침'
        self.response_format = quiz._schema('questions')

    def pack(self, units, limit=240000):
        plan = {'allocations': units, 'unallocated': 0, 'reason': ''}

        def payload(assignment):
            return quiz.generation_payload(self.config, self.outline, plan, assignment,
                                           self.concepts, self.sources, [], 'transport-test')
        return pack_generation_jobs(units, payload, self.prompt, self.response_format, limit), payload

    def test_packing_preserves_targets_order_quotas_and_full_unique_sources(self):
        units = [unit('first', ['c1', 'c2'], ox=2), unit('second', ['c2', 'c3'], ox=0, mcq=1)]
        original = copy.deepcopy(units)
        self.sources['study:c2:e1']['text'] += '\n' + '본문 전체' * 3000
        jobs, payload = self.pack(units)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job['unitId'], 'transport-0')
        self.assertEqual(job['conceptIds'], ['c1', 'c2', 'c3'])
        self.assertEqual(job['counts'], {'ox': 2, 'mcq': 1, 'word': 0, 'essay': 0})
        self.assertEqual(job['focus'], '독립 배정은 units를 각각 준수한다.')
        self.assertEqual(job['units'], original)
        self.assertEqual(units, original)
        body = payload(job)
        ids = [source['sourceId'] for source in body['sources']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {sid for cid in job['conceptIds'] for sid in self.concepts[cid]['sourceIds']})
        self.assertEqual(next(s for s in body['sources'] if s['sourceId'] == 'study:c2:e1')['text'],
                         self.sources['study:c2:e1']['text'])

    def test_real_input_limit_keeps_single_units_without_truncation(self):
        units = [unit('one', ['c1']), unit('two', ['c2'])]
        for cid in ('c1', 'c2'):
            self.sources[f'study:{cid}:e1']['text'] += '\n' + cid * 3000
        packed, payload = self.pack(units)
        multi_bound = quiz.input_bound(payload(packed[0]), self.prompt, self.response_format)
        limit = multi_bound - 1
        for assignment in units:
            self.assertLessEqual(quiz.input_bound(payload(assignment), self.prompt, self.response_format), limit)
        jobs, _ = self.pack(units, limit)
        self.assertEqual(jobs, units)
        self.assertIs(jobs[0], units[0])
        self.assertIs(jobs[1], units[1])
        self.assertTrue(all('units' not in job for job in jobs))

    def test_output_limit_is_respected_even_when_sources_fit(self):
        half = quiz.MAX_BATCH_QUESTIONS // 2
        units = [unit('first', ['c1'], ox=half), unit('second', ['c2'], ox=half+1)]
        jobs, _ = self.pack(units)
        self.assertEqual(jobs, units)
        self.assertTrue(all(sum(job['counts'].values()) <= quiz.MAX_BATCH_QUESTIONS for job in jobs))

    def test_single_oversized_unit_is_not_silently_cut_or_sent(self):
        with self.assertRaisesRegex(ValueError, '먼저 분할'):
            self.pack([unit('too-large', ['c1'], ox=quiz.MAX_BATCH_QUESTIONS + 1)])
        with self.assertRaisesRegex(ValueError, '먼저 분할'):
            self.pack([unit('too-large', ['c1'])], limit=1)

    def test_empty_and_single_job_keep_legacy_validation_contract(self):
        self.assertEqual(self.pack([])[0], [])
        original = unit('legacy', ['c1'])
        jobs, _ = self.pack([original])
        self.assertIs(jobs[0], original)
        accepted, rejected = validate_job(reply([question()]), original, self.concepts, self.sources, set())
        self.assertEqual(rejected, 0)
        self.assertEqual(len(accepted), 1)

    def test_units_cannot_borrow_concepts_but_surplus_is_preserved(self):
        units = [unit('one', ['c1']), unit('two', ['c2'], ox=0, mcq=1)]
        job = self.pack(units)[0][0]
        raw = reply([tagged('two', 'c2', kind='mcq'),
                     tagged('one', 'c2', stem='다른 개념으로 범위 탈출'),
                     tagged('one', 'c1', kind='mcq', stem='다른 배정의 객관식 수량 사용'),
                     tagged('one', 'c1'), tagged('one', 'c1', stem='배정 초과')])
        accepted, rejected = validate_job(raw, job, self.concepts, self.sources, set())
        self.assertEqual([(q['unitId'], q['type'], q['conceptIds']) for q in accepted],
                         [('one', 'ox', ['c2']), ('one', 'mcq', ['c1']), ('one', 'ox', ['c1']), ('one', 'ox', ['c1']), ('two', 'mcq', ['c2'])])
        self.assertEqual(rejected, 0)

    def test_surplus_keeps_original_unit_identity(self):
        job = self.pack([unit('one', ['c1']), unit('two', ['c1'])])[0][0]
        raw = reply([tagged('one'), tagged('one', stem='첫 배정 초과'), tagged('two')])
        accepted, rejected = validate_job(raw, job, self.concepts, self.sources, set())
        self.assertEqual([q['unitId'] for q in accepted], ['one', 'one', 'two'])
        self.assertEqual(rejected, 0)

    def test_missing_and_unknown_unit_ids_never_use_the_union_scope(self):
        job = self.pack([unit('one', ['c1']), unit('two', ['c2'])])[0][0]
        raw = reply([question(), tagged('unknown'), tagged('one'), tagged('two', 'c2')])
        accepted, rejected = validate_job(raw, job, self.concepts, self.sources, set())
        self.assertEqual(len(accepted), 4)
        self.assertEqual(sum(bool(q.get('warnings')) for q in accepted), 2)
        self.assertEqual(rejected, 0)

    def test_stable_unit_order_keeps_cross_unit_duplicate_stems(self):
        job = self.pack([unit('one', ['c1']), unit('two', ['c2'])])[0][0]
        seen = {'이전 문제'}
        raw = reply([tagged('two', 'c2', stem='같은 판단'), tagged('one', stem='같은 판단')])
        accepted, rejected = validate_job(raw, job, self.concepts, self.sources, seen)
        self.assertEqual([q['unitId'] for q in accepted], ['one', 'two'])
        self.assertEqual(rejected, 0)
        self.assertEqual(seen, {'이전 문제'})

    def test_global_unfilled_is_checked_once_without_discarding_valid_items(self):
        job = self.pack([unit('one', ['c1']), unit('two', ['c2'])])[0][0]
        accepted, rejected = validate_job(reply([tagged('one')], unfilled=1, reason='한 배정 미생성'),
                                           job, self.concepts, self.sources, set())
        self.assertEqual((len(accepted), rejected), (1, 0))
        for raw in ({'unfilled': 0, 'reason': ''},):
            with self.assertRaises(ValueError):
                validate_job(raw, job, self.concepts, self.sources, set())


class QuizTransportIntegrationTests(unittest.TestCase):
    """Use the real packer, scheduler and local source/format checks."""

    def generate(self, generated=None, review_reply=approve):
        document, request = fixture(5, size=5)
        for page in document['pages']:
            page['nativeText'] = f"PDF 원문 {page['number']}의 정의와 조건이다."
        kinds = ['ox', 'mcq', 'word', 'essay', 'ox']
        units = []
        for index, kind in enumerate(kinds, 1):
            units.append({'unitId': f'unit-{index}', 'conceptIds': [f'c{index}'],
                          'counts': {k: int(k == kind) for k in quiz.TYPES},
                          'focus': f'개념 {index}의 고유 조건 판단'})
        plan = {'allocations': units, 'unallocated': 0, 'reason': ''}
        good = [tagged(a['unitId'], a['conceptIds'][0], kind=kind)
                for a, kind in zip(units, kinds)]
        all_questions = generated(good) if generated else good
        def answer(payload):
            assignment = payload['assignment']
            owned = {u['unitId'] for u in assignment.get('units', [assignment])}
            return reply([q for q in all_questions if q['unitId'] in owned])
        job_count = (len(units) + quiz.MAX_BATCH_QUESTIONS - 1) // quiz.MAX_BATCH_QUESTIONS
        provider = FakeProvider([plan, *([answer] * job_count), review_reply])
        captured, snapshots = {}, []
        real_write = quiz.write_json

        def write(path, value):
            if path.name == 'latest.json':
                snapshots.append(copy.deepcopy(value))
            return real_write(path, value)

        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'), \
                patch.object(quiz, 'write_json', side_effect=write):
            result = quiz.generate(Path(directory), document, request, provider)
            saved = json.loads((Path(directory) / 'generated/quiz-v2/latest.json').read_text())
        return result, provider, captured, units, snapshots, saved

    def test_five_logical_units_pack_within_limit_and_publish_without_review(self):
        result, provider, captured, units, snapshots, saved = self.generate()
        self.assertEqual([call[0]['task'] for call in provider.calls],
                         ['quiz_plan'] + ['quiz_questions'] * 2)
        self.assertEqual(len(result['executionAssignments']), 2)
        generations = [p for p, _, _ in provider.calls[1:]]
        assignments = [p['assignment'] for p in generations]
        self.assertCountEqual([u for a in assignments for u in a.get('units', [a])], units)
        self.assertTrue(all(sum(a['counts'].values()) <= quiz.MAX_BATCH_QUESTIONS for a in assignments))
        source_ids = [s['sourceId'] for generation in generations for s in generation['sources']]
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(len(source_ids), 10)
        for index in range(1, 6):
            self.assertEqual(sum(p['text'].count(f'핵심 정의 {index}')
                                 for generation in generations for s in generation['sources'] for p in s['quotes']), 1)
        self.assertEqual(len(result['questions']), 5)
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual((result['quality']['status'], result['quality']['calls']), ('disabled', 0))
        self.assertEqual(result['runUsage']['usageBasedUsd'], .03)
        self.assertEqual(result['runUsage']['byKind']['quiz_questions']['requests'], 2)
        self.assertEqual(result['runUsage']['byKind']['quiz_review']['requests'], 0)
        self.assertEqual(saved['questions'], result['questions'])
        self.assertTrue(any(len(s['questions']) == 5 for s in snapshots))
        self.assertTrue(all(not s['candidateQuestions'] for s in snapshots))

    def test_packed_generation_warns_about_cross_unit_concepts_without_dropping_items(self):
        def corrupted(good):
            good[0]['conceptIds'] = ['c1', 'c2']
            good[2] = tagged('unit-3', 'c3', kind='mcq', stem='다른 단위의 형식 수량을 빌린 문항')
            return good
        result, provider, captured, _, _, _ = self.generate(corrupted)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual({q['unitId'] for q in result['questions']}, {'unit-1', 'unit-2', 'unit-3', 'unit-4', 'unit-5'})
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(result['quality']['reviewed'], 0)
        self.assertEqual(sum(len(a['issues']) for a in result['generationAudit']), 1)

    def test_independent_reviewer_is_not_called_or_allowed_to_remove_questions(self):
        def forbidden_review(payload):
            self.fail('Independent reviewer must never be called')

        result, provider, _, _, _, _ = self.generate(review_reply=forbidden_review)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(result['candidateQuestions'], [])
        self.assertEqual(len(result['questions']), 5)
        self.assertEqual((result['unfilled'], result['quality']['rejected']), (0, 0))


if __name__ == '__main__':
    unittest.main()
