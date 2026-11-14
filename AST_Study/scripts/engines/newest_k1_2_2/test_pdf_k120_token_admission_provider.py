"""Offline Provider integration for fixed-prefix TPM calibration."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_api_slots as slots
import test_pdf_responses_provider as fixtures
from test_pdf_responses_transport import native


class TokenAdmissionProviderTest(unittest.TestCase):
    setUp = fixtures.ResponsesProviderTests.setUp
    provider = fixtures.ResponsesProviderTests.provider
    reply = fixtures.ResponsesProviderTests.reply

    def make(self):
        provider = self.provider(mode='chat')
        provider.billing = None
        provider.context = {'kind':'region_study','strategy':'newest-k1-2-2',
                            'studyForegroundResponses':True,'unitIds':['u1']}
        return provider

    def test_first_receipt_calibrates_next_request_without_changing_source_or_caps(self):
        self.reply(native())
        provider = self.make()
        options = {**self.options, 'system_prompt': 'Fixed teaching instructions. ' * 1000,
                   'max_output': 18000}
        first_payload = copy.deepcopy(self.payload)
        second_payload = copy.deepcopy(self.payload)
        second_payload['blocks'][0]['text'] += ' 다른 단락 원문을 그대로 보존해요.'
        before = copy.deepcopy((first_payload, second_payload, options))
        # Fixture responses prevent HTTP/socket access; real local admission
        # verifies the callback is invoked and output reservation is retained.
        with patch.object(ai, 'api_slot', slots.api_slot):
            self.assertEqual(provider.complete(first_payload, **options), {'ok':True})
            first = provider.ledger['requests'][0]
            self.assertEqual(first['tokenAdmissionInputEstimate'], first['inputTokenBound'])
            self.assertEqual(first['tokenAdmissionConfirmedSamples'], 0)
            self.assertEqual(first['state'], 'settled')
            provider.context['unitIds'] = ['u2']
            self.assertEqual(provider.complete(second_payload, **options), {'ok':True})
        second = provider.ledger['requests'][1]
        self.assertEqual(second['tokenAdmissionConfirmedSamples'], 1)
        self.assertEqual(second['tokenAdmissionEvidenceRequestId'], first['requestId'])
        expected = second['inputTokenBound'] - len(options['system_prompt'].encode()) + 1250 + 256
        self.assertEqual(second['tokenAdmissionInputEstimate'], expected)
        self.assertEqual(second['maxOutputTokens'], 18000)
        self.assertEqual(second['providerUpperBoundUsd'], second['reservedUsd'])
        requests = [json.loads(call.args[0].data)for call in self.opener.call_args_list]
        self.assertEqual(len(requests), 2)
        for body, source in zip(requests, (first_payload, second_payload)):
            self.assertEqual(json.loads(body['input'][1]['content'][0]['text']), source)
            self.assertEqual(body['input'][0]['content'][0]['text'], options['system_prompt'])
            self.assertEqual(body['input'][0]['content'][1]['text'], ai.STUDY_FINAL_DELIVERY)
            self.assertEqual(body['max_output_tokens'], 18000)
            self.assertEqual(body['text']['format']['schema'], options['response_format']['json_schema']['schema'])
        rate = json.loads((Path(provider.rate_directory)/'rate-state.json').read_text())
        self.assertEqual([r[1]for r in rate['models']['gpt-6-luna']['requests']],
                         [max(first['inputTokenBound'],18000), max(expected,18000)])
        self.assertEqual((first_payload, second_payload, options), before)

    def test_modified_instruction_or_delivery_contract_is_cold_again(self):
        self.reply(native())
        provider = self.make()
        options = {**self.options, 'system_prompt': 'Fixed instructions. ' * 1000}
        with patch.object(ai, 'api_slot', slots.api_slot):
            provider.complete(self.payload, **options)
            provider.complete(self.payload, **{**options, 'system_prompt':options['system_prompt']+' changed'})
            source = {**self.payload, 'revision':'different-source'}
            with patch.object(ai, 'STUDY_FINAL_DELIVERY', ai.STUDY_FINAL_DELIVERY+' extra contract'):
                provider.complete(source, **options)
        rows = provider.ledger['requests']
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['tokenAdmissionConfirmedSamples']==0 for r in rows))
        self.assertEqual(len({r['tokenAdmissionPrefixSha']for r in rows}),3)

    def test_overview_has_no_teaching_calibration_callback(self):
        self.reply(native())
        provider = self.make();provider.context['kind']='summary_reduce'
        provider.complete({'task':'lecture_flow_from_planned_units','titles':['강의 제목']}, **self.options)
        self.assertNotIn('input_tokens_estimator',self.admissions[0])
        self.assertNotIn('tokenAdmissionPolicy',provider.ledger['requests'][0])


if __name__ == '__main__':
    unittest.main()
