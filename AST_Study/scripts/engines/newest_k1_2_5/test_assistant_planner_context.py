"""Offline interval/protocol cases; no API, app UI, wallet, or real planner data."""
import copy
import unittest
from assistant_planner_context import analyze, validate_request, PlannerContext
from assistant_protocol import run, validate_envelope, FORMAT
from home_assistant import SYSTEM, MAX_OUTPUT, chat, DOCUMENT
from pdf_ai import AiResponseError
from test_assistant_protocol import Host, Model, final, tools, action

NOW = {'localDateTime': '2026-10-26T01:54:00+09:00[Asia/Seoul]', 'timezone': 'Asia/Seoul'}


def plan(purpose='advice', start='2026-10-26', end='2026-10-27', kinds=None):
    return {'purpose': purpose, 'goal': '지금부터 몇 시까지 공부할까?', 'from': start,
            'to': end, 'kinds': kinds or ['event']}


def need(value=None, premature=False):
    response = final('조회 전에 추측한 답변이에요.') if premature else tools()
    response['plannerContextRequest'] = value or plan()
    return response


def event(identifier, occurrence_start, occurrence_end, **fields):
    return {'entity': 'event', 'id': identifier, 'title': identifier,
            'occurrenceStart': occurrence_start, 'occurrenceEnd': occurrence_end, **fields}


EXAMS = [event('프입 시험', '2026-10-26T10:00', '2026-10-26T10:50'),
         event('금융 시험', '2026-10-26T15:00', '2026-10-26T18:00')]


class PlannerHost(Host):
    def __init__(self, rows=None):
        super().__init__()
        self.rows = copy.deepcopy(EXAMS if rows is None else rows)

    def __call__(self, tool, args, quote):
        if tool == 'planner.query':
            self.calls.append((tool, copy.deepcopy(args), quote))
            return {'ok': True, 'data': {'revision': self.context['plannerAccess']['revision'],
                    'from': args['from'], 'to': args['to'], 'items': copy.deepcopy(self.rows), 'hasMore': False}}
        return super().__call__(tool, args, quote)


class TimeAnalysisTests(unittest.TestCase):
    def test_gap_uses_end_time_and_registered_appointments(self):
        analysis = analyze(EXAMS, plan(), NOW)
        day = analysis['days'][0]
        self.assertEqual(2, day['eventCount'])
        self.assertEqual([{'start': '2026-10-26T10:50', 'end': '2026-10-26T15:00', 'minutes': 250}], day['gapsBetweenAppointments'])
        self.assertTrue(day['availabilityCertain'])
        self.assertIn('unknown', analysis['interpretation'])

    def test_overlap_merge_and_past_windows_are_excluded(self):
        rows = EXAMS+[event('약속', '2026-10-26T12:00', '2026-10-26T13:00'),
                      event('겹친 약속', '2026-10-26T12:30', '2026-10-26T13:30')]
        day = analyze(rows, plan(), {**NOW, 'localDateTime': '2026-10-26T11:30:00+09:00'})['days'][0]
        self.assertEqual([70, 90], [gap['minutes'] for gap in day['gapsBetweenAppointments']])
        self.assertEqual('2026-10-26T11:30', day['unbookedWindowsFromNow'][0]['start'])
        self.assertEqual(3, len(day['busyIntervals']))
        self.assertEqual('past', day['events'][0]['status'])

    def test_native_occurrence_and_cross_midnight_are_used(self):
        row = event('반복 야간 일정', '2026-10-25T23:30', '2026-10-26T01:00',
                    start='2026-01-01T23:30', end='2026-01-02T01:00', repeat='DAILY')
        day = analyze([row]+EXAMS, plan(), NOW)['days'][0]
        self.assertEqual('2026-10-26T00:00', day['busyIntervals'][0]['start'])
        self.assertEqual(60, day['busyIntervals'][0]['minutes'])
        self.assertTrue(all(window['start'] >= '2026-10-26T01:54' for window in day['unbookedWindowsFromNow']))

    def test_all_day_and_missing_times_do_not_claim_confirmed_availability(self):
        all_day = event('시간 미정', '2026-10-26T00:00', '2026-10-27T00:00', allDay=True)
        day = analyze(EXAMS+[all_day], plan(), NOW)['days'][0]
        self.assertFalse(day['availabilityCertain'])
        self.assertEqual(['시간 미정'], day['allDayConstraints'])
        broken = analyze(EXAMS+[{'entity': 'event', 'id': 'broken', 'title': '시각 없음'}], plan(), NOW)
        self.assertIsNone(broken['days'][0]['eventCount'])
        self.assertEqual([], broken['days'][0]['unbookedWindowsFromNow'])
        self.assertEqual([], broken['days'][0]['gapsBetweenAppointments'])

    def test_completed_tasks_and_outside_cached_scope_do_not_become_study_time(self):
        tasks = [{'entity': 'task', 'id': 'done', 'date': '2026-10-26', 'completed': True},
                 {'entity': 'task', 'id': 'remaining', 'date': '2026-10-26', 'completed': False},
                 {'entity': 'task', 'id': 'outside', 'date': '2026-10-30', 'completed': False}]
        analysis = analyze(EXAMS+tasks, plan(), NOW)
        self.assertEqual(['remaining'], [row['id'] for row in analysis['remainingTasks']])
        self.assertEqual(250, analysis['days'][0]['gapsBetweenAppointments'][0]['minutes'])

    def test_past_days_and_unknown_current_time(self):
        later = {**NOW, 'localDateTime': '2026-10-27T01:00:00+09:00'}
        day = analyze(EXAMS, plan(), later)['days'][0]
        self.assertTrue(day['pastDay'])
        self.assertEqual([], day['unbookedWindowsFromNow'])
        unknown = analyze(EXAMS, plan(), {})
        self.assertIsNone(unknown['asOf'])
        self.assertEqual([], unknown['days'][0]['unbookedWindowsFromNow'])


