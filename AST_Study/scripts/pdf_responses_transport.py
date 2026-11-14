"""Opt-in, single-study wire conversion; no transport, credentials or API calls.

Official references:
https://developers.openai.com/api/docs/guides/prompt-caching
https://developers.openai.com/api/reference/resources/responses/methods/create

Developer input_text blocks retain explicit cache breakpoints. A converted
response retains its complete native body under _responsesApiRaw; the caller
must persist that body before its existing completion/JSON validation can fail.
This adapter does not establish cache hits or equivalent generated semantics.
"""
from __future__ import annotations

import copy
import json
import math
import re


class ResponsesTransportError(ValueError):
    """This request cannot be represented by the narrow study-only pilot."""


def _object(value, where):
    if not isinstance(value, dict):
        raise ResponsesTransportError(where+' must be an object.')
    return value


def _keys(value, allowed, where, required=()):
    _object(value, where)
    if set(value)-set(allowed) or set(required)-set(value):
        raise ResponsesTransportError(where+' contains unsupported or missing fields.')


def _breakpoint(value):
    # Twelve-hour writes have a different price. This pilot preserves only the
    # existing default-lifetime explicit breakpoint, without changing billing.
    if value != {'mode': 'explicit'}:
        raise ResponsesTransportError('Only default-lifetime explicit cache breakpoints are supported.')
    return copy.deepcopy(value)


def _content(value, *, user):
    parts = [{'type': 'text', 'text': value}] if isinstance(value, str) else value
    if not isinstance(parts, list) or not parts:
        raise ResponsesTransportError('A study message needs nonempty text/image content.')
    result = []
    for part in parts:
        _object(part, 'message content')
        if part.get('type') == 'text':
            _keys(part, ('type', 'text', 'prompt_cache_breakpoint'), 'text content', ('type', 'text'))
            if not isinstance(part['text'], str):
                raise ResponsesTransportError('Text content must remain a string.')
            converted = {'type': 'input_text', 'text': part['text']}
        elif user and part.get('type') == 'image_url':
            _keys(part, ('type', 'image_url', 'prompt_cache_breakpoint'), 'image content', ('type', 'image_url'))
            image = part['image_url']
            _keys(image, ('url', 'detail'), 'image URL', ('url',))
            if not isinstance(image['url'], str) or not image['url']:
                raise ResponsesTransportError('Image URLs must remain nonempty strings.')
            converted = {'type': 'input_image', 'image_url': image['url']}
            if 'detail' in image:
                if image['detail'] not in ('auto', 'low', 'high'):
                    raise ResponsesTransportError('The image detail setting is unsupported.')
                converted['detail'] = image['detail']
        else:
            raise ResponsesTransportError('Only study text and user image URLs are supported.')
        if 'prompt_cache_breakpoint' in part:
            converted['prompt_cache_breakpoint'] = _breakpoint(part['prompt_cache_breakpoint'])
        result.append(converted)
    return result


def _study_payload(parts, *, allow_outline=False):
    if not parts or parts[0].get('type') != 'input_text':
        raise ResponsesTransportError('The original study payload must precede its images.')
    try:
        payload = json.loads(parts[0]['text'])
    except (ValueError, TypeError):
        raise ResponsesTransportError('The user input must retain its original JSON study payload.') from None
    if (not isinstance(payload, dict) or payload.get('taskType') == 'tutor' or
            payload.get('task') not in (('region_teaching', 'region_teaching_batch','region_groups','lecture_flow_from_planned_units')
                                       if allow_outline else ('region_teaching', 'region_teaching_batch','region_groups'))):
        raise ResponsesTransportError('Only a single study generation is supported, not tutor or other operations.')
    if payload['task'] == 'region_teaching_batch':
        units = payload.get('units')
        if (not isinstance(units, dict) or not 2 <= len(units) <= 4 or
                set(units) != {f'u{i}' for i in range(len(units))} or
                any(not isinstance(unit, dict) or unit.get('task') != 'region_teaching' or
                    unit.get('taskType') == 'tutor' for unit in units.values())):
            raise ResponsesTransportError('Every batched input must remain an independent original study unit.')


