"""Generation-only construction; persisted questions retain the existing UI shape.

Correct choice content has one origin. These transformations never judge
meaning, remove questions, or call a model.
"""
from __future__ import annotations

import copy
from pdf_quiz_study_contract import project_answers


def generation_schema(schema):
    schema = copy.deepcopy(schema)
    question = schema['properties']['questions']['items']
    properties = question['properties']
    # Separate supporting material from the actual task within this existing call.
    question['properties'] = {'passage': {'type': 'string',
        'description': 'Student-visible supporting material/conditions only; empty if unnecessary. Never give away the judgment.'}, **properties}
    properties = question['properties']
    properties['stem']['description'] = 'The explicit question or OX proposition only, separate from passage. Do not repeat selectable options or the O/X UI guide.'
    question['required'].append('passage')
    calculations = {'type': 'array', 'items': {'type': 'object',
        'properties': {'name': {'type': 'string'}, 'expression': {'type': 'string'}},
        'required': ['name', 'expression'], 'additionalProperties': False}, 'maxItems': 64}
    question['properties'] = {'calculations': calculations, **properties}
    properties = question['properties']
    question['required'].append('calculations')
    option = properties.pop('options')
    option['maxItems'] = 3
    option['items']['properties'].pop('id')
    option['items']['required'].remove('id')
    properties['distractors'] = option
    question['required'] = [k for k in question['required'] if k != 'options'] + ['distractors']
    return schema


def assemble_answers(raw):
    result = project_answers(raw)
    if not isinstance(result, dict) or not isinstance(result.get('questions'), list):
        return result
    for question in result['questions']:
        if not isinstance(question, dict):
            continue
        passage = question.get('passage')
        stem = question.get('stem')
        if isinstance(passage, str) and isinstance(stem, str) and stem.strip():
            # Persist the established stem field, retaining explicit section boundaries.
            title = '판단할 진술' if question.get('type') == 'ox' else '문제'
            question['stem'] = ((f'### 제시문\n{passage.strip()}\n\n' if passage.strip() else '')
                                + f'### {title}\n{stem.strip()}')
            question.pop('passage')  # Idempotent; legacy stems are never guessed or rewritten.
        if 'distractors' not in question:
            continue  # Older stored responses keep their original contract.
        distractors = question['distractors']
        # Preserve malformed source choices for the lossless publication fallback.
        question['options'] = None
        if not isinstance(distractors, list):
            continue
        if question.get('type') != 'mcq':
            if not distractors:
                question['options'] = []
                question.pop('distractors')
            continue
        if (len(distractors) != 3 or any(not isinstance(o, dict)
                or set(o) != {'text', 'explanation'} for o in distractors)):
            continue
        question['options'] = [
            {'id': 'A', 'text': question.get('answer'), 'explanation': question.get('explanation')},
            *[{'id': oid, **choice} for oid, choice in zip('BCD', distractors)]]
        question['answer'] = 'A'
        question.pop('distractors')
    return result
