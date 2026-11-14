"""Per-assignment response slots and lossless decoding; no judgement or retries."""
from __future__ import annotations

import copy
from pdf_quiz_study_contract import scoped_body_schema


_OWNED_FIELDS = ('type', 'unitId', 'targetId', 'conceptIds')


def _units(assignment):
    return assignment.get('units', [assignment]) if isinstance(assignment, dict) else []


def _target_ids(assignment):
    """Accept the original assignment or its wire form for admission sizing."""
    result = []
    for unit in _units(assignment):
        if not isinstance(unit, dict):
            return None
        targets = unit.get('targets')
        tasks = unit.get('tasks')
        if isinstance(targets, list):
            ids = [target.get('id') for target in targets if isinstance(target, dict)]
        elif isinstance(tasks, list):
            ids = [task.get('targetId') for task in tasks if isinstance(task, dict)]
        else:
            ids = unit.get('targetIds')
        if not isinstance(ids, list) or not ids:
            return None  # Count-only legacy assignments retain their array schema.
        result.extend(ids)
    if (not result or any(not isinstance(tid, str) or not tid for tid in result)
            or len(set(result)) != len(result)):
        return None
    return result


def scoped_question_schema(response_format, assignment):
    """Require each assigned target key, with one shared question definition."""
    ids = _target_ids(assignment)
    if not ids:
        return response_format
    result = copy.deepcopy(response_format)
    schema = result['json_schema']['schema']
    questions = schema['properties']['questions']
    if questions.get('type') != 'array':
        return result  # Already scoped; callers may calculate its bound directly.
    question = questions['items']
    for name in _OWNED_FIELDS:
        question['properties'].pop(name, None)
    question['required'] = [name for name in question['required'] if name not in _OWNED_FIELDS]
    schema.setdefault('$defs', {})['question'] = question
    kinds = {t['id']:t['type'] for u in _units(assignment) for t in u.get('targets', [])}
    kinds.update({t['targetId']:t['type'] for u in _units(assignment) for t in u.get('tasks', []) if 'type' in t})
    kinds = {k:v for k,v in kinds.items() if v in ('mcq','essay','ox')}
    for kind in sorted(set(kinds.values())):
        schema['$defs']['question_'+kind] = scoped_body_schema(question,kind)
    schema['properties']['questions'] = {
        'type': 'object',
        'properties': {tid: {'$ref': '#/$defs/question_'+kinds[tid] if tid in kinds else '#/$defs/question'} for tid in ids},
        'required': ids, 'additionalProperties': False,
    }
    return result


def decode_keyed_questions(raw, assignment):
    """Use app-owned metadata; keep missing, unknown and malformed output honest."""
    if not isinstance(raw, dict) or not isinstance(raw.get('questions'), dict):
        return copy.deepcopy(raw)  # Legacy array responses are never reinterpreted.
    targets = {}
    for unit in _units(assignment):
        for target in unit.get('targets', []):
            targets[target['id']] = {'type': target['type'], 'unitId': unit['unitId'],
                                     'targetId': target['id'], 'conceptIds': target['conceptIds']}
    result = copy.deepcopy(raw)
    result['questions'] = []
    for key, value in raw['questions'].items():
        question = copy.deepcopy(value) if isinstance(value, dict) else {'rawQuestion': copy.deepcopy(value)}
        warnings = []
        metadata = targets.get(key)
        if metadata is None:
            question['rawQuestion'] = copy.deepcopy(value)
            # Do not accept model-invented scope, even if its body looks valid.
            metadata = {'type': None, 'unitId': None, 'targetId': key, 'conceptIds': []}
            warnings.append('배정되지 않은 문항 키의 응답이에요. 생성 원문을 그대로 표시해요.')
        elif not isinstance(value, dict):
            warnings.append('문항 본문이 객체 형식이 아니에요. 생성 원문을 그대로 표시해요.')
        elif any(name in value and value[name] != metadata[name] for name in _OWNED_FIELDS):
            question['rawQuestion'] = copy.deepcopy(value)
            warnings.append('생성된 메타데이터 대신 앱의 원래 문항 배정을 연결했어요.')
        if warnings:
            existing = question.get('warnings', [])
            question['warnings'] = ([w for w in existing if isinstance(w, str)]
                                    if isinstance(existing, list) else []) + warnings
        question.update(copy.deepcopy(metadata))
        for unit in _units(assignment):
            for target in unit.get('targets', []):
                if target['id'] == key:
                    for field in ('profile','profileStatus','additionalJudgment','profileEvidenceSourceIds'):
                        if field in target: question[field] = copy.deepcopy(target[field])
        result['questions'].append(question)
    # Missing required keys remain missing: no invented question and no refill.
    return result