def request_body(chat_body, *, allow_outline=False):
    """Convert one supported Chat request without editing source/text/schema/pixels."""
    _keys(chat_body, ('model', 'messages', 'store', 'response_format', 'max_completion_tokens',
                     'reasoning_effort', 'temperature', 'prompt_cache_options'), 'study request',
          ('model', 'messages', 'store', 'response_format', 'max_completion_tokens', 'reasoning_effort'))
    if not isinstance(chat_body['model'], str) or not chat_body['model'] or type(chat_body['store']) is not bool:
        raise ResponsesTransportError('The original model and boolean store setting are required.')
    maximum = chat_body['max_completion_tokens']
    if type(maximum) is not int or maximum < 1 or chat_body['reasoning_effort'] not in ('none','low'):
        raise ResponsesTransportError('Study transport supports positive output limits and none/low reasoning.')
    messages = chat_body['messages']
    if (not isinstance(messages, list) or len(messages) != 2 or
            any(not isinstance(message, dict) for message in messages) or
            messages[0].get('role') not in ('system', 'developer') or messages[1].get('role') != 'user'):
        raise ResponsesTransportError('Only one developer instruction and one study input are supported.')
    inputs = []
    for index, message in enumerate(messages):
        _keys(message, ('role', 'content'), 'study message', ('role', 'content'))
        inputs.append({'role': 'developer' if index == 0 else 'user',
                       'content': _content(message['content'], user=index == 1)})
    _study_payload(inputs[1]['content'],allow_outline=allow_outline)
    if sum('prompt_cache_breakpoint' in part for message in inputs for part in message['content']) > 4:
        raise ResponsesTransportError('The request exceeds the four supported cache breakpoints.')
    format = chat_body['response_format']
    _keys(format, ('type', 'json_schema'), 'response format', ('type', 'json_schema'))
    if format['type'] != 'json_schema':
        raise ResponsesTransportError('A study JSON-schema response format is required.')
    wrapper = format['json_schema']
    _keys(wrapper, ('name', 'schema', 'strict'), 'JSON schema format', ('name', 'schema', 'strict'))
    if (not isinstance(wrapper['name'], str) or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', wrapper['name']) is None or
            not isinstance(wrapper['schema'], dict) or type(wrapper['strict']) is not bool):
        raise ResponsesTransportError('The original schema, name and strict setting must remain valid.')
    result = {'model': chat_body['model'], 'store': chat_body['store'], 'input': inputs,
              'text': {'format': {'type': 'json_schema', **copy.deepcopy(wrapper)}},
              'max_output_tokens': maximum, 'reasoning': {'effort': chat_body['reasoning_effort']}}
    if 'temperature' in chat_body:
        value = chat_body['temperature']
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 2:
            raise ResponsesTransportError('The temperature setting must be a finite number from zero to two.')
        result['temperature'] = value
    if 'prompt_cache_options' in chat_body:
        if chat_body['prompt_cache_options'] != {'mode': 'explicit'}:
            raise ResponsesTransportError('Only the existing default-lifetime explicit cache mode is supported.')
        result['prompt_cache_options'] = copy.deepcopy(chat_body['prompt_cache_options'])
    return result


def _count(value):
    return type(value) is int and value >= 0


def _usage(value, diagnostics):
    if value is None:
        return None
    if not isinstance(value, dict):
        diagnostics.append('invalid_usage_object')
        return None
    result = {}
    for native, chat in (('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')):
        if _count(value.get(native)):
            result[chat] = value[native]
        else:
            diagnostics.append('invalid_'+native)
    for native, chat, maximum in (('input_tokens_details', 'prompt_tokens_details', result.get('prompt_tokens')),
                                 ('output_tokens_details', 'completion_tokens_details', result.get('completion_tokens'))):
        if native not in value or value[native] is None:
            continue
        details = value[native]
        if not isinstance(details, dict):
            diagnostics.append('invalid_'+native)
            continue
        copied = copy.deepcopy(details)
        for field in ('cached_tokens', 'cache_write_tokens') if native == 'input_tokens_details' else ('reasoning_tokens',):
            if field in copied and (not _count(copied[field]) or maximum is not None and copied[field] > maximum):
                # Omit malformed cache counts rather than invent free cached
                # input. The native count remains intact in _responsesApiRaw;
                # missing write counts retain the audit's conservative bound.
                copied.pop(field)
                diagnostics.append('invalid_'+field)
        result[chat] = copied
    if _count(value.get('total_tokens')):
        result['total_tokens'] = value['total_tokens']
    elif 'prompt_tokens' in result and 'completion_tokens' in result:
        result['total_tokens'] = result['prompt_tokens'] + result['completion_tokens']
    return result