class PlannerReadProtocolTests(unittest.TestCase):
    def test_semantic_read_blocks_premature_answer_and_keeps_original_goal(self):
        host = PlannerHost()
        model = Model(need(premature=True), final('두 시험 사이에 4시간 10분이 있으니 준비를 나눠볼 수 있어요.'))
        payload = {'question': '플래너 보고 와. 시험 하나가 아니거든?', **NOW,
                   'recentConversation': [{'question': plan()['goal'], 'answer': '아침 시험만 있겠네요.'}]}
        answer, effects = run(payload, model, SYSTEM, MAX_OUTPUT, host)
        self.assertEqual(2, len(model.calls))
        self.assertEqual([], effects)
        self.assertNotIn('추측한', answer)
        context = model.calls[1][0]['plannerContext']
        self.assertEqual(plan()['goal'], context['goal'])
        self.assertEqual(250, context['timeAnalysis']['days'][0]['gapsBetweenAppointments'][0]['minutes'])
        queries = [args for tool, args, _ in host.calls if tool == 'planner.query']
        self.assertEqual(1, len(queries))
        self.assertEqual(('2026-10-26', '2026-10-27'), (queries[0]['from'], queries[0]['to']))
        self.assertEqual(['event'], queries[0]['kinds'])

    def test_words_do_not_trigger_prefetch_or_extra_model_calls(self):
        for question in ('오늘 일정이란 표현을 영어로 번역해줘', '내일 시험이라는 문장만 고쳐줘', '안녕'):
            host = PlannerHost()
            model = Model(final('요청한 내용이에요.'))
            run({'question': question, **NOW}, model, SYSTEM, MAX_OUTPUT, host)
            self.assertEqual(1, len(model.calls))
            self.assertNotIn('planner.query', [c[0] for c in host.calls])

    def test_reading_does_not_depend_on_mutation_or_recovery_permission(self):
        host = PlannerHost()
        host.context.update(recoveryInterpretationEligible=True, mutationScope='undo',
                            semanticMutationAuthorization=True)
        model = Model(need(), final('실제 일정을 참고한 조언이에요.'))
        run({'question': '그럼 언제 준비하는 게 좋을까?', **NOW}, model, SYSTEM, MAX_OUTPUT, host)
        calls = [c[0] for c in host.calls]
        self.assertIn('planner.query', calls)
        self.assertNotIn('internal.mutationIntent', calls)
        self.assertNotIn('planner.apply', calls)

    def test_exact_two_day_scope_is_model_selected_not_a_midnight_rule(self):
        request = plan(start='2026-10-26', end='2026-10-28')
        host = PlannerHost()
        model = Model(need(request), final('말씀하신 시험은 26일 일정이에요.'))
        run({'question': '낼 시험인데 얼마나 더 할까?', **NOW}, model, SYSTEM, MAX_OUTPUT, host)
        query = next(c[1] for c in host.calls if c[0] == 'planner.query')
        self.assertEqual('2026-10-28', query['to'])
        self.assertEqual(2, len(model.calls[1][0]['plannerContext']['timeAnalysis']['days']))

    def test_new_revision_reloads_before_final_answer(self):
        host = PlannerHost()
        class ChangingModel(Model):
            def complete(self, payload, **options):
                if len(self.calls) == 1:
                    host.context['plannerAccess']['revision'] = 5
                    host.rows[1]['occurrenceStart'] = '2026-10-26T14:00'
                return super().complete(payload, **options)
        model = ChangingModel(need(), final('오래된 15시 기준 조언'), final('최신 14시 기준 조언'))
        answer, _ = run({'question': '언제 준비할까?', **NOW}, model, SYSTEM, MAX_OUTPUT, host)
        self.assertEqual('최신 14시 기준 조언', answer)
        self.assertEqual(2, sum(c[0] == 'planner.query' for c in host.calls))
        self.assertEqual(190, model.calls[2][0]['plannerContext']['timeAnalysis']['days'][0]['gapsBetweenAppointments'][0]['minutes'])

    def test_complete_manual_query_is_reused_for_semantic_advice(self):
        host = PlannerHost()
        response = need(premature=True)
        response['answer'] = '조회된 일정을 활용한 조언이에요.'
        model = Model(tools(action('planner.query', {'from': '2026-10-26', 'to': '2026-10-27'})), response)
        answer, _ = run({'question': '공부 계획 알려줘', **NOW}, model, SYSTEM, MAX_OUTPUT, host)
        self.assertIn('활용한', answer)
        self.assertEqual(1, sum(c[0] == 'planner.query' for c in host.calls))

    def test_cached_facts_can_finish_in_last_round_and_lookup_stays_lookup(self):
        host = PlannerHost()
        request = plan(purpose='lookup')
        response = need(request, premature=True)
        response['answer'] = '시험은 두 개예요. 오전 10시와 오후 3시예요.'
        model = Model(need(request), need(request), need(request), need(request), need(request), response)
        answer, _ = run({'question': '오늘 시험 시간만 알려줘', **NOW}, model, SYSTEM, MAX_OUTPUT, host)
        self.assertEqual(response['answer'], answer)
        self.assertEqual(1, sum(c[0] == 'planner.query' for c in host.calls))
        self.assertEqual('lookup', model.calls[-1][0]['plannerContext']['purpose'])

    def test_all_pages_are_collected_and_stale_restart_discards_old_rows(self):
        payload = {'localContext': {'plannerAccess': {'revision': 4}}, 'localResults': [], **NOW}
        calls = []
        def local(tool, args, quote):
            calls.append(copy.deepcopy(args))
            if len(calls) == 1:
                return {'ok': True, 'data': {'revision': 4, 'items': [EXAMS[0]], 'hasMore': True, 'nextOffset': 1}}
            if len(calls) == 2:
                return {'ok': False, 'error': 'revision changed'}
            return {'ok': True, 'data': {'revision': 5, 'items': EXAMS, 'hasMore': False}}
        reader = PlannerContext(payload, local)
        reader.ensure(plan())
        self.assertEqual([0, 1, 0], [c['offset'] for c in calls])
        self.assertEqual(4, calls[1]['expectedRevision'])
        self.assertEqual(2, payload['plannerContext']['timeAnalysis']['days'][0]['eventCount'])
        self.assertTrue(payload['plannerContext']['complete'])

    def test_incomplete_read_cannot_be_presented_as_complete_advice(self):
        host = PlannerHost()
        def failing(tool, args, quote):
            if tool == 'planner.query':
                return {'ok': True, 'data': {'revision': 4, 'items': EXAMS[:1], 'hasMore': True, 'nextOffset': 0}}
            return host(tool, args, quote)
        model = Model(need())
        answer, effects = run({'question': '공부 시간 좀 정해줘', **NOW}, model, SYSTEM, MAX_OUTPUT, failing)
        self.assertIn('전체 일정을 확인하지 못했어요', answer)
        self.assertEqual([], effects)
        self.assertEqual(1, len(model.calls))

    def test_read_plan_never_executes_a_pre_read_write(self):
        response = need()
        response['localRequests'] = [action('planner.apply', {'expectedRevision': 4, 'changes': []})]
        host = PlannerHost()
        model = Model(response, final('일정을 등록하지 않고 조언만 해요.'))
        run({'question': '어떻게 준비할까?', **NOW}, model, SYSTEM, MAX_OUTPUT, host)
        self.assertNotIn('planner.apply', [c[0] for c in host.calls])

    def test_invalid_scope_is_rejected_before_reads_and_schema_has_new_field(self):
        self.assertIn('plannerContextRequest', FORMAT['json_schema']['schema']['required'])
        for request in (plan(end='2026-10-26'), plan(start='20261026'), plan(end='2028-01-01'), {**plan(), 'kinds': ['shell']}):
            with self.assertRaises(AiResponseError):
                validate_envelope(need(request))
        self.assertIn('event', validate_request(plan(kinds=['task']))['kinds'])


if __name__ == '__main__':
    unittest.main()
