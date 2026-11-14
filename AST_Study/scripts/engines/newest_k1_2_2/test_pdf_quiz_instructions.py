"""Offline request/prompt continuity through the actual planner and packer.

Fake model answers exercise transport and call counts, not semantic model adherence.
No network, real library data or wallet is used.
"""
from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_quiz as quiz
from pdf_quiz_sources import wire_generation_payload
from test_pdf_quiz import fixture, planned
from test_pdf_quiz_direct_completion import answers
from test_pdf_quiz_parallel import ConcurrentProvider


def wire_answers(payload):
    reply = answers(payload)
    sources = {source['sourceId']: source for source in payload['sources']}
    for question in reply['questions']:
        sid = question['evidence'][0]['sourceId']
        question['evidence'] = [{'sourceId': sid, 'quoteId': sources[sid]['quotes'][0]['quoteId']}]
    return reply


class QuizInstructionFlowTests(unittest.TestCase):
    def run_request(self, document, request, plan, answer=wire_answers, *, limit=None):
        original = copy.deepcopy(request)
        provider = ConcurrentProvider(plan, answer)
        if limit is not None:
            provider.input_bound_limit = limit
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'), \
                patch('socket.socket.connect', side_effect=AssertionError('offline test attempted network')):
            output = quiz.generate(Path(directory), document, request, provider)
            saved = json.loads((Path(directory) / 'generated/quiz-v2/latest.json').read_text())
        self.assertEqual(request, original)
        self.assertEqual(saved['questions'], output['questions'])
        self.assertEqual(saved['quiz']['instructions'], request['quiz']['instructions'].strip())
        self.assertEqual(output['quality']['status'], 'disabled')
        self.assertEqual(output['runUsage']['byKind']['quiz_review']['requests'], 0)
        self.assertEqual(sum(p['task'] == 'quiz_plan' for p, _, _ in provider.calls), 1)
        for payload, options, _ in provider.calls:
            self.assertIn(payload['task'], ('quiz_plan', 'quiz_questions'))
            self.assertEqual(payload['request']['instructions'], request['quiz']['instructions'].strip())
            self.assertTrue(options['response_format']['json_schema']['strict'])
            if request['quiz']['instructions']:
                self.assertNotIn(request['quiz']['instructions'].strip(), options['system_prompt'])
            if payload['task'] == 'quiz_questions':
                # This call owns only its assignment; the original prose may mention a whole-set ratio.
                self.assertNotIn('totalCount', payload['request'])
                self.assertNotIn('typeCounts', payload['request'])
        self.assertFalse(output['errors'], output['errors'])
        return output, provider.calls

    def test_every_theme_keeps_request_and_existing_two_call_flow(self):
        for theme in quiz.THEMES:
            with self.subTest(theme=theme):
                document, request = fixture(4)
                request['quiz'].update(theme=theme, instructions='  개념 1과 2의 차이 위주로, 해설은 짧게 써 주세요.\n수식 a_n은 유지해 주세요.  ')
                plan = planned({'ox': 1, 'mcq': 1, 'word': 1, 'essay': 1})
                plan['allocations'][0]['focus'] = '개념 1과 2를 구별하는 조건 비교'
                output, calls = self.run_request(document, request, plan)
                self.assertEqual((len(output['questions']), len(calls)), (4, 2))
                self.assertIn('request.instructions', calls[0][1]['system_prompt'])
                self.assertIn((quiz.PROMPTS / quiz.THEMES[theme]).read_text().strip(), calls[1][1]['system_prompt'])

    def test_packed_units_share_one_request_without_losing_individual_focus(self):
        document, request = fixture(3, ['ox'], size=3)
        request['quiz']['instructions'] = '각 개념의 적용 조건을 비교하고 해설은 두 문장으로 써 주세요.'
        units = []
        for index in range(1, 4):
            unit = planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0}, [f'c{index}'], f'u{index}')['allocations'][0]
            unit['focus'] = f'개념 {index}의 적용 조건 비교'
            units.append(unit)
        output, calls = self.run_request(document, request, {'allocations': units, 'unallocated': 0, 'reason': ''})
        self.assertEqual((len(output['questions']), len(calls)), (3, 2))
        self.assertEqual(calls[1][0]['assignment']['units'], units)

    def test_count_splitting_retains_request_and_whole_set_type_ratio(self):
        document, request = fixture(20, ['ox', 'essay'])
        request['quiz']['instructions'] = '개념 1만 출제하고 OX와 서술형을 절반씩, 해설은 간결하게 써 주세요.'
        counts = {'ox': 10, 'mcq': 0, 'word': 0, 'essay': 10}
        plan = planned(counts, ['c1'])
        plan['allocations'][0]['focus'] = '개념 1의 성립 조건 판별'
        output, calls = self.run_request(document, request, plan)
        self.assertEqual(Counter(q['type'] for q in output['questions']), {'ox': 10, 'essay': 10})
        self.assertEqual(len(calls), 1 + (20 + quiz.MAX_BATCH_QUESTIONS - 1) // quiz.MAX_BATCH_QUESTIONS)
        for payload, _, _ in calls[1:]:
            self.assertEqual(payload['assignment']['focus'], plan['allocations'][0]['focus'])
            self.assertEqual(payload['assignment']['conceptIds'], ['c1'])
            self.assertLessEqual(sum(payload['assignment']['counts'].values()), quiz.MAX_BATCH_QUESTIONS)

    def test_context_splitting_preserves_request_and_focus_without_truncating_sources(self):
        document, request = fixture(2, ['ox'])
        request['quiz']['instructions'] = '각 개념의 조건을 바꾸었을 때 결과가 달라지는지 물어보세요.'
        for card in request['studyContent']['concepts']:
            card['entries'][0]['explanation'] = ('조건과 적용 범위를 비교한다.\n' * 140)
        plan = planned({'ox': 2, 'mcq': 0, 'word': 0, 'essay': 0})
        plan['allocations'][0]['focus'] = '조건 변화에 따른 결과 비교'
        config, outline, _, concepts, sources = quiz.context(document, request)
        raw = quiz.generation_payload(config, outline, plan, plan['allocations'][0], concepts, sources, [], '0' * 32)
        prompt = '\n\n'.join((quiz.PROMPTS / name).read_text().strip()
                             for name in ('common.md', 'quality.md', quiz.THEMES[config['theme']]))
        limit = quiz.input_bound(wire_generation_payload(raw)[0], prompt, quiz._schema('questions')) - 1
        output, calls = self.run_request(document, request, plan, limit=limit)
        self.assertEqual((len(output['questions']), len(calls)), (2, 3))
        sent_sources = {}
        for payload, _, _ in calls[1:]:
            self.assertEqual(payload['assignment']['focus'], plan['allocations'][0]['focus'])
            for source in payload['sources']:
                sent_sources[source['sourceId']] = ''.join(q['text'] for q in source['quotes'])
        self.assertEqual(sent_sources, {sid: source['text'] for sid, source in sources.items()})

    def test_short_response_keeps_original_request_without_topups(self):
        document, request = fixture(4, ['ox'])
        request['quiz']['instructions'] = '정의 암기보다 조건 비교 위주로 내고 해설은 두 문장으로 써 주세요.'
        units = [planned({'ox': 2, 'mcq': 0, 'word': 0, 'essay': 0}, [f'c{i}'], f'u{i}')['allocations'][0]
                 for i in (1, 2)]
        for unit in units:
            unit['focus'] = unit['conceptIds'][0] + '의 조건 비교'

        def answer(payload):
            round_number = payload.get('completion', {}).get('round', 0)
            if not round_number:
                first = copy.deepcopy(payload)
                first['assignment'] = payload['assignment']['units'][0]
                return wire_answers(first)
            if round_number == 1:
                return {'questions': [], 'unfilled': 2, 'reason': '보충 경로 확인용 미생성'}
            return wire_answers(payload)

        output, calls = self.run_request(document, request, {'allocations': units, 'unallocated': 0, 'reason': ''}, answer)
        self.assertEqual((len(output['questions']), len(calls), output['refillRounds']), (2, 2, 0))
        self.assertFalse(any('completion' in p for p, _, _ in calls))

    def test_empty_request_preserves_default_flow(self):
        document, request = fixture(1, ['ox'])
        output, calls = self.run_request(document, request, planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0}, ['c1']))
        self.assertEqual((len(output['questions']), len(calls), output['refillRounds']), (1, 2, 0))


if __name__ == '__main__':
    unittest.main()