def response_body(native):
    """Normalize even malformed native dictionaries so usage is settled first.

    An anomalous output never becomes a logical successful completion. The
    existing Provider receives one safe choice and reaches its usual incomplete
    guard after recording usage; the complete native body is retained verbatim.
    """
    _object(native, 'Responses response')
    diagnostics = []
    usage = _usage(native.get('usage'), diagnostics)
    texts, refusals = [], []
    output = native.get('output')
    messages = []
    tool_output = False
    if not isinstance(output, list):
        diagnostics.append('invalid_output_array')
        output = []
    for item in output:
        if not isinstance(item, dict):
            diagnostics.append('invalid_output_item')
            continue
        kind = item.get('type')
        if kind == 'reasoning':
            continue  # Hidden reasoning is preserved natively, not learner text.
        if kind != 'message':
            tool_output |= isinstance(kind, str) and kind.endswith('_call')
            diagnostics.append('unsupported_output_item')
            continue
        messages.append(item)
        if item.get('role') != 'assistant':
            diagnostics.append('invalid_output_message')
    # Some Responses models return commentary before a final answer. Joining
    # those messages invents a different document (or invalid concatenated
    # JSON). Select only an explicit, unambiguous final phase; never choose the
    # last parseable object or reinterpret commentary as the requested answer.
    phases = [item.get('phase') for item in messages]
    if len(messages) == 1 and phases[0] is None:
        selected = messages
    elif (messages and all(phase in ('commentary', 'final_answer') for phase in phases)
          and phases.count('final_answer') == 1):
        selected = [item for item in messages if item['phase'] == 'final_answer']
    else:
        selected = []
        diagnostics.append('ambiguous_or_missing_final_output_phase')
    for item in selected:
        if item.get('status') not in (None, 'completed'):
            diagnostics.append('invalid_output_message_status')
        content = item.get('content')
        if not isinstance(content, list):
            diagnostics.append('invalid_output_content')
            continue
        for part in content:
            if not isinstance(part, dict):
                diagnostics.append('invalid_output_part')
            elif part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                texts.append(part['text'])
            elif part.get('type') == 'refusal' and isinstance(part.get('refusal'), str):
                refusals.append(part['refusal'])
            else:
                diagnostics.append('unsupported_or_invalid_output_part')
    if not selected or not any(texts + refusals):
        diagnostics.append('missing_output_message')
    status = native.get('status')
    details = native.get('incomplete_details')
    reason = details.get('reason') if isinstance(details, dict) else None
    if status == 'incomplete' and reason == 'max_output_tokens':
        finish = 'length'
    elif status == 'incomplete' and reason == 'content_filter':
        finish = 'content_filter'
    elif tool_output:
        finish = 'tool_calls'
    elif status == 'completed' and not diagnostics and native.get('error') is None and details is None:
        finish = 'stop'
    else:
        finish = 'unknown'
    message = {'role': 'assistant', 'content': ''.join(texts) if texts else None}
    if refusals:
        message['refusal'] = ''.join(refusals)
    result = {'choices': [{'message': message, 'finish_reason': finish}],
              'usage': usage, '_responsesApiRaw': copy.deepcopy(native)}
    if isinstance(native.get('service_tier'),str):result['service_tier']=native['service_tier']
    if diagnostics:
        result['_responsesTransportDiagnostics'] = diagnostics
    return result
