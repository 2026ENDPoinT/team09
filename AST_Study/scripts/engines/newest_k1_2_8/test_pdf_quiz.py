"""Offline contracts for explicit, source-scoped two-stage quiz generation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import sys
import threading
from unittest.mock import patch

import pdf_quiz as quiz
import pdf_ai
from pdf_ai import BudgetExceeded


def fixture(count=3, allowed=None, size=2):
    document = {'documentId': 'doc', 'fingerprint': 'fp',
                'pages': [{'number': i} for i in range(1, size + 1)],
                'chunks': [{'id': f's{i}', 'text': f'원문 근거 {i}', 'page': i, 'source': 'native'}
                           for i in range(1, size + 1)]}
    cards = [{'name': f'개념 {i}', 'entries': [{'definition': f'핵심 정의 {i}',
               'explanation': f'핵심 설명 {i}', 'easyExplanation': '비유는 출제하면 안 돼요',
               'evidence': [{'sourceId': f's{i}', 'page': i}],
               'standardKnowledgeUsed': i == 1}]} for i in range(1, size + 1)]
    request = {'quiz': {'theme': 'understanding', 'totalCount': count, 'difficulty': '중',
                       'allowedTypes': allowed or ['ox', 'mcq', 'word', 'essay'], 'instructions': ''},
               'studyContent': {'documentId': 'doc', 'sourceFingerprint': 'fp', 'concepts': cards},
               'studyGroups': [{'id': 'g', 'title': '상위 제목', 'conceptIndexes': list(range(size)),
                                'path': [{'id': 'h', 'title': '실제 상위 제목'}]}],
               'startPage': 1, 'endPage': size}
    return document, request


def planned(counts=None, ids=None, uid='u1', unallocated=0):
    return {'allocations': [{'unitId': uid, 'conceptIds': ids or ['c1', 'c2'],
                            'counts': counts or {'ox': 1, 'mcq': 1, 'word': 1, 'essay': 0},
                            'focus': '조건 비교'}], 'unallocated': unallocated, 'reason': ''}


def question(kind='ox', cid='c1', stem='옳은 명제인가?', source=None):
    return {'type': kind, 'conceptIds': [cid], 'stem': stem,
            'options': [{'id': t, 'text': '선지 ' + t, 'explanation': '판단 이유 ' + t} for t in 'ABCD'] if kind == 'mcq' else [],
            'answer': {'ox': 'O', 'mcq': 'A', 'word': '용어', 'essay': '모범 답안'}[kind],
            'explanation': '핵심 조건으로 설명한다.', 'keyPoints': ['핵심 조건'] if kind == 'essay' else [],
            'evidence': [{'sourceId': source or f'study:{cid}:e1', 'quote': '핵심 정의 ' + cid[1:]}]}


class FakeProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
        self._lock = threading.RLock()
        self._thread_context = threading.local()
        self._generation_replies = []
        self.context = {}
        self.ledger = {'requests': []}
        self.billing = None

    @property
    def context(self):
        return getattr(self._thread_context, 'value', {})

    @context.setter
    def context(self, value):
        self._thread_context.value = value

    def complete(self, payload, **options):
        with self._lock:
            self.calls.append((copy.deepcopy(payload), copy.deepcopy(options), dict(self.context)))
            self.ledger['requests'].append({'state': 'settled', 'estimatedUsd': .01,
                                           'kind': self.context.get('kind'),
                                           'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})
            index = self.context.get('quizAssignmentIndex')
            if index is not None:
                while len(self._generation_replies) <= index:
                    self._generation_replies.append(next(self.replies))
                reply = self._generation_replies[index]
            else:
                self._generation_replies.clear()
                reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply(payload) if callable(reply) else copy.deepcopy(reply)


def review_passthrough(folder, document, config, candidates, concepts, sources, provider,
                       assignment_by_id, previous_stems, **unused):
    """Isolate generation contracts from the independently tested review stage."""
    return candidates, {'status': 'passed', 'reviewed': len(candidates),
                        'accepted': len(candidates), 'revised': 0, 'rejected': 0, 'calls': 0}


class QuizGenerationTests(unittest.TestCase):
    def setUp(self):
        review_patch = patch.object(quiz, 'review_candidates', side_effect=review_passthrough, create=True)
        self.review = review_patch.start()
        self.addCleanup(review_patch.stop)
        transport_patch = patch.object(quiz, 'pack_generation_jobs', side_effect=lambda assignments, *unused: assignments)
        transport_patch.start()
        self.addCleanup(transport_patch.stop)
        wire_patch = patch.object(quiz, 'wire_generation_payload', side_effect=lambda payload: (payload, {}))
        wire_patch.start()
        self.addCleanup(wire_patch.stop)
    def test_persisted_questions_published_before_generation_finishes(self):
        document, request = fixture(2)
        plan = planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 1}, ids=['c1'])
        provider = FakeProvider([plan, {'questions': [question(), question('essay', stem='이유를 설명하라.')],
                                      'unfilled': 0, 'reason': ''}])
        published=[]
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            def receive(event, **fields):
                live=fields.get('workbook')
                if live:
                    persisted=json.loads((folder/'generated/quiz-v2/runs'/(live['quizRunId']+'.json')).read_text())
                    self.assertEqual(live['questions'],persisted['questions'])
                    self.assertEqual(len(live['questions'])+live['unfilled'],live['requestedCount'])
                    published.append(live)
            with patch.object(quiz,'emit',side_effect=receive):
                result=quiz.generate(folder,document,request,provider)
        self.assertTrue(published)
        self.assertEqual(published[-1]['quizRunId'],result['quizRunId'])
        self.assertEqual(published[-1]['questions'],result['questions'])

    def test_evidence_planner_then_selected_sources_once_and_shared_prompt(self):
        document, request = fixture(2)
        plan = planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 1}, ids=['c1'])
        provider = FakeProvider([plan, {'questions': [question(), question('essay', stem='이유를 설명하라.')],
                                      'unfilled': 0, 'reason': ''}])
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(quiz, 'emit'):
                result = quiz.generate(Path(directory), document, request, provider)
            saved = json.loads((Path(directory) / 'generated/quiz-v2/latest.json').read_text())
        self.assertEqual(len(provider.calls), 2)
        planning, generation = provider.calls
        planning_text = json.dumps(planning[0], ensure_ascii=False)
        self.assertIn('핵심 정의', planning_text)
        self.assertIn('planningEvidence', planning[0])
        self.assertNotIn('핵심 정의', json.dumps(planning[0]['catalog'], ensure_ascii=False))
        self.assertIn('개념 2', planning_text)
        self.assertEqual(generation[0]['concepts'], [{'id': 'c1', 'title': '개념 1', 'sourceIds': ['study:c1:e1', 's1']}])
        self.assertEqual({s['sourceId'] for s in generation[0]['sources']}, {'study:c1:e1', 's1'})
        serialized = json.dumps(generation[0], ensure_ascii=False)
        self.assertEqual(serialized.count('핵심 정의 1'), 1)
        self.assertNotIn('비유는 출제', serialized)
        self.assertNotIn('핵심 정의 2', serialized)
        prompt = generation[1]['system_prompt']
        common = (quiz.PROMPTS / 'common.md').read_text().strip()
        self.assertEqual(prompt.count(common), 1)
        quality = (quiz.PROMPTS / 'quality.md').read_text().strip()
        self.assertEqual(prompt.count(quality), 1)
        self.assertEqual(prompt.count((quiz.PROMPTS / 'understanding.md').read_text().strip()), 1)
        self.assertNotIn((quiz.PROMPTS / 'recall.md').read_text().strip(), prompt)
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(result['runUsage']['usageBasedUsd'], .02)
        self.assertEqual(saved['questions'], result['questions'])
        evidence = result['questions'][0]['evidence'][0]
        self.assertEqual((evidence['page'], evidence['sourceKind'], evidence['originalSourceIds']), (1, 'saved_concept', ['s1']))
        self.assertTrue(evidence['standardKnowledgeUsed'])

    def test_context_preserves_groups_without_fixed_cap_and_keeps_full_outline(self):
        document, request = fixture(2, size=9)
        request['studyGroups'] = [{'id': 'first', 'title': '첫 단원', 'conceptIndexes': [0, 1]},
                                 {'id': 'second', 'title': '둘째 단원', 'conceptIndexes': list(range(2, 9))}]
        _, outline, catalog, _, _ = quiz.context(document, request)
        self.assertEqual(len(catalog), 9)
        self.assertEqual([len(g['concepts']) for g in outline], [2, 7])
        self.assertEqual([g['title'] for g in outline], ['첫 단원', '둘째 단원'])
        request['startPage'], request['endPage'] = 5, 6
        _, outline, catalog, _, _ = quiz.context(document, request)
        self.assertEqual(sum(len(g['concepts']) for g in outline), 9)
        self.assertEqual([c['id'] for c in catalog], ['c5', 'c6'])

    def test_planner_combines_small_related_sections_and_keeps_more_than_four_concepts(self):
        document, request = fixture(8, ['ox'], size=8)
        request['studyGroups'] = [{'id': str(i), 'title': '관련 소단락 ' + str(i), 'conceptIndexes': [i]}
                                 for i in range(8)]
        plan = planned({'ox': 8, 'mcq': 0, 'word': 0, 'essay': 0},
                       ['c' + str(i) for i in range(1, 9)], uid='combined-by-planner')
        generated = [question(cid='c' + str(i), stem='서로 연결된 명제 ' + str(i)) for i in range(1, 9)]
        replies = [{'questions': generated[start:start+quiz.MAX_BATCH_QUESTIONS], 'unfilled': 0, 'reason': ''}
                   for start in range(0, len(generated), quiz.MAX_BATCH_QUESTIONS)]
        provider = FakeProvider([plan, *replies])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(len(provider.calls), 1 + len(replies))
        self.assertEqual(len(provider.calls[0][0]['catalog']), 8)
        self.assertEqual(len(provider.calls[1][0]['concepts']), 8)
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(len(result['executionAssignments']), len(replies))

    def test_real_input_limit_splits_without_truncating_source(self):
        document, request = fixture(4, ['ox'], size=4)
        for card in request['studyContent']['concepts']:
            card['entries'][0]['explanation'] = '完整본문' * 3000
        config, outline, _, concepts, sources = quiz.context(document, request)
        plan = planned({'ox': 4, 'mcq': 0, 'word': 0, 'essay': 0}, ['c1', 'c2', 'c3', 'c4'])
        assignment = plan['allocations'][0]
        prompt = '\n\n'.join((quiz.PROMPTS / n).read_text().strip() for n in ('common.md', 'quality.md', 'understanding.md'))
        prompt += '\n\n' + quiz.difficulty_instruction(config['difficulty'], config['allowedTypes'], config['theme'])
        full = quiz.generation_payload(config, outline, plan, assignment, concepts, sources, [], 'x' * 32)
        child = quiz.generation_payload(config, outline, plan,
                                       {**assignment, 'conceptIds': ['c1', 'c2']}, concepts, sources, [], 'x' * 32)
        limit = (quiz.input_bound(full, prompt, quiz._schema('questions'))
                 + quiz.input_bound(child, prompt, quiz._schema('questions'))) // 2
        def answer(payload):
            ids = payload['assignment']['conceptIds']
            count = sum(payload['assignment']['counts'].values())
            return {'questions': [question(cid=ids[i % len(ids)], stem='한도분할 명제 ' + ids[i % len(ids)] + str(i))
                                  for i in range(count)], 'unfilled': 0, 'reason': ''}
        provider = FakeProvider([plan, answer, answer])
        provider.input_bound_limit = limit
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(result['unfilled'], 0)
        for payload, options, _ in provider.calls[1:]:
            self.assertLessEqual(quiz.input_bound(payload, options['system_prompt'], options['response_format']), limit)
            saved_sources = [s for s in payload['sources'] if s['sourceKind'] == 'saved_concept']
            self.assertTrue(all(s['text'].endswith('完整본문' * 3000) for s in saved_sources))

    def test_parallel_calls_fit_with_one_fixed_previous_target_snapshot(self):
        document, request = fixture(4, ['ox'], size=3)
        for card in request['studyContent']['concepts'][1:]:
            card['entries'][0]['explanation'] = '긴본문' * 1000
        first = planned({'ox': 2, 'mcq': 0, 'word': 0, 'essay': 0}, ['c1'])['allocations'][0]
        second = planned({'ox': 2, 'mcq': 0, 'word': 0, 'essay': 0}, ['c2', 'c3'], 'next')['allocations'][0]
        plan = {'allocations': [first, second], 'unallocated': 0, 'reason': ''}
        config, outline, _, concepts, sources = quiz.context(document, request)
        prompt = '\n\n'.join((quiz.PROMPTS / n).read_text().strip() for n in ('common.md', 'quality.md', 'understanding.md'))
        prompt += '\n\n' + quiz.difficulty_instruction(config['difficulty'], config['allowedTypes'], config['theme'])
        payload = quiz.generation_payload(config, outline, plan, second, concepts, sources, [], 'x' * 32)
        limit = quiz.input_bound(payload, prompt, quiz._schema('questions')) + 40
        def answer(payload):
            ids = payload['assignment']['conceptIds']
            count = sum(payload['assignment']['counts'].values())
            return {'questions': [question(cid=ids[0], stem=('추가문맥' * 30) + ids[0] + str(i)) for i in range(count)],
                    'unfilled': 0, 'reason': ''}
        provider = FakeProvider([plan, answer, answer])
        provider.input_bound_limit = limit
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(result['unfilled'], 0)
        for payload, options, _ in provider.calls[1:]:
            self.assertLessEqual(quiz.input_bound(payload, options['system_prompt'], options['response_format']), limit)
            self.assertEqual(payload['previousTargets'], [])
            self.assertNotIn('totalCount', payload['request'])

    def test_unknown_page_only_in_whole_scope_and_native_fallback(self):
        document, request = fixture(1)
        for card in request['studyContent']['concepts']:
            card['entries'][0]['evidence'][0].pop('page')
        _, _, catalog, _, sources = quiz.context(document, request)
        self.assertEqual(sources['study:c1:e1']['pages'], [1])
        request['studyContent']['concepts'][1]['entries'][0]['evidence'] = []
        request['startPage'] = request['endPage'] = 1
        _, outline, catalog, _, _ = quiz.context(document, request)
        self.assertEqual([c['id'] for c in catalog], ['c1'])
        self.assertEqual(len(outline[0]['concepts']), 2)

    def test_legacy_fingerprint_and_visual_pages(self):
        document, request = fixture(1)
        document['legacySourceFingerprints'] = ['old']
        request['studyContent']['sourceFingerprint'] = 'old'
        entry = request['studyContent']['concepts'][0]['entries'][0]
        entry['evidence'] = [{'sourceId': 'visual-region'}]
        entry['visualPages'] = [1]
        _, _, _, _, sources = quiz.context(document, request)
        self.assertEqual(sources['study:c1:e1']['pages'], [1])

    def test_source_page_prefers_the_selected_scope_without_cutting_body(self):
        document, request = fixture(1, ['ox'], size=6)
        entry = request['studyContent']['concepts'][0]['entries'][0]
        entry['evidence'] = [{'sourceId': 'figure-one', 'page': 1}, {'sourceId': 'figure-six', 'page': 6}]
        request['startPage'] = request['endPage'] = 6
        _, _, _, _, sources = quiz.context(document, request)
        self.assertEqual(sources['study:c1:e1']['pages'], [6, 1])
        self.assertIn('핵심 설명 1', sources['study:c1:e1']['text'])

    def test_invalid_input_makes_no_call(self):
        for field, value in [('totalCount', 0), ('totalCount', True), ('allowedTypes', []), ('difficulty', '쉬움')]:
            document, request = fixture()
            request['quiz'][field] = value
            provider = FakeProvider([])
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    quiz.generate(Path(directory), document, request, provider)
            self.assertFalse(provider.calls)

    def test_bad_plan_stops_before_generation_and_keeps_planning_charge(self):
        for bad in [planned(ids=['foreign']), planned(uid=''), planned(unallocated=1),
                    planned({'ox': 2, 'mcq': 0, 'word': 1, 'essay': 0})]:
            document, request = fixture(3, ['mcq', 'word'])
            provider = FakeProvider([bad])
            with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
                result = quiz.generate(Path(directory), document, request, provider)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(result['unfilled'], 3)
            self.assertEqual(result['runUsage']['usageBasedUsd'], .01)
            self.assertTrue(result['reason'])

    def test_invalid_quote_or_foreign_concept_shown_without_paid_retry(self):
        document, request = fixture()
        wrong_quote, wrong_concept = question('mcq'), question('word')
        wrong_quote['evidence'][0]['quote'] = '자료에 없는 주장'
        wrong_concept['conceptIds'] = ['foreign']
        provider = FakeProvider([planned(), {'questions': [question(), wrong_quote, wrong_concept],
                                            'unfilled': 0, 'reason': ''}])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(result['questions']), 3)
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(sum(bool(q.get('warnings')) for q in result['questions']), 2)

    def test_budget_stop_preserves_unchecked_candidates_and_all_attempt_costs(self):
        count = quiz.MAX_BATCH_QUESTIONS + 1
        document, request = fixture(count, ['ox'])
        first = [question(stem='명제 ' + str(i)) for i in range(count-1)]
        provider = FakeProvider([planned({'ox': count, 'mcq': 0, 'word': 0, 'essay': 0}),
                                 {'questions': first, 'unfilled': 0, 'reason': ''}, BudgetExceeded('budget')])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual((len(result['questions']), result['unfilled']), (count-1, 1))
        self.assertFalse(result['candidateQuestions'])
        self.review.assert_not_called()
        self.assertEqual(result['runUsage']['usageBasedUsd'], .03)
        self.assertIn('한도', result['reason'])

    def test_mid_generation_error_continues_other_units_without_retry(self):
        document, request = fixture(2, ['ox'], size=5)
        plan = {'allocations': [planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0}, ['c1'])['allocations'][0],
                               planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0}, ['c5'], 'u2')['allocations'][0]],
                'unallocated': 0, 'reason': ''}
        provider = FakeProvider([plan, RuntimeError('failed'),
                                 {'questions': [question(cid='c5')], 'unfilled': 0, 'reason': ''}])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(result['unfilled'], 1)
        self.assertEqual(result['questions'][0]['conceptIds'], ['c5'])

    def test_unknown_usage_is_not_counted_as_zero_complete_cost(self):
        document, request = fixture(1, ['ox'])
        provider = FakeProvider([planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0})])
        def failure(payload):
            provider.ledger['requests'][-1].update(state='usage_unknown', reservedUsd=.02)
            raise RuntimeError('connection lost')
        provider.replies = iter([failure])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(result['runUsage']['unknownUsageRequests'], 1)
        self.assertEqual(result['runUsage']['uncertainReservedUsd'], .02)

    def test_repeat_run_has_nonce_and_uses_previous_targets_only_as_metadata(self):
        document, request = fixture(1, ['ox'])
        plan = planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0})
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            one = FakeProvider([plan, {'questions': [question()], 'unfilled': 0, 'reason': ''}])
            first = quiz.generate(Path(directory), document, request, one)
            two = FakeProvider([plan, {'questions': [question()], 'unfilled': 0, 'reason': ''}])
            second = quiz.generate(Path(directory), document, request, two)
            saved = json.loads((Path(directory) / 'generated/quiz-v2/latest.json').read_text())
            attempted = json.loads((Path(directory) / 'generated/quiz-v2/last-attempt.json').read_text())
        self.assertNotEqual(one.calls[1][0]['requestId'], two.calls[1][0]['requestId'])
        self.assertTrue(two.calls[0][0]['previousTargets'])
        self.assertEqual(second['unfilled'], 0)
        self.assertEqual(first['unfilled'], 0)
        self.assertEqual(saved['questions'], second['questions'])
        self.assertEqual(attempted['questions'], second['questions'])
        self.assertEqual(attempted['runUsage']['usageBasedUsd'], .02)
        self.assertFalse(any(s.get('sourceKind') == 'previous_question' for s in two.calls[1][0]['sources']))

    def test_cancel_retains_usage_and_result(self):
        document, request = fixture(1, ['ox'])
        provider = FakeProvider([planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0})])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'), \
                patch.object(quiz, 'check_cancel', side_effect=[None, InterruptedError('cancel')]):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['runUsage']['usageBasedUsd'], .01)

    def test_main_quiz_route_uses_existing_provider_and_does_not_rewrite_document(self):
        document, request = fixture(1, ['ox'])
        provider = FakeProvider([planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0}),
                                 {'questions': [question()], 'unfilled': 0, 'reason': ''}])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            request_file = folder / 'request.json'
            request_file.write_text(json.dumps(request))
            args = ['pdf_ai.py', 'quiz', '--folder', directory, '--request', str(request_file),
                    '--allow-remote', '--max-usd', '1']
            with patch.object(sys, 'argv', args), patch.object(pdf_ai, 'Provider', return_value=provider), \
                    patch.object(pdf_ai, 'load_tutor_document', return_value=document), \
                    patch.object(pdf_ai, 'emit'), patch.object(quiz, 'emit'):
                pdf_ai.main()
            result = json.loads(request_file.with_suffix('.result.json').read_text())
            self.assertEqual(result['unfilled'], 0)
            self.assertFalse((folder / 'document.json').exists())


if __name__ == '__main__':
    unittest.main()
