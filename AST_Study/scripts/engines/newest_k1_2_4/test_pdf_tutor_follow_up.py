"""Follow-up metadata is optional and never replaces an answer or creates a model call."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from pdf_ai import (tutor, valid_tutor_follow_up, partial_json_answer, collect_chat_stream,
                    completed_answer_without_follow_up, Provider as ApiProvider,
                    AiResponseError, TUTOR_MAX_OUTPUT, TUTOR_SYSTEM)
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import document, semantic


class FollowUpTests(unittest.TestCase):
    def test_question_survives_both_existing_answer_modes_without_an_extra_call(self):
        for mode in ('quick', 'deep'):
            with self.subTest(mode=mode):
                answer = '운동량은 질량과 속도의 곱이에요.'
                question = '운동에너지와 운동량은 어떻게 달라?'
                provider = Provider([reply(answer, followUpQuestion='  ' + question + '  ')], semantic('운동량'))
                shown = []
                result = tutor(document(), '운동량을 설명해줘', provider, mode=mode, progress=shown.append)
                self.assertEqual(result['followUpQuestion'], question)
                self.assertEqual(result['answer'], answer)
                self.assertEqual(result['memory']['turns'][-1]['answer'], answer)
                self.assertEqual(shown[-1], answer)
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(provider.calls[0][1]['max_output'], TUTOR_MAX_OUTPUT[mode])
                self.assertNotIn('followUpQuestion', result['memory']['turns'][-1])

    def test_missing_and_malformed_questions_are_omitted(self):
        for value in (None, [], {}, 3, '', '질문\n두 개', 'x' * 161, '```질문```', '질문\x00'):
            with self.subTest(value=value):
                self.assertEqual(valid_tutor_follow_up(value), '')
        provider = Provider([reply('핵심부터 살펴봐요.')], semantic('학습'))
        result = tutor(document(), '학습 방법을 설명해줘', provider)
        self.assertEqual(result['followUpQuestion'], '')

    def test_tutor_offers_are_not_clickable_student_messages(self):
        for offer in ('운동량을 설명해줄까?', '운동량을 설명해 줄까요?',
                      '계산 방법을 알려드릴까요?', '예시를 보여 줄까?',
                      '운동량을 계산해볼까요?', '같이 살펴볼까요?'):
            with self.subTest(offer=offer):
                self.assertEqual(valid_tutor_follow_up(offer), '')
                provider = Provider([reply('운동량은 질량과 속도의 곱이에요.',
                                           followUpQuestion=offer)], semantic('운동량'))
                result = tutor(document(), '운동량을 설명해줘', provider)
                self.assertEqual(result['followUpQuestion'], '')
                self.assertEqual(result['answer'], '운동량은 질량과 속도의 곱이에요.')
                self.assertEqual(len(provider.calls), 1)

    def test_student_requests_and_curiosity_are_preserved_verbatim(self):
        for question in ('충격량과 운동량의 관계에 대해 설명해줘.',
                         '속도가 두 배가 되면 운동에너지는 왜 네 배야?',
                         '영업이익은 흑자인데 당기순이익은 적자일 수도 있어?',
                         '이 식을 숫자 예시로 풀어줄 수 있어?'):
            with self.subTest(question=question):
                self.assertEqual(valid_tutor_follow_up(question), question)

    def test_qualified_answer_keeps_its_own_suggestion_without_another_generation(self):
        answer='맞아요. 운동량은 보존돼요. 다만 모든 계에서 보존된다는 뜻은 아니에요.'
        provider=Provider([reply(answer,claimVerdict='confirmed',followUpQuestion='외력이 있으면 어떻게 달라져?')],semantic('운동량'))
        result=tutor(document(),'외력이 없으면 운동량이 보존되는 거지?',provider)
        self.assertEqual(result['followUpQuestion'],'외력이 있으면 어떻게 달라져?')
        self.assertEqual(result['answer'],answer)
        self.assertEqual(len(provider.calls),1)

    def test_unresolved_answers_omit_suggestions_without_editing_or_retrying_answer(self):
        answer = '조건을 하나 더 알아야 정확히 설명할 수 있어요.'
        for flag in ('notFound', 'needsClarification', 'needsExternalSearch'):
            with self.subTest(flag=flag):
                value = reply(answer, followUpQuestion='운동량을 계산해 볼까?')
                value[flag] = True
                provider = Provider([value], semantic('운동량'))
                result = tutor(document(), '운동량 설명해줘', provider)
                self.assertEqual(result['answer'], answer)
                self.assertEqual(result['followUpQuestion'], '')
                self.assertEqual(len(provider.calls), 1)

    def test_current_or_recent_question_is_not_suggested_again(self):
        for suggested, memory in [
                (' 운동량 설명해줘? ', None),
                ('운동에너지와는 어떻게 달라?', {'documentId': 'doc', 'turns': [
                    {'question': '운동에너지와는 어떻게 달라?', 'answer': '단위부터 달라요.'}]})]:
            with self.subTest(suggested=suggested):
                provider = Provider([reply('운동량은 질량과 속도의 곱이에요.', followUpQuestion=suggested)], semantic('운동량'))
                result = tutor(document(), '운동량 설명해줘', provider, memory=memory)
                self.assertEqual(result['followUpQuestion'], '')

    def test_signs_and_changed_numeric_conditions_are_not_deduplicated(self):
        for current, suggested in [('v=-2이면 p는?', 'v=2이면 p는?'), ('p=2이면?', 'P=2이면?')]:
            provider = Provider([reply('기호와 부호를 구분해서 계산해요.', followUpQuestion=suggested)], semantic('운동량'))
            result = tutor(document(), current, provider)
            self.assertEqual(result['followUpQuestion'], suggested)

    def test_question_already_in_answer_is_not_duplicated_as_a_button(self):
        answer = '다음에는 운동에너지와 비교해 볼까요?'
        provider = Provider([reply(answer, followUpQuestion=answer)], semantic('운동량'))
        result = tutor(document(), '운동량 설명해줘', provider)
        self.assertEqual(result['answer'], answer)
        self.assertEqual(result['followUpQuestion'], '')

    def test_unicode_line_separators_are_not_single_line_metadata(self):
        for separator in ('\u2028', '\u2029'):
            self.assertEqual(valid_tutor_follow_up('한 질문'+separator+'다른 질문'), '')

    def test_stream_never_selects_nested_answer_inside_malformed_metadata(self):
        content = json.dumps({'followUpQuestion': {'answer': '본문에 섞이면 안 돼요.'},
                              'answer': '실제 설명이에요.'}, ensure_ascii=False)
        self.assertEqual(partial_json_answer(content), '실제 설명이에요.')
        self.assertEqual(partial_json_answer('{"followUpQuestion":{"answer":"잘못된'), '')
        for order in ('first', 'last'):
            value = ({'followUpQuestion': '운동에너지와는 어떻게 달라?', 'answer': '운동량은 보존돼요.'}
                     if order == 'first' else {'answer': '운동량은 보존돼요.', 'followUpQuestion': '운동에너지와는 어떻게 달라?'})
            content = json.dumps(value, ensure_ascii=False)
            def lines():
                for char in content:
                    yield 'data: '+json.dumps({'choices': [{'delta': {'content': char}}]})+'\n'
                yield 'data: '+json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})+'\n'
                yield 'data: [DONE]\n'
            shown = []
            collect_chat_stream(lines(), shown.append)
            self.assertEqual(shown[-1], value['answer'])
            self.assertTrue(all(value['answer'].startswith(text) for text in shown))

    def test_single_answer_prompt_prioritizes_answer_and_keeps_suggestion_last(self):
        self.assertIn('complete answer and evidence first',TUTOR_SYSTEM.lower())
        self.assertIn('followUpQuestion LAST',TUTOR_SYSTEM)
        self.assertIn('determine the full proposition first',TUTOR_SYSTEM)


    def test_single_answer_question_stays_separate_from_stream_and_memory(self):
        answer='화살이 앞으로 얻은 운동량만큼 궁수는 뒤로 운동량을 얻어요.'
        question='화살을 비스듬히 쏘면 궁수의 반동은 어떻게 달라져?'
        provider=Provider([reply(answer,followUpQuestion=question)],semantic('운동량'))
        shown=[]
        result=tutor(document(),'궁수의 반동을 설명해줘',provider,progress=shown.append)
        self.assertEqual(result['followUpQuestion'],question)
        self.assertEqual(result['answer'],answer)
        self.assertEqual(result['memory']['turns'][-1]['answer'],answer)
        self.assertEqual(shown[-1],answer)
        self.assertNotIn('',shown)
        self.assertEqual(len(provider.calls),1)

class OptionalTailTests(unittest.TestCase):
    def core(self):
        return {'claimVerdict': 'none', 'answer': '운동량은 질량과 속도의 곱이에요.',
                'responseKind': 'general', 'notFound': False, 'requiresPdfEvidence': False,
                'needsClarification': False, 'needsExternalSearch': False, 'webSearchTopic': '',
                'evidence': [], 'visualPages': []}

    def content(self, value=None, tail='"그럼 운동에너지는'):
        return json.dumps(self.core() if value is None else value, ensure_ascii=False)[:-1]+',"followUpQuestion":'+tail

    def test_recovers_only_when_all_answer_fields_precede_the_optional_tail(self):
        for tail in ('', '"질문', '"질문\\', '"질문\\u', '"질문"', '"질문"}'):
            with self.subTest(tail=tail):
                self.assertEqual(completed_answer_without_follow_up(self.content(tail=tail)),
                                 {**self.core(), 'followUpQuestion': ''})
        for key in self.core():
            value = self.core(); value.pop(key)
            self.assertIsNone(completed_answer_without_follow_up(self.content(value)))

    def test_rejects_incomplete_answers_nested_metadata_and_later_fields(self):
        for content in ('{"answer":"미완성', '{"answer":"followUpQuestion: 질문',
                        self.content(tail='{"answer":"이건 본문이 아니에요'),
                        self.content(tail='"질문","evidence":['), self.content(tail='"질문",')):
            with self.subTest(content=content):
                self.assertIsNone(completed_answer_without_follow_up(content))
        value = self.core();value['needsClarification'] = 'false'
        self.assertIsNone(completed_answer_without_follow_up(self.content(value)))

    def test_review_tail_uses_review_fields_without_requiring_web_topic(self):
        value = self.core();value.pop('webSearchTopic')
        self.assertEqual(completed_answer_without_follow_up(self.content(value), review=True),
                         {**value, 'followUpQuestion': ''})

    def test_completed_teaching_body_survives_an_optional_tail_truncation(self):
        for teaching,expected in (
                ({'lead':'생성된 본문','case':{}},'생성된 본문'),
                ({'lead':'조건 설명','case':{'development':'이미 생성된 결과'}},
                 '조건 설명\n\n이미 생성된 결과'),
                ({'case':{'development':'본문 전개'}},'본문 전개')):
            value={**self.core(),'answer':'','teaching':teaching}
            recovered=completed_answer_without_follow_up(self.content(value))
            self.assertEqual(recovered['answer'],expected)
            self.assertEqual(recovered['followUpQuestion'],'')
        self.assertIsNone(completed_answer_without_follow_up(
            self.content({**self.core(),'answer':'','teaching':{'lead':'','case':{}}})))

    def test_provider_preserves_usage_raw_tail_and_cache_without_an_extra_call(self):
        calls = []
        def transport(body):
            calls.append(body)
            return {'choices': [{'finish_reason': 'length', 'message': {'content': self.content()}}],
                    'usage': {'prompt_tokens': 50, 'completion_tokens': 30}}
        with tempfile.TemporaryDirectory() as folder:
            provider = ApiProvider(Path(folder), True, .1, transport=transport)
            payload = {'taskType': 'tutor', 'question': '운동량은?'}
            shown = []
            value = provider.complete(payload, max_output=1800, on_delta=shown.append)
            self.assertEqual(value, {**self.core(), 'followUpQuestion': ''})
            self.assertEqual(shown[-1], self.core()['answer'])
            self.assertEqual(provider.complete(payload, max_output=1800), value)
            self.assertEqual(len(calls), 1)
            entry = provider.ledger['requests'][0]
            self.assertEqual(entry['state'], 'settled')
            self.assertEqual(entry['finishReason'], 'length')
            self.assertEqual(entry['usage']['completion_tokens'], 30)
            self.assertTrue(entry['optionalMetadataOmitted'])
            saved = json.loads(next(Path(folder).glob('generated/paid-responses/*.incomplete.json')).read_text())
            self.assertEqual(saved['content'], self.content())
            self.assertTrue(saved['completedAnswerRecovered'])

    def test_provider_never_recovers_non_tutor_truncation_or_filtered_responses(self):
        for task, reason in (('summary', 'length'), ('tutor', 'content_filter'), ('tutor', 'tool_calls')):
            def transport(body):
                return {'choices': [{'finish_reason': reason, 'message': {'content': self.content()}}]}
            with self.subTest(task=task, reason=reason), tempfile.TemporaryDirectory() as folder:
                provider = ApiProvider(Path(folder), True, .1, transport=transport)
                with self.assertRaises(AiResponseError):
                    provider.complete({'taskType': task}, max_output=1800)

    def test_provider_does_not_accept_a_truncated_answer_or_refusal_as_metadata_failure(self):
        for content, refusal in [('{"answer":"계산 중인 식', None), (self.content(), 'fixture refusal')]:
            def transport(body):
                return {'choices': [{'finish_reason': 'length', 'message': {'content': content, 'refusal': refusal}}]}
            with self.subTest(refusal=refusal), tempfile.TemporaryDirectory() as folder:
                provider = ApiProvider(Path(folder), True, .1, transport=transport)
                with self.assertRaises(AiResponseError):
                    provider.complete({'taskType': 'tutor'}, max_output=1800)



if __name__ == '__main__':
    unittest.main()
