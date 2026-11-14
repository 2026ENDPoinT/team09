"""Pure Responses pilot conversions: no transport or credential use."""
import copy
import json
import unittest

from pdf_responses_transport import ResponsesTransportError, request_body, response_body


FORMAT = {'type': 'json_schema', 'json_schema': {'name': 'study_fixture', 'strict': True,
    'schema': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
               'required': ['ok'], 'additionalProperties': False}}}


def chat():
    payload = {'task': 'region_teaching', 'blocks': [{'id': 'v2p1f0',
        'text': r'원문 \(x_{i+1}=x_i-1\) 및 code {"a": "u0"}를 그대로 보존해요.'}]}
    return {'model': 'gpt-6-luna', 'store': True, 'messages': [
        {'role': 'system', 'content': [{'type': 'text', 'text': '고정 학습 지침 \n 원문은 그대로예요.',
            'prompt_cache_breakpoint': {'mode': 'explicit'}}]},
        {'role': 'user', 'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)},
            {'type': 'text', 'text': '원래 이미지 라벨도 그대로예요.'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/webp;base64,EXACT-ORIGINAL-BYTES', 'detail': 'high'}}]}],
        'response_format': copy.deepcopy(FORMAT), 'max_completion_tokens': 18000,
        'reasoning_effort': 'none', 'prompt_cache_options': {'mode': 'explicit'}}


def native():
    return {'id': 'resp_fixture', 'status': 'completed', 'error': None, 'incomplete_details': None,
        'output': [{'type': 'reasoning', 'summary': []}, {'type': 'message', 'role': 'assistant',
            'status': 'completed', 'content': [{'type': 'output_text', 'text': '{"ok":'},
                                               {'type': 'output_text', 'text': 'true}'}]}],
        'usage': {'input_tokens': 1000, 'output_tokens': 100, 'total_tokens': 1100,
            'input_tokens_details': {'cached_tokens': 200, 'cache_write_tokens': 300},
            'output_tokens_details': {'reasoning_tokens': 7}}}


class ResponsesTransportTests(unittest.TestCase):
    def test_low_reasoning_preserves_background_transport_contract(self):
        value=chat();value['reasoning_effort']='low'
        converted=request_body(value)
        self.assertEqual(converted['reasoning'],{'effort':'low'})
        self.assertTrue(converted['store'])
        self.assertEqual(converted['text']['format']['schema'],value['response_format']['json_schema']['schema'])

    def test_higher_reasoning_is_limited_to_single_body_generation(self):
        value = chat()
        for effort in ('medium', 'high'):
            value['reasoning_effort'] = effort
            self.assertEqual(request_body(value)['reasoning'], {'effort': effort})
        value['messages'][1]['content'][0]['text'] = json.dumps({'task': 'region_groups'})
        with self.assertRaises(ResponsesTransportError):
            request_body(value)

    def test_request_preserves_every_text_image_schema_and_cache_breakpoint(self):
        value = chat();before = copy.deepcopy(value);result = request_body(value)
        self.assertEqual(value, before)
        self.assertEqual(result['model'], value['model']);self.assertTrue(result['store'])
        self.assertEqual(result['max_output_tokens'], 18000)
        self.assertEqual(result['reasoning'], {'effort': 'none'})
        self.assertEqual(result['text']['format'], {'type': 'json_schema', **value['response_format']['json_schema']})
        for old, new in zip(value['messages'], result['input']):
            for part, restored in zip(old['content'], new['content']):
                if part['type'] == 'text':
                    self.assertEqual(restored['text'], part['text'])
                    self.assertEqual(restored.get('prompt_cache_breakpoint'), part.get('prompt_cache_breakpoint'))
                else:
                    self.assertEqual(restored['image_url'], part['image_url']['url'])
                    self.assertEqual(restored['detail'], part['image_url']['detail'])
        self.assertEqual([message['role'] for message in result['input']], ['developer', 'user'])
        self.assertEqual(result['prompt_cache_options'], {'mode': 'explicit'})
        result['text']['format']['schema']['properties']['ok']['type'] = 'string'
        self.assertEqual(value, before)

    def test_plain_string_content_store_false_and_explicit_temperature_remain_exact(self):
        value = chat();value['messages'][0] = {'role': 'developer', 'content': 'literal\n\t < > **'}
        value['messages'][1]['content'] = value['messages'][1]['content'][0]['text']
        value['store'] = False;value['temperature'] = 0
        value.pop('prompt_cache_options')
        result = request_body(value)
        self.assertFalse(result['store']);self.assertEqual(result['temperature'], 0)
        self.assertNotIn('prompt_cache_options', result)
        self.assertEqual(result['input'][0]['content'], [{'type': 'input_text', 'text': 'literal\n\t < > **'}])
        self.assertEqual(result['input'][1]['content'][0]['text'], value['messages'][1]['content'])

    def test_independent_batch_payload_is_preserved_as_one_request(self):
        value = chat();original = json.loads(value['messages'][1]['content'][0]['text'])
        payload = {'task': 'region_teaching_batch', 'units': {'u0': original, 'u1': copy.deepcopy(original)},
                   'imageOrder': [{'unit': 'u0', 'cropIndex': 0}]}
        value['messages'][1]['content'][0]['text'] = json.dumps(payload, ensure_ascii=False)
        value['max_completion_tokens'] = 36000
        result = request_body(value)
        self.assertEqual(result['max_output_tokens'], 36000)
        self.assertEqual(result['input'][1]['content'][0]['text'], value['messages'][1]['content'][0]['text'])

    def test_stream_tool_tutor_multiturn_and_unknown_fields_reject_before_send(self):
        for field, data in (('stream', True), ('stream', False), ('stream_options', {}),
                            ('on_delta', None), ('tools', []), ('tool_choice', 'none'),
                            ('service_tier', 'priority'), ('unknown', 'do not silently drop')):
            value = chat();value[field] = data
            with self.subTest(field=field), self.assertRaises(ResponsesTransportError):request_body(value)
        for task in ({'taskType': 'tutor'}, {'task': 'region_teaching', 'taskType': 'tutor'},
                     {'task': 'plan_groups'}, {'task': 'region_teaching_batch', 'units': {'u0': {}}}):
            value = chat();value['messages'][1]['content'][0]['text'] = json.dumps(task)
            with self.subTest(task=task), self.assertRaises(ResponsesTransportError):request_body(value)
        value = chat();value['messages'].append({'role': 'assistant', 'content': 'history'})
        with self.assertRaises(ResponsesTransportError):request_body(value)

    def test_malformed_or_unsupported_values_never_get_silently_normalized_into_request(self):
        for field, data in (('max_completion_tokens', True), ('max_completion_tokens', 0),
                            ('reasoning_effort', 'invalid'), ('temperature', float('nan')),
                            ('temperature', True), ('store', 1), ('prompt_cache_options', {'mode': 'explicit', 'ttl': '12h'})):
            value = chat();value[field] = data
            with self.subTest(field=field, data=data), self.assertRaises(ResponsesTransportError):request_body(value)
        value = chat();value['messages'][0]['content'][0]['prompt_cache_breakpoint']['ttl'] = '12h'
        with self.assertRaises(ResponsesTransportError):request_body(value)
        value = chat();value['response_format']['type'] = 'json_object'
        with self.assertRaises(ResponsesTransportError):request_body(value)

    def test_native_response_preserves_full_body_usage_and_exact_concatenated_output(self):
        value = native();before = copy.deepcopy(value);result = response_body(value)
        self.assertEqual(value, before)
        self.assertEqual(result['choices'][0], {'message': {'role': 'assistant', 'content': '{"ok":true}'}, 'finish_reason': 'stop'})
        self.assertEqual(result['usage'], {'prompt_tokens': 1000, 'completion_tokens': 100, 'total_tokens': 1100,
            'prompt_tokens_details': {'cached_tokens': 200, 'cache_write_tokens': 300},
            'completion_tokens_details': {'reasoning_tokens': 7}})
        self.assertEqual(result['_responsesApiRaw'], before)
        result['_responsesApiRaw']['usage']['input_tokens'] = 0
        self.assertEqual(value, before)

    def test_native_cache_write_lifetime_and_reasoning_details_are_preserved_unchanged(self):
        value = native()
        value['usage']['input_tokens_details']['cache_write_tokens_details'] = {
            'ttl_12h_tokens': 0, 'ttl_30m_tokens': 300}
        before = copy.deepcopy(value)
        result = response_body(value)
        self.assertEqual(result['usage']['prompt_tokens_details'], value['usage']['input_tokens_details'])
        self.assertEqual(result['usage']['completion_tokens_details'], value['usage']['output_tokens_details'])
        self.assertEqual(result['choices'][0]['finish_reason'], 'stop')
        result['usage']['prompt_tokens_details']['cache_write_tokens_details']['ttl_30m_tokens'] = 0
        self.assertEqual(value, before)

    def test_refusal_is_preserved_and_cannot_become_successful_json(self):
        value = native();value['output'][1]['content'] = [{'type': 'refusal', 'refusal': 'fixture refusal'}]
        result = response_body(value)
        self.assertEqual(result['choices'][0]['message']['refusal'], 'fixture refusal')
        self.assertEqual(result['choices'][0]['finish_reason'], 'stop')
        self.assertEqual(result['_responsesApiRaw'], value)

    def test_commentary_malformed_json_is_native_only_and_one_explicit_final_is_selected(self):
        value = native()
        final = copy.deepcopy(value['output'][1]);final['phase'] = 'final_answer'
        commentary = {'type': 'message', 'role': 'assistant', 'status': 'completed', 'phase': 'commentary',
                      'content': [{'type': 'output_text', 'text': '{"ok": false, "unfinished":'}]}
        value['output'] = [commentary, final]
        before = copy.deepcopy(value);result = response_body(value)
        self.assertEqual(result['choices'][0]['finish_reason'], 'stop')
        self.assertEqual(json.loads(result['choices'][0]['message']['content']), {'ok': True})
        self.assertEqual(result['usage']['prompt_tokens'], value['usage']['input_tokens'])
        self.assertEqual(result['_responsesApiRaw'], before)
        self.assertEqual(value, before)

    def test_commentary_refusal_is_not_mixed_into_explicit_final_and_final_refusal_remains(self):
        value = native();final = value['output'][1];final['phase'] = 'final_answer'
        commentary = {'type': 'message', 'role': 'assistant', 'phase': 'commentary',
                      'content': [{'type': 'refusal', 'refusal': 'commentary only'}]}
        value['output'] = [commentary, final]
        result = response_body(value)
        self.assertEqual(result['choices'][0]['finish_reason'], 'stop')
        self.assertNotIn('refusal', result['choices'][0]['message'])
        self.assertEqual(result['_responsesApiRaw'], value)
        final['content'] = [{'type': 'refusal', 'refusal': 'final refusal'}]
        result = response_body(value)
        self.assertEqual(result['choices'][0]['message']['refusal'], 'final refusal')

    def test_multiple_final_unknown_phase_and_unphased_ambiguity_reject_without_guessing(self):
        for phases in (('final_answer', 'final_answer'), ('commentary', 'unknown', 'final_answer'),
                       ('final_answer', None), (None, None), ('commentary',), ('unknown',)):
            with self.subTest(phases=phases):
                value = native();base = value['output'][1]
                value['output'] = [{**copy.deepcopy(base), 'phase': phase} for phase in phases]
                result = response_body(value)
                self.assertNotEqual(result['choices'][0]['finish_reason'], 'stop')
                self.assertIsNone(result['choices'][0]['message']['content'])
                self.assertEqual(result['usage']['prompt_tokens'], 1000)
                self.assertEqual(result['_responsesApiRaw'], value)

    def test_incomplete_filters_tools_and_nonfinal_states_keep_native_usage(self):
        for status, reason, expected in (('incomplete', 'max_output_tokens', 'length'),
                                         ('incomplete', 'content_filter', 'content_filter'),
                                         ('incomplete', 'steered', 'unknown'),
                                         ('failed', None, 'unknown'), ('in_progress', None, 'unknown')):
            value = native();value['status'] = status
            value['incomplete_details'] = {'reason': reason} if reason else None
            result = response_body(value)
            self.assertEqual(result['choices'][0]['finish_reason'], expected)
            self.assertEqual(result['usage']['prompt_tokens'], 1000)
            self.assertEqual(result['_responsesApiRaw'], value)
        value = native();value['output'].append({'type': 'function_call', 'name': 'unsupported'})
        self.assertEqual(response_body(value)['choices'][0]['finish_reason'], 'tool_calls')

    def test_every_malformed_output_dict_still_returns_usage_and_one_nonstop_choice(self):
        for output in (None, [], {}, [None], [{'type': 'message', 'role': 'assistant', 'content': None}],
                       [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 42}]}]):
            value = native();value['output'] = output
            result = response_body(value)
            self.assertEqual(result['usage']['prompt_tokens'], 1000)
            self.assertEqual(result['usage']['prompt_tokens_details']['cache_write_tokens'], 300)
            self.assertEqual(len(result['choices']), 1)
            self.assertNotEqual(result['choices'][0]['finish_reason'], 'stop')
            self.assertEqual(result['_responsesApiRaw'], value)

    def test_invalid_usage_counts_are_not_converted_into_free_cache_or_valid_usage(self):
        value = native();value['usage']['input_tokens_details'] = {'cached_tokens': '1000', 'cache_write_tokens': -1}
        result = response_body(value)
        self.assertEqual(result['usage']['prompt_tokens_details'], {})
        self.assertEqual(result['choices'][0]['finish_reason'], 'unknown')
        self.assertEqual(result['_responsesApiRaw'], value)
        for count in (True, -1, '1000', None):
            value = native();value['usage']['input_tokens'] = count
            result = response_body(value)
            self.assertNotIn('prompt_tokens', result['usage'])
            self.assertEqual(result['choices'][0]['finish_reason'], 'unknown')


if __name__ == '__main__':
    unittest.main()
