"""Offline follow-up intent contracts; no vocabulary-to-answer routing or paid calls."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pdf_ai import Provider as ApiProvider, TUTOR_MAX_OUTPUT, tutor
from pdf_tutor_delivery import learning_task
from pdf_tutor_intent import PLAN_SYSTEM, FOLLOWUP_PLAN_SYSTEM
from test_pdf_tutor_context import doc
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import semantic


def memory():
    return {'documentId': 'doc', 'topicQuestion': '1페이지 2번 풀이해줘.',
            'focus': {'subject': '클래스의 구성', 'page': 1, 'viewerPage': 1},
            'sourceTask': {'page': 1, 'item': 2, 'action': 'solve'},
            'turns': [{'question': '1페이지 2번 풀이해줘.',
                       'answer': '클래스의 두 구성은 Datafield (Member Variable)와 '
                                 'Interface (Member Function)예요.'}]}


def focus_plan(**changes):
    return {**semantic('클래스 구성 요소', query='Datafield Interface 멤버변수 멤버함수',
                      page=1, followup=True), 'scope': 'pdf',
            'answerFocus': '직전 두 분류 중 멤버변수와 멤버함수가 각각 어디에 해당하는지',
            'needsExample': False, **changes}


class RecordingProvider(Provider):
    def __init__(self, plan):
        super().__init__([reply('이 문항에서 멤버변수는 Datafield, 멤버함수는 Interface에 해당해요.')], plan)
        self.plans = []

    def plan_tutor(self, payload):
        self.plans.append(copy.deepcopy(payload))
        return copy.deepcopy(self.plan)


class TutorFollowupFocusTests(unittest.TestCase):
    def run_question(self, question, plan=None, **options):
        document = doc('2. 클래스는 Datafield (Member Variable)과 Interface (Member Function)으로 '
                       '구성된다. 6. class ABC { public: int a, b; void set(int, int); };')
        document['pages'].append({'nativeText': '다른 페이지의 새 개념'})
        provider = RecordingProvider(focus_plan() if plan is None else plan)
        with patch('pdf_tutor_page_image.prepare', return_value=([], [])):
            result = tutor(document, question, provider, memory=options.pop('memory', memory()),
                           web_fallback=False, **options)
        return provider, result, provider.calls[0][0]

    def test_prior_distinction_is_carried_once_in_existing_calls_and_both_modes(self):
        question = '아하 ㅇㅋ. 거기서 그 멤버변수, 멤버함수 이런건 어디에 들어가?'
        for mode in ('quick', 'deep'):
            with self.subTest(mode=mode):
                provider, result, payload = self.run_question(question, mode=mode, current_page=1)
                self.assertEqual(payload['question'], question)
                self.assertEqual(payload['questionPlan']['resolvedRequest'], focus_plan()['answerFocus'])
                self.assertEqual(payload['topicHint'], '')
                self.assertEqual(payload['priorSource'], {'page': 1, 'item': 2})
                self.assertNotIn('sourceTask', payload)
                self.assertEqual(payload['learningTask']['responseContract'], 'direct')
                self.assertEqual(payload['learningTask']['explanationMode'], mode)
                self.assertEqual(len(provider.plans), 1)
                self.assertTrue(provider.plans[0]['followupHints'])
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(provider.calls[0][1]['max_output'], TUTOR_MAX_OUTPUT[mode])
                self.assertFalse(provider.searches)
                self.assertEqual(result['memory']['turns'][-1]['question'], question)

    def test_semantic_result_can_request_code_location_and_a_worked_example(self):
        focus = '클래스 선언에서 멤버변수와 멤버함수를 배치하는 위치를 코드 예시로 설명'
        provider, _, payload = self.run_question(
            '아까 말한 것들이 코드에서 어디에 있는지 예시를 자세히 보여줘.',
            focus_plan(answerFocus=focus, needsExample=True), mode='deep', current_page=1)
        self.assertEqual(payload['questionPlan']['resolvedRequest'], focus)
        self.assertEqual(payload['learningTask']['responseContract'], 'direct')
        self.assertNotIn('response_format', provider.calls[0][1])
        self.assertEqual(payload['priorSource'], {'page': 1, 'item': 2})

    def test_same_question_text_follows_semantic_intent_without_phrase_dispatch(self):
        question = '그건 어디에 들어가?'
        for focus, needed, contract in [('앞서 설명한 두 범주 사이의 분류 관계', False, 'direct'),
                                        ('실제 선언 위치를 예시로 설명', True, 'direct')]:
            with self.subTest(focus=focus):
                _, _, payload = self.run_question(question, focus_plan(answerFocus=focus, needsExample=needed),
                                                  mode='deep', current_page=1)
                self.assertEqual(payload['questionPlan']['resolvedRequest'], focus)
                self.assertEqual(payload['learningTask']['responseContract'], contract)

    def test_new_numbered_item_cannot_inherit_previous_semantic_focus(self):
        _, _, payload = self.run_question('1페이지 3번 해설해줘.', mode='deep', current_page=1)
        self.assertEqual(payload['sourceTask']['item'], 3)
        self.assertIn('3번', payload['questionPlan']['resolvedRequest'])
        self.assertNotEqual(payload['questionPlan']['resolvedRequest'], focus_plan()['answerFocus'])
        self.assertNotIn('priorSource', payload)

    def test_changed_page_and_new_topic_do_not_keep_old_focus(self):
        for question, plan, page in [
                ('2페이지 내용을 설명해줘.', focus_plan(page=2), 2),
                ('광합성 원리를 설명해줘.', focus_plan(subject='광합성', query='광합성 원리',
                    followup=False, page=None, scope='general'), 1)]:
            with self.subTest(question=question):
                _, _, payload = self.run_question(question, plan, mode='deep', current_page=page)
                self.assertNotEqual(payload['questionPlan']['resolvedRequest'], focus_plan()['answerFocus'])
                self.assertNotIn('priorSource', payload)
                self.assertEqual(payload['learningTask']['responseContract'], 'direct')

    def test_new_selection_and_attachment_supersede_prior_focus(self):
        selection = {'documentId': 'doc', 'origin': '개념', 'title': '새로 선택한 정의',
                     'pages': [1], 'context': '선택한 다른 개념의 정의예요.'}
        for options in ({'selection_context': selection},
                        {'attachment': {'name': '새 노트', 'kind': 'image', 'images': []}}):
            with self.subTest(options=options):
                _, _, payload = self.run_question('이 PDF 내용의 관계를 설명해줘.',
                                                  mode='deep', current_page=1, **options)
                self.assertNotIn('priorSource', payload)
                self.assertEqual(payload['learningTask']['responseContract'], 'direct')
                if 'questionPlan' in payload:
                    self.assertNotEqual(payload['questionPlan']['resolvedRequest'], focus_plan()['answerFocus'])

    def test_fresh_chat_does_not_opt_into_followup_prompt(self):
        provider, _, payload = self.run_question('클래스의 구성을 설명해줘.',
            focus_plan(followup=False), memory={}, current_page=1)
        self.assertNotIn('followupHints', provider.plans[0])
        self.assertNotIn('priorSource', payload)

    def test_shared_planner_addition_requires_strict_mentor_opt_in(self):
        for flag, expected in [(None, PLAN_SYSTEM), (False, PLAN_SYSTEM),
                               ('true', PLAN_SYSTEM), (True, FOLLOWUP_PLAN_SYSTEM)]:
            payload = {} if flag is None else {'followupHints': flag}
            provider = SimpleNamespace(complete=Mock(return_value={'plan': True}))
            ApiProvider.plan_tutor(provider, payload)
            self.assertEqual(provider.complete.call_count, 1)
            args, options = provider.complete.call_args
            self.assertEqual(args, (payload,))
            self.assertEqual(options, {'max_output': 512, 'system_prompt': expected})

    def test_example_hints_never_force_a_prose_schema(self):
        for plan in ({}, {'needsExample': False}, {'followup': True},
                     {'followup': True, 'needsExample': 'false'}):
            self.assertEqual(learning_task('앞서 설명한 관계를 다시 설명해줘.', 'deep', plan)
                             ['responseContract'], 'direct')


if __name__ == '__main__':
    unittest.main()
