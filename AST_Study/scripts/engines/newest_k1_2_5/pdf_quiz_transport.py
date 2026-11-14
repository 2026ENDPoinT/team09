"""Pack API transport while preserving each logical quiz assignment's scope.

An input unit is already small enough after ``fitting_batches``. Packing only
shares request overhead and repeated sources; it never merges teaching targets
or widens a question's source scope. Types and counts guide generation;
returned surplus is published without quota filtering.
"""
from __future__ import annotations

import copy


def _job(units, index):
    if len(units) == 1:
        return units[0]
    from pdf_quiz import TYPES

    return {
        'unitId': f'transport-{index}',
        'conceptIds': list(dict.fromkeys(cid for unit in units for cid in unit['conceptIds'])),
        'counts': {kind: sum(unit['counts'][kind] for unit in units) for kind in TYPES},
        'focus': '독립 배정은 units를 각각 준수한다.',
        'units': copy.deepcopy(units),
    }


def pack_generation_jobs(assignments, payload_for, prompt, response_format, limit):
    """Greedily pack consecutive units within the real input and output bounds.

    Single-unit jobs keep their original object and fields. A unit that does not
    fit by itself is a caller error: splitting or omitting source text here would
    silently change the already-approved logical assignment.
    """
    from pdf_quiz import MAX_BATCH_QUESTIONS, input_bound

    jobs, pending = [], []
    for assignment in assignments:
        if (sum(assignment['counts'].values()) > MAX_BATCH_QUESTIONS
                or input_bound(payload_for(assignment), prompt, response_format) > limit):
            raise ValueError('입력·출력 한도를 넘는 단일 배정은 먼저 분할해야 해요.')
        proposed = _job(pending + [assignment], len(jobs))
        if pending and (sum(proposed['counts'].values()) > MAX_BATCH_QUESTIONS
                        or input_bound(payload_for(proposed), prompt, response_format) > limit):
            jobs.append(_job(pending, len(jobs)))
            pending = [assignment]
        else:
            pending.append(assignment)
    if pending:
        jobs.append(_job(pending, len(jobs)))
    return jobs


def validate_job(raw, job, concepts, sources, previous_stems, diagnostics=None):
    """Validate each tagged question against its original unit, not the union.

    The response's ``unfilled`` belongs to the transport job as a whole. Check
    its contract once; the number of readable, source-linked questions determines
    the caller's final unfilled count, even if the model's bookkeeping is wrong.
    Identical stems and surplus questions are not discarded.
    """
    from pdf_quiz import _number, validate_questions

    if 'units' not in job:
        return validate_questions(raw, job, concepts, sources, previous_stems, diagnostics)
    if not isinstance(raw, dict) or not isinstance(raw.get('questions'), list):
        raise ValueError('문제 생성 응답 형식이 올바르지 않아요.')

    units = job['units']
    if not isinstance(units, list) or not units:
        raise ValueError('전송 묶음의 원래 배정이 비어 있어요.')
    ids = [unit.get('unitId') if isinstance(unit, dict) else None for unit in units]
    if (any(not isinstance(uid, str) or not uid.strip() for uid in ids)
            or len(ids) != len(set(ids))):
        raise ValueError('전송 묶음의 원래 배정 ID가 올바르지 않아요.')
    by_unit = {uid: [] for uid in ids}
    accepted, rejected = [], 0
    for question in raw['questions']:
        uid = question.get('unitId') if isinstance(question, dict) else None
        if not isinstance(uid, str) or uid not in by_unit:
            from pdf_quiz_publish import preserve_question
            accepted.append(preserve_question(question, job, concepts, sources, '문항의 배정 ID를 확인하지 못했어요.'))
            if diagnostics is not None:
                diagnostics.append({'unitId': uid, 'reason': '문항 배정 ID 불일치', 'action': 'shown_with_warning'})
            continue
        by_unit[uid].append(question)
    for unit in units:
        questions, invalid = validate_questions(
            {'questions': by_unit[unit['unitId']], 'unfilled': 0, 'reason': ''},
            unit, concepts, sources, previous_stems, diagnostics)
        accepted.extend(questions)
        rejected += invalid
    return accepted, rejected
