"""Tutor effort is independent of presentation mode and response-cache identity."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_ai as ai
from test_pdf_tutor_intent import semantic


def request_context(body):
    final=body['messages'][-1]['content']
    if final.startswith('{'):return json.loads(final)  # The unchanged planner wire.
    return {**json.loads(body['messages'][-2]['content'].split('\n',1)[1]),'question':final}


class TutorReasoningTests(unittest.TestCase):
    def test_desktop_selection_reaches_answer_api_independently_of_mode(self):
        for mode in ('quick','deep'):
            for effort in ('medium','low'):
                with self.subTest(mode=mode,effort=effort),tempfile.TemporaryDirectory() as directory:
                    calls=[]
                    def transport(body):
                        payload=request_context(body);calls.append((payload,body))
                        value=semantic('운동량') if payload.get('operation')=='query_plan' else {
                            'claimVerdict':'none','responseForm':'direct','answer':'운동량은 질량과 속도의 곱이에요.',
                            'responseKind':'general','notFound':False,'needsExternalSearch':False,
                            'requiresPdfEvidence':False,'needsClarification':False,'evidence':[],'visualPages':[]}
                        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
                                'usage':{'prompt_tokens':100,'completion_tokens':100}}
                    provider=ai.Provider(Path(directory),True,.1,transport=transport)
                    result=ai.run_tutor_request(Path(directory),{'documentId':'doc','pages':[{}],'chunks':[]},
                        {'question':'운동량을 설명해줘.','mode':mode,'reasoningEffort':effort},provider)
                    answers=[body for payload,body in calls if 'learningTask' in payload]
                    plans=[body for payload,body in calls if payload.get('operation')=='query_plan']
                    self.assertEqual([body['reasoning_effort'] for body in answers],[effort])
                    self.assertEqual([body['reasoning_effort'] for body in plans],['low'])
                    self.assertEqual(len(calls),2)
                    self.assertEqual(result['contextDiagnostics']['reasoningEffort'],effort)

    def test_selected_effort_has_a_separate_cache_and_rejects_invalid_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            def transport(body):
                calls.append(body)
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'answer':body['reasoning_effort']})}}],
                        'usage':{'prompt_tokens':100,'completion_tokens':100}}
            provider=ai.Provider(Path(directory),True,.1,transport=transport)
            payload={'taskType':'tutor','question':'설명해줘'}
            for effort in ('low','medium','low'):
                self.assertEqual(provider.complete({**payload,'tutorReasoningEffort':effort},max_output=200)['answer'],effort)
            self.assertEqual(len(calls),2)
            for effort in ('high','none','',17,[]):
                with self.subTest(invalid=effort),self.assertRaises(ValueError):
                    ai.run_tutor_request(Path(directory),{'documentId':'doc','pages':[],'chunks':[]},
                        {'question':'설명해줘','reasoningEffort':effort},provider)
                with self.assertRaises(ValueError):
                    provider.complete({**payload,'tutorReasoningEffort':effort},max_output=200)
            self.assertEqual(len(calls),2)

    def test_both_modes_send_medium_for_answers_without_changing_routing(self):
        for mode in ('quick','deep'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                calls=[]
                def transport(body):
                    payload=request_context(body)
                    calls.append((payload,body))
                    value=semantic('운동량') if payload.get('operation')=='query_plan' else {
                        'claimVerdict':'none','responseForm':'direct','answer':'운동량은 질량과 속도의 곱이에요.',
                        'responseKind':'general','notFound':False,'needsExternalSearch':False,
                        'requiresPdfEvidence':False,'needsClarification':False,'evidence':[],'visualPages':[]}
                    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
                            'usage':{'prompt_tokens':100,'completion_tokens':100}}
                p=ai.Provider(Path(directory),True,.1,transport=transport)
                result=ai.tutor({'documentId':'doc','pages':[{}],'chunks':[]},
                                '운동량을 설명해줘.',p,mode=mode)
                self.assertTrue(result['answer'])
                answers=[body for payload,body in calls if 'learningTask' in payload]
                plans=[body for payload,body in calls if payload.get('operation')=='query_plan']
                self.assertEqual(len(answers),1)
                self.assertEqual(answers[0]['reasoning_effort'],'medium')
                self.assertEqual(len(plans),1)
                self.assertEqual(plans[0]['reasoning_effort'],'low')
                self.assertEqual([r['tutorReasoningEffort'] for r in p.ledger['requests']
                                  if 'tutorReasoningEffort' in r],['medium'])

    def test_effort_change_cannot_reuse_a_response_from_another_effort(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            def transport(body):
                calls.append(body)
                return {'choices':[{'finish_reason':'stop','message':{'content':
                    json.dumps({'answer':body['reasoning_effort']})}}],
                    'usage':{'prompt_tokens':100,'completion_tokens':100}}
            p=ai.Provider(Path(directory),True,.1,transport=transport)
            payload={'taskType':'tutor','question':'어떤 설명인가요?'}
            with patch.object(ai,'TUTOR_REASONING_EFFORT','low'):
                self.assertEqual(p.complete(payload,max_output=200)['answer'],'low')
            self.assertEqual(p.complete(payload,max_output=200)['answer'],'medium')
            self.assertEqual(p.complete(payload,max_output=200)['answer'],'medium')
            self.assertEqual(len(calls),2)
            self.assertNotEqual(p.ledger['requests'][0]['responseCacheKey'],p.ledger['requests'][1]['responseCacheKey'])

    def test_personal_assistant_and_non_tutor_generation_keep_their_own_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            def transport(body):
                calls.append(body)
                return {'choices':[{'finish_reason':'stop','message':{'content':'{"answer":"본문"}'}}],
                        'usage':{'prompt_tokens':100,'completion_tokens':10}}
            p=ai.Provider(Path(directory),True,.1,transport=transport)
            p.context={'assistantReasoningEffort':'low'}
            p.complete({'taskType':'tutor','operation':'home_assistant_chat','question':'안녕'},max_output=200)
            p.complete({'task':'Summarize','sources':[]},max_output=200)
            self.assertEqual([body['reasoning_effort'] for body in calls],['low','none'])


if __name__=='__main__':unittest.main()
