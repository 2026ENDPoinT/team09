"""Plan question objectives once, generate in parallel and publish without top-ups.

Only the existing structural/source contract is checked; no duplicate gate or AI review.
"""
from __future__ import annotations

from concurrent.futures import CancelledError, FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import nullcontext
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import threading
import uuid

from pdf_pipeline import check_cancel, emit, write_json
from pdf_quiz_review import shuffle_display_options
from pdf_quiz_targets import (balanced_counts, target_plan, scoped_targets, target_index,
                              wire_assignment, interleave_questions)
from pdf_quiz_transport import pack_generation_jobs, validate_job
from pdf_quiz_sources import wire_generation_payload, resolve_generation_quotes
from pdf_quiz_grounding import transcription_index, recover_transcriptions
from pdf_quiz_response import generation_schema, assemble_answers
from pdf_quiz_calculations import render_calculations
from pdf_quiz_keyed import scoped_question_schema, decode_keyed_questions
from pdf_quiz_difficulty import difficulty_instruction
from pdf_quiz_profiles import planning_evidence, policy, apply_profile_plan

PROMPTS = Path(__file__).resolve().parent / 'prompts' / 'quiz-v2'
VERSION = 'quiz-v4.13-explicit-passage-question'
QUIZ_PLAN_EFFORT = 'high'
QUIZ_GENERATION_EFFORT = 'low'
TYPES = ('ox', 'mcq', 'word', 'essay')
THEMES = {'concept_completion': 'concept-completion.md', 'understanding': 'understanding.md',
          'practice_set': 'practice-set.md', 'recall': 'recall.md'}
# Luna's documented per-response ceiling (2026-10-23). A requested 500k
# output is unsupported; keep transport packing independent of this ceiling.
MAX_OUTPUT_TOKENS = 128000
OUTPUT_TOKENS_PER_QUESTION = 1500
MAX_BATCH_QUESTIONS = 4
MAX_PARALLEL_GENERATIONS = 10


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _objects(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _number(value, minimum=0, maximum=120):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('문항 수가 올바르지 않아요.')
    return value


def settings(request):
    value = request.get('quiz')
    if not isinstance(value, dict) or value.get('theme') not in THEMES:
        raise ValueError('문제 테마를 선택해 주세요.')
    count = _number(value.get('totalCount'), 1)
    allowed = value.get('allowedTypes')
    if (not isinstance(allowed, list) or not allowed or any(t not in TYPES for t in allowed)
            or len(set(allowed)) != len(allowed)):
        raise ValueError('문제 형식을 하나 이상 선택해 주세요.')
    if value.get('difficulty') not in ('중', '중상', '상', '최상'):
        raise ValueError('문제 난이도가 올바르지 않아요.')
    instructions = value.get('instructions', '')
    if not isinstance(instructions, str) or len(instructions) > 2000:
        raise ValueError('추가 요청은 2,000자 이내로 작성해 주세요.')
    return {'theme': value['theme'], 'totalCount': count, 'difficulty': value['difficulty'],
            'allowedTypes': [t for t in TYPES if t in allowed],
            'instructions': instructions.strip(),
            'typeCounts': balanced_counts(count, allowed, value['theme'])}


def context(document, request):
    """Reuse Java's actual concept groups, rather than duplicating UI placement."""
    config = settings(request)
    study = request.get('studyContent')
    if not isinstance(study, dict) or not _objects(study.get('concepts')):
        raise ValueError('먼저 개념 탭의 학습 내용을 생성해 주세요.')
    if study.get('documentId') != document.get('documentId'):
        raise ValueError('현재 PDF의 개념으로만 문제를 만들 수 있어요.')
    fingerprints = {document.get('fingerprint'), *document.get('legacySourceFingerprints', [])}
    if study.get('sourceFingerprint') and study['sourceFingerprint'] not in fingerprints:
        raise ValueError('PDF가 바뀌었어요. 개념을 다시 생성해 주세요.')
    page_count = len(document.get('pages', []))
    first, last = request.get('startPage', 1), request.get('endPage', page_count)
    if type(first) is not int or type(last) is not int or not 1 <= first <= last <= page_count:
        raise ValueError('출제할 PDF 페이지 범위를 확인해 주세요.')
    native = {c['id']: c for c in _objects(document.get('chunks'))
              if _text(c.get('id')) and _text(c.get('text')) and c.get('source') != 'ocr'}
    cards = _objects(study.get('concepts'))
    transcriptions = transcription_index(document)
    concepts, sources, sizes = {}, {}, {}
    for index, card in enumerate(cards):
        cid, title = 'c' + str(index + 1), _text(card.get('name'))
        if not title:
            continue
        source_ids = []
        primary_titles, fully_grounded = [], True
        entries = _objects(card.get('entries')) or [card]
        for number, entry in enumerate(entries):
            evidence = _objects(entry.get('evidence'))
            entry_pages = {e['page'] for e in evidence if type(e.get('page')) is int and e['page'] > 0}
            entry_pages.update(native[e['sourceId']]['page'] for e in evidence
                               if e.get('sourceId') in native
                               and type(native[e['sourceId']].get('page')) is int)
            if not entry_pages:
                entry_pages.update(p for p in entry.get('visualPages', []) if type(p) is int and p > 0)
            if not entry_pages:
                entry_pages.update(p for p in card.get('pages', []) if type(p) is int and p > 0)
            if not entry_pages and (first != 1 or last != page_count):
                continue
            if entry_pages and not any(first <= p <= last for p in entry_pages):
                continue
            recovered, covered = recover_transcriptions(evidence, transcriptions, first, last, document['documentId'])
            fully_grounded = fully_grounded and covered
            for chunk in recovered:
                ref = chunk['id']
                sources[ref] = {'sourceId': ref, 'text': chunk['text'], 'sourceKind': 'ai_transcription',
                                'pages': [chunk['page']], 'originalSourceIds': [ref], 'standardKnowledgeUsed': False}
                source_ids.append(ref)
                if _text(chunk.get('elementTitle')):
                    primary_titles.append(chunk['elementTitle'].strip())
            if covered:
                # Do not send a potentially distorted paraphrase alongside all
                # of its recovered primary passages, or inherit its rule title.
                continue
            # Easy explanations can contain analogies and added background. The
            # assessable material is the saved definition/explanation only.
            fields = list(dict.fromkeys(v for key in ('definition', 'explanation')
                                       if (v := _text(entry.get(key)))))
            body = '\n\n'.join(fields)
            if not body:
                continue
            sid = f'study:{cid}:e{number + 1}'
            original = list(dict.fromkeys(e['sourceId'] for e in evidence if _text(e.get('sourceId'))))
            source = {'sourceId': sid, 'text': body, 'sourceKind': 'saved_concept',
                      'originalSourceIds': original,
                      'pages': sorted(entry_pages, key=lambda p: (not first <= p <= last, p)),
                      'standardKnowledgeUsed': entry.get('standardKnowledgeUsed') is True}
            sources[sid] = source
            source_ids.append(sid)
            for ref in original:
                chunk = native.get(ref)
                if chunk is not None and (type(chunk.get('page')) is not int or first <= chunk['page'] <= last):
                    sources[ref] = {'sourceId': ref, 'text': chunk['text'],
                                    'sourceKind': chunk.get('source', 'native'),
                                    'pages': [chunk['page']] if type(chunk.get('page')) is int else [],
                                    'originalSourceIds': [ref], 'standardKnowledgeUsed': False}
                    source_ids.append(ref)
        if source_ids:
            ids = list(dict.fromkeys(source_ids))
            if fully_grounded and primary_titles:
                title = ' · '.join(dict.fromkeys(primary_titles))
            concepts[cid] = {'id': cid, 'title': title, 'sourceIds': ids}
            sizes[cid] = sum(len(sources[s]['text']) for s in ids)

    outline, catalog, assigned = [], [], set()
    groups = _objects(request.get('studyGroups'))
    if not groups:
        groups = [{'id': 'all', 'title': '전체 개념', 'conceptIndexes': list(range(len(cards)))}]
    # Missing cards retain their own fallback group; duplicate membership never
    # sends a concept twice to the planner.
    used = {i for g in groups for i in g.get('conceptIndexes', []) if type(i) is int and 0 <= i < len(cards)}
    missing = [i for i in range(len(cards)) if i not in used]
    if missing:
        groups.append({'id': 'unplaced', 'title': '기타 개념', 'conceptIndexes': missing})
    for ordinal, group in enumerate(groups):
        indexes = group.get('conceptIndexes')
        if not isinstance(indexes, list) or any(type(i) is not int or not 0 <= i < len(cards) for i in indexes):
            raise ValueError('개념 목차의 소속 정보가 올바르지 않아요.')
        members = []
        for index in indexes:
            cid = 'c' + str(index + 1)
            if cid in assigned:
                continue
            assigned.add(cid)
            title = concepts[cid]['title'] if cid in concepts else _text(cards[index].get('name'))
            if title:
                members.append({'id': cid, 'title': title})
        if not members:
            continue
        group_id = f'g{ordinal + 1}'
        heading = {'id': group_id, 'title': _text(group.get('title')) or '개념', 'concepts': members}
        path = [{'id': _text(p.get('id')), 'title': _text(p.get('title'))}
                for p in _objects(group.get('path')) if _text(p.get('title'))]
        if path:
            heading['path'] = path
        outline.append(heading)
        for member in members:
            cid = member['id']
            if cid not in concepts:
                continue
            source_bytes = len(json.dumps([sources[s] for s in concepts[cid]['sourceIds']],
                                         ensure_ascii=False).encode('utf-8'))
            catalog.append({**member, 'sectionId': group_id, 'bodyChars': sizes[cid], 'sourceBytes': source_bytes})
    if not catalog:
        raise ValueError('선택한 범위에 출제할 개념 내용이 없어요.')
    return config, outline, catalog, concepts, sources


def _schema(name):
    schema = json.loads((PROMPTS / (name + '.schema.json')).read_text(encoding='utf-8'))
    if name == 'questions':
        item = schema['properties']['questions']['items']
        item['properties']['unitId'] = {'type': 'string'}
        item['required'].append('unitId')
        item['properties']['targetId'] = {'type': 'string'}
        item['required'].append('targetId')
        item['properties']['evidence']['items'] = {
            'type': 'object', 'properties': {'sourceId': {'type': 'string'}, 'quoteId': {'type': 'string'}},
            'required': ['sourceId','quoteId'], 'additionalProperties': False}
        schema = generation_schema(schema)
    return {'type': 'json_schema', 'json_schema': {'name': 'quiz_' + name, 'strict': True,
            'schema': schema}}


def validate_plan(value, catalog, config):
    known = {c['id'] for c in catalog}
    if (not isinstance(value, dict) or not isinstance(value.get('allocations'), list)
            or not isinstance(value.get('reason'), str)):
        raise ValueError('출제 배분 응답 형식이 올바르지 않아요.')
    if value['allocations'] and any('targets' in a for a in value['allocations'] if isinstance(a, dict)):
        return target_plan(value, catalog, config)
    remaining = _number(value.get('unallocated'))
    if remaining > config['totalCount']:
        raise ValueError('미배분 문항 수가 요청한 총문항 수보다 많아요.')
    total, seen, allocations = 0, set(), []
    for assignment in value['allocations']:
        if not isinstance(assignment, dict) or not _text(assignment.get('unitId')):
            raise ValueError('출제 배분의 묶음 ID가 비어 있어요.')
        uid, ids = assignment['unitId'], assignment.get('conceptIds')
        if (uid in seen or not isinstance(ids, list) or not ids or len(set(ids)) != len(ids)
                or any(c not in known for c in ids)):
            raise ValueError('출제 배분의 개념 범위가 올바르지 않아요.')
        seen.add(uid)
        counts = assignment.get('counts')
        if not isinstance(counts, dict) or set(counts) != set(TYPES):
            raise ValueError('출제 배분의 형식별 수가 올바르지 않아요.')
        amount = sum(_number(counts[t]) for t in TYPES)
        if any(counts[t] for t in TYPES if t not in config['allowedTypes']):
            raise ValueError('선택하지 않은 문제 형식이 배분됐어요.')
        if amount == 0:
            continue  # Empty rows do not invalidate otherwise usable scopes.
        if not _text(assignment.get('focus')):
            raise ValueError('출제 배분의 초점이 비어 있어요.')
        total += amount
        allocations.append(copy.deepcopy(assignment))

    result = copy.deepcopy(value)
    result.pop('countAdjustment', None)
    result['allocations'] = allocations
    target = config['totalCount'] - remaining
    if total == target:
        return result
    if not total and target:
        raise ValueError('문항 수를 배분할 출제 묶음이 없어요.')

    def apportion(weights, amount, preserve_groups=False):
        if not amount:
            return [0] * len(weights)
        denominator = sum(weights)
        shares = [amount * weight // denominator for weight in weights]
        residues = [amount * weight % denominator for weight in weights]
        for index in sorted(range(len(weights)), key=lambda i: (-residues[i], i))[:amount - sum(shares)]:
            shares[index] += 1
        # Preserve each valid group when there are enough questions, without
        # using floating point or changing the planner's concept membership.
        if preserve_groups and amount >= len(weights):
            for index in range(len(weights)):
                if shares[index]:
                    continue
                donor = max((i for i, count in enumerate(shares) if count > 1),
                            key=lambda i: (shares[i] * denominator - amount * weights[i], -i))
                shares[donor] -= 1
                shares[index] = 1
        return shares

    group_counts = apportion([sum(a['counts'].values()) for a in allocations], target, True)
    adjusted = []
    for assignment, amount in zip(allocations, group_counts):
        if not amount:
            continue
        kinds = [kind for kind in TYPES if assignment['counts'][kind]]
        shares = apportion([assignment['counts'][kind] for kind in kinds], amount)
        assignment['counts'] = dict.fromkeys(TYPES, 0)
        assignment['counts'].update(zip(kinds, shares))
        adjusted.append(assignment)
    result['allocations'] = adjusted
    result['countAdjustment'] = {'allocatedBefore': total, 'allocatedAfter': target}
    return result


def batches(plan):
    for assignment in plan['allocations']:
        if 'targets' in assignment:
            slots = assignment['targets']
            for start in range(0, len(slots), MAX_BATCH_QUESTIONS):
                uid = assignment['unitId']
                if len(slots) > MAX_BATCH_QUESTIONS:
                    uid += f'/batch-{start // MAX_BATCH_QUESTIONS}'
                yield scoped_targets(assignment, slots[start:start + MAX_BATCH_QUESTIONS], uid)
            continue
        rest = dict(assignment['counts'])
        split = sum(rest.values()) > MAX_BATCH_QUESTIONS
        batch_index = 0
        while sum(rest.values()):
            counts = dict.fromkeys(TYPES, 0)
            # Round-robin avoids exhausting one format in every early batch.
            while sum(counts.values()) < MAX_BATCH_QUESTIONS and sum(rest.values()):
                for kind in TYPES:
                    if rest[kind] and sum(counts.values()) < MAX_BATCH_QUESTIONS:
                        counts[kind] += 1
                        rest[kind] -= 1
            uid = assignment['unitId'] + f'/batch-{batch_index}' if split else assignment['unitId']
            yield {**assignment, 'unitId': uid, 'counts': counts}
            batch_index += 1


def input_bound(payload, system_prompt, response_format):
    """The provider's text-only admission bound, without truncating any source."""
    if payload.get('task') == 'quiz_questions':
        scope = payload.get('assignment')
        if isinstance(payload.get('tasks'), list):
            scope = {'tasks': payload['tasks']}
        response_format = scoped_question_schema(response_format, scope)
    user_text = json.dumps(payload, ensure_ascii=False)
    messages = [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_text}]
    return (len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 2048
            + len(json.dumps(response_format).encode('utf-8')))


def generation_payload(config, outline, plan, assignment, concepts, sources, previous, run_id):
    selected = [concepts[c] for c in assignment['conceptIds']]
    selected_sources = list(dict.fromkeys(s for c in selected for s in c['sourceIds']))
    request = {key: value for key, value in config.items() if key not in ('totalCount', 'typeCounts')}
    assigned = wire_assignment(assignment)
    owned = {task['targetId'] for task in assigned.get('tasks', [])}
    payload = {'task': 'quiz_questions', 'requestId': run_id, 'request': request, 'outline': outline,
            'sharedTargets': [row for row in target_index(plan) if row[0] not in owned],
            'assignment': assigned, 'studyPurpose': policy(config['totalCount'],config['theme'])['purpose'], 'concepts': selected,
            'sources': [sources[s] for s in selected_sources],
            'referenceQuestions': [], 'previousTargets': previous[-30:]}
    return payload


def fitting_batches(assignment, payload_for, prompt, response_format, limit):
    """Split only a real input overflow; never enforce a concept/character cap.

    A one-question integrative target cannot be split across two calls without
    changing the target. Keep it unfilled rather than silently dropping sources.
    """
    if input_bound(payload_for(assignment), prompt, response_format) <= limit:
        yield assignment
        return
    if 'targets' in assignment:
        slots = assignment['targets']
        if len(slots) < 2:
            raise ValueError('출제 문항의 본문이 모델의 입력 한도를 넘어요.')
        middle = len(slots) // 2
        for suffix, members in (('L', slots[:middle]), ('R', slots[middle:])):
            child = scoped_targets(assignment, members, assignment['unitId'] + '/context-' + suffix)
            yield from fitting_batches(child, payload_for, prompt, response_format, limit)
        return
    ids, amount = assignment['conceptIds'], sum(assignment['counts'].values())
    if len(ids) < 2 or amount < 2:
        raise ValueError('출제 묶음 본문이 모델의 입력 한도를 넘어요.')
    middle = len(ids) // 2
    left_amount = max(1, min(amount - 1, round(amount * middle / len(ids))))
    left, right = dict.fromkeys(TYPES, 0), dict(assignment['counts'])
    while sum(left.values()) < left_amount:
        for kind in TYPES:
            if right[kind] and sum(left.values()) < left_amount:
                left[kind] += 1
                right[kind] -= 1
    for suffix, members, counts in (('L', ids[:middle], left), ('R', ids[middle:], right)):
        child = {**assignment, 'unitId': assignment['unitId'] + '/context-' + suffix,
                 'conceptIds': members, 'counts': counts}
        yield from fitting_batches(child, payload_for, prompt, response_format, limit)


def _quote_key(value):
    return re.sub(r'\s+', ' ', value).strip()


def _question(value, assignment, concepts, sources):
    if not isinstance(value, dict) or value.get('type') not in TYPES:
        raise ValueError('문항 형식이 올바르지 않아요.')
    if value.get('answerContractError'):
        raise ValueError(value['answerContractError'])
    kind, ids = value['type'], value.get('conceptIds')
    if (not isinstance(ids, list) or not ids or any(c not in assignment['conceptIds'] for c in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('문항이 배정된 개념 범위를 벗어났어요.')
    if any(not _text(value.get(key)) for key in ('stem', 'answer', 'explanation')):
        raise ValueError('문항의 질문·답안·해설이 비어 있어요.')
    options, points = value.get('options'), value.get('keyPoints')
    if (not isinstance(options, list) or not isinstance(points, list)
            or any(not _text(point) for point in points)):
        raise ValueError('문항의 선택지 또는 비교 항목이 올바르지 않아요.')
    if kind == 'mcq':
        if (len(options) != 4 or any(not isinstance(o, dict) for o in options)
                or {o.get('id') for o in options} != set('ABCD')
                or value['answer'] not in set('ABCD')
                or len({_quote_key(_text(o.get('text'))) for o in options}) != 4
                or any(not _text(o.get('text')) or not _text(o.get('explanation')) for o in options)):
            raise ValueError('4지선다의 선택지와 정답이 올바르지 않아요.')
    elif options or kind == 'ox' and value['answer'] not in ('O', 'X'):
        raise ValueError('문항 형식에 맞는 답안이 아니에요.')
    if kind == 'essay' and not points:
        raise ValueError('서술형 비교 항목이 올바르지 않아요.')
    evidence = value.get('evidence')
    if not isinstance(evidence, list) or not evidence:
        raise ValueError('문항의 근거가 비어 있어요.')
    enriched = []
    # A question may use any assigned concept, but not another unit's source.
    ids = list(ids)
    for item in evidence:
        if isinstance(item, dict) and item.get('sourceId') in sources:
            owners = [c for c in assignment['conceptIds'] if item['sourceId'] in concepts[c]['sourceIds']]
            if owners and not any(c in ids for c in owners):
                ids.append(owners[0])
    allowed_sources = {s for c in ids for s in concepts[c]['sourceIds']}
    for item in evidence:
        if not isinstance(item, dict) or item.get('sourceId') not in allowed_sources:
            raise ValueError('제공되지 않은 근거를 인용했어요.')
        source, quote = sources[item['sourceId']], _text(item.get('quote'))
        if not quote or len(quote) > 240 or _quote_key(quote) not in _quote_key(source['text']):
            raise ValueError('근거 인용이 제공된 내용과 일치하지 않아요.')
        pages = source.get('pages', [])
        enriched.append({'sourceId': item['sourceId'], 'quote': quote,
                         'page': pages[0] if pages else 0,
                         'sourceKind': source['sourceKind'],
                         'originalSourceIds': source.get('originalSourceIds', []),
                         'standardKnowledgeUsed': source.get('standardKnowledgeUsed') is True})
    result = copy.deepcopy(value)
    if kind != 'essay':
        result['keyPoints'] = []  # Unused display metadata must not discard a valid question.
    result.update(id=uuid.uuid4().hex, conceptIds=ids, concept=' · '.join(concepts[c]['title'] for c in ids), evidence=enriched)
    return result


def validate_questions(raw, assignment, concepts, sources, previous_stems, diagnostics=None):
    if not isinstance(raw, dict) or not isinstance(raw.get('questions'), list):
        raise ValueError('문제 생성 응답 형식이 올바르지 않아요.')
    # Objectives guide generation, never gate publication or trigger retries.
    targets = list(assignment.get('targets', []))
    used_targets = set()
    accepted, rejected = [], 0
    for item in raw['questions']:
        try:
            question = _question(item, assignment, concepts, sources)
            question['unitId'] = assignment['unitId']
            target = next((t for t in targets if t['id'] == question.get('targetId')), None)
            if target is None:
                target = next((t for t in targets if t['id'] not in used_targets
                               and t['type'] == question['type']), None)
            if target is not None:
                question.update(targetId=target['id'], targetGoal=copy.deepcopy(target['goal']))
                question['targetExecution'] = {'plannedGoal': copy.deepcopy(target['goal']),
                    'actualQuestion': question['stem'], 'comparisonStatus': 'not_semantically_evaluated'}
                used_targets.add(target['id'])
            accepted.append(question)
        except (ValueError, TypeError, KeyError) as error:
            from pdf_quiz_publish import preserve_question
            reason = str(error) if isinstance(error, ValueError) else '문항 필드 형식을 확인해 주세요.'
            question = preserve_question(item, assignment, concepts, sources, reason)
            question['unitId'] = assignment['unitId']
            accepted.append(question)
            if diagnostics is not None:
                diagnostics.append({'unitId': assignment['unitId'], 'reason': reason, 'action': 'shown_with_warning'})
    return accepted, rejected


def generate(folder, document, request, provider):
    from pdf_ai import AiResponseError, BudgetExceeded, run_usage
    folder = Path(folder)
    started, started_ms = time.monotonic(), int(time.time() * 1000)
    progress_lock = threading.Lock()
    progress_value = 0
    def progress(percent, message):
        nonlocal progress_value
        with progress_lock:
            percent = max(progress_value, min(99, int(percent)))
            if percent == progress_value:
                return
            progress_value = percent
            emit('quiz_stage', percent=percent, message=message)
    progress(2, '출제에 사용할 개념과 원문 근거를 준비하고 있어요.')
    config, outline, catalog, concepts, sources = context(document, request)
    # The planner receives bounded whole evidence passages; missing scope stays explicit.
    planner_prompt = (PROMPTS / 'planner.md').read_text(encoding='utf-8').strip()

    generation_prompt = '\n\n'.join((PROMPTS / name).read_text(encoding='utf-8').strip()
                                   for name in ('common.md', 'quality.md', THEMES[config['theme']]))

    question_format = _schema('questions')
    bound_limit = getattr(provider, 'input_bound_limit', 240000)
    signature = hashlib.sha256(json.dumps([VERSION, request['studyContent']['concepts'],
                             request.get('studyGroups', []), concepts, sources],
                             ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    run_id = uuid.uuid4().hex
    output = {'kind': 'quiz', 'documentId': document['documentId'], 'quizRunId': run_id,
              'operationId': provider.ledger.get('operationId', ''),
              'studySignature': signature,
              'sourceFingerprint': document.get('fingerprint', ''), 'promptVersion': VERSION,
              'startedAtMs': started_ms, 'quiz': config, 'requestedCount': config['totalCount'],
              'questions': [], 'candidateQuestions': [],
              'quality': {'status': 'disabled', 'reviewed': 0, 'accepted': 0, 'revised': 0, 'rejected': 0, 'calls': 0},
              'generationAudit': [], 'refillRounds': 0,
              'rawPlan': None, 'plan': None, 'errors': [],
              'unfilled': config['totalCount'], 'reason': ''}
    previous, messages = [], []
    quiz_root = folder / 'generated' / 'quiz-v2'
    latest = quiz_root / 'latest.json'
    destination = quiz_root / 'runs' / (run_id + '.json')
    retain_latest = False
    try:
        saved = json.loads(latest.read_text(encoding='utf-8'))
        if not isinstance(saved, dict):
            raise ValueError('invalid previous quiz')
        retain_latest = (saved.get('documentId') == document['documentId']
                         and saved.get('sourceFingerprint') in {document.get('fingerprint', ''),
                                                              *document.get('legacySourceFingerprints', [])}
                         and bool(_objects(saved.get('questions'))))
        if (saved.get('documentId') == document['documentId']
                and saved.get('sourceFingerprint') == document.get('fingerprint', '')
                and saved.get('studySignature') == signature):
            previous = [{'conceptIds': q['conceptIds'], 'focus': q['stem'][:160]}
                        for q in _objects(saved.get('questions'))
                        if isinstance(q.get('conceptIds'), list) and _text(q.get('stem'))][-30:]
    except (OSError, ValueError, TypeError, KeyError):
        pass  # A missing/damaged previous quiz never prevents a new explicit run.

    def save():
        with getattr(provider, '_lock', nullcontext()):
            usage = copy.deepcopy(run_usage(provider))
        output.update(elapsedSeconds=round(time.monotonic() - started, 3),
                      runUsage=usage, unfilled=max(0, config['totalCount'] - len(output['questions'])),
                      completedAtMs=int(time.time() * 1000), reason=' '.join(dict.fromkeys(messages)))
        output['processingComplete'] = output['unfilled'] == 0
        output['completionStatus'] = 'complete' if output['processingComplete'] else 'partial'
        output['resultPath'] = str(destination)
        write_json(destination, output)
        write_json(quiz_root / 'last-attempt.json', output)
        if output['questions'] or not retain_latest:
            write_json(latest, output)
        if output['questions']:
            # Publish only persisted, validated questions. Stable run/question IDs
            # let the UI keep answers while later batches continue generating.
            live = {key: copy.deepcopy(output[key]) for key in (
                'kind', 'documentId', 'quizRunId', 'startedAtMs', 'quiz',
                'requestedCount', 'questions', 'unfilled', 'elapsedSeconds',
                'runUsage', 'reason')}
            emit('quiz_stage', message=f"완성된 {len(output['questions'])}문제부터 풀 수 있어요.", workbook=live)

    def record_failure(error, stage, unit_id=''):
        # Provider errors are already sanitized. Local validation messages are
        # trusted only when raised here, never arbitrary transport/response text.
        trace = error.__traceback__
        while trace is not None and trace.tb_next is not None:
            trace = trace.tb_next
        local_validation = (isinstance(error, ValueError) and trace is not None
                            and Path(trace.tb_frame.f_code.co_filename).resolve() in {
                                Path(__file__).resolve(), Path(__file__).with_name('pdf_quiz_targets.py').resolve()})
        message = (str(error) if isinstance(error, AiResponseError) or local_validation else
                   '내부 처리 오류가 발생했어요. (' + type(error).__name__ + ')')
        detail = {'stage': stage, 'errorType': type(error).__name__, 'message': message}
        if unit_id:
            detail['unitId'] = unit_id
        output['errors'].append(detail)
        messages.append(({'planning': '출제 배분: ', 'quality': '문항 검증: '}.get(stage, '문제 생성: ')) + message)

    phase = 'planning'
    try:
        check_cancel(folder)
        progress(5, '전체 개념 목차로 출제 범위를 배분하고 있어요.')
        provider.context = {'kind': 'quiz_plan', 'reasoningEffort': QUIZ_PLAN_EFFORT}
        empty_payload = generation_payload(config, outline, {'allocations': [], 'unallocated': 0, 'reason': ''},
                                          {'unitId': '', 'conceptIds': [], 'counts': dict.fromkeys(TYPES, 0), 'focus': ''},
                                          concepts, sources, previous, run_id)
        budget = {'inputBoundBytes': bound_limit,
                  'fixedOverheadBytes': input_bound(empty_payload, generation_prompt, question_format),
                  'outputTokenLimit': MAX_OUTPUT_TOKENS,
                  'estimatedOutputTokensPerQuestion': OUTPUT_TOKENS_PER_QUESTION}
        profile_evidence = planning_evidence(concepts, sources)
        plan = provider.complete({'profilePolicy':policy(config['totalCount'],config['theme']), 'planningEvidence':profile_evidence, 'task': 'quiz_plan', 'request': config, 'outline': outline,
                                  'catalog': catalog, 'contextBudget': budget, 'previousTargets': previous},
                                 max_output=MAX_OUTPUT_TOKENS, system_prompt=planner_prompt,
                                 response_format=_schema('planner'),
                                 on_progress=lambda size: progress(10 + 14 * size / (size + max(800, config['totalCount'] * 180)),
                                     '출제 배분 응답을 받고 있어요.'))
        progress(25, '출제 배분을 확인하고 문항별 요청을 준비하고 있어요.')
        output['rawPlan'] = copy.deepcopy(plan)
        output['plan'] = apply_profile_plan(validate_plan(plan, catalog, config), profile_evidence, config, concepts)
        profile = output['plan']['profileAllocation']
        if profile['advancedShortfall']:
            messages.append(f"심화 목표 {profile['targetCounts']['advanced']}개 중 {profile['advancedShortfall']}개를 배정하지 못했어요. 실제 적합성은 미확인이에요.")
        adjustment = output['plan'].get('countAdjustment')
        if adjustment:
            output['planAdjustment'] = copy.deepcopy(adjustment)
            messages.append(f"배분 수량 {adjustment['allocatedBefore']}개를 요청 범위의 {adjustment['allocatedAfter']}개에 맞췄어요.")
        if output['plan']['unallocated']:
            messages.append(_text(output['plan']['reason']) or '일부 문항은 출제 대상을 배분하지 못했어요.')
        save()
        phase = 'questions'
        # Every worker receives the same prior-set snapshot. The complete plan
        # already carries the other targets; no worker depends on a peer reply.
        previous_snapshot = copy.deepcopy(previous)
        def payload_for(assignment):
            raw_payload = generation_payload(config, outline, output['plan'], assignment,
                                             concepts, sources, previous_snapshot, run_id)
            return wire_generation_payload(raw_payload)[0]
        assignments = []
        for assignment in batches(output['plan']):
            check_cancel(folder)
            try:
                assignments.extend(fitting_batches(assignment, payload_for, generation_prompt,
                                                   question_format, bound_limit))
            except ValueError:
                messages.append('일부 묶음은 모델의 입력 한도를 넘어 제외했어요. 개념 본문은 자르지 않았어요.')
        assignments = pack_generation_jobs(assignments, payload_for, generation_prompt, question_format, bound_limit)
        progress(30, '문항별 원문 근거 준비를 마쳤어요. 문제 생성을 시작해요.')
        stream_fractions = {}
        def question_progress(index, assignment, size):
            count = max(1, sum(assignment['counts'].values()))
            with progress_lock:
                stream_fractions[index] = max(stream_fractions.get(index, 0), .1 + .8 * size / (size + count * 1800))
                percent = 30 + 63 * sum(stream_fractions.values()) / max(1, len(assignments))
            progress(percent, '문제와 정답·해설을 생성하고 있어요. (예상 진행률)')
        output['executionAssignments'] = []
        output['maxParallelGenerations'] = MAX_PARALLEL_GENERATIONS
        accepted_by_index = {}
        displayed_option_ids = {}
        stop = threading.Event()
        stop_error = None
        completed_count = 0

        def mark_stop(error):
            nonlocal stop_error
            stop.set()
            if stop_error is not None:
                return
            stop_error = error
            if isinstance(error, InterruptedError):
                output['cancelled'] = True
                messages.append('문제 출제를 취소했어요. 완료된 문제와 사용량은 보관했어요.')
            else:
                output['budgetStopped'] = True
                output['creditStopped'] = bool(getattr(getattr(provider, 'billing', None), 'exhausted', False))
                messages.append(('크레딧이 부족해서 문제집 생성을 중단했어요.' if output['creditStopped']
                                 else '이번 출제의 사용 한도에 도달해 중단했어요.') + ' 완료된 문제는 보관했어요.')
            # In-flight network calls can outlive desktop cancellation grace.
            # Persist the stop and confirmed partials before waiting for them.
            save()

        def request_questions(index, assignment):
            if stop.is_set():
                raise CancelledError()
            check_cancel(folder)
            provider.context = {'kind': 'quiz_questions', 'quizUnitId': assignment['unitId'],
                                'quizAssignmentIndex': index,
                                'reasoningEffort': QUIZ_GENERATION_EFFORT}
            try:
                payload = payload_for(assignment)
                quotes = {(s['sourceId'], p['quoteId']): p['text'] for s in payload['sources']
                          for p in s.get('quotes', [])}
                raw = provider.complete(payload,
                    max_output=MAX_OUTPUT_TOKENS,
                    system_prompt=generation_prompt,
                    response_format=scoped_question_schema(question_format, assignment),
                    on_progress=lambda size: question_progress(index, assignment, size))
                raw = decode_keyed_questions(raw, assignment)
                original = copy.deepcopy(raw)
                projected = assemble_answers(render_calculations(resolve_generation_quotes(raw, quotes)))
                for q, source in zip(projected.get('questions', []), original.get('questions', [])):
                    if isinstance(q, dict): q['rawGenerationQuestion'] = source
                return projected
            except (BudgetExceeded, InterruptedError):
                stop.set()
                raise
            finally:
                provider.context = {}

        def merge_results():
            # Keep every structurally readable response, including identical stems.
            combined = [q for index in sorted(accepted_by_index) for q in accepted_by_index[index]]
            output['candidateQuestions'] = []
            output['questions'] = copy.deepcopy(interleave_questions(combined, config['allowedTypes']))
            shuffle_display_options(output['questions'], run_id)
            for item in output['questions']:
                if item['type'] != 'mcq':
                    continue
                # Later batches may be inserted earlier in plan order. Preserve
                # the choice order of questions already saved/shown for solving.
                choices = {option['id']: option for option in item['options']}
                order = displayed_option_ids.setdefault(item['id'], list(choices))
                item['options'] = [choices[oid] for oid in order]

        def run_assignments(assignments):
            nonlocal completed_count
            if not assignments:
                return
            offset = len(output['executionAssignments'])
            completed_before_round = completed_count
            with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_GENERATIONS, len(assignments)),
                                    thread_name_prefix='quiz-generation') as pool:
                active = {}
                next_index = 0
                last_progress = None
                while active or next_index < len(assignments):
                    if stop_error is None:
                        try:
                            check_cancel(folder)
                        except InterruptedError as error:
                            mark_stop(error)
                    while (not stop.is_set() and next_index < len(assignments)
                           and len(active) < MAX_PARALLEL_GENERATIONS):
                        assignment = assignments[next_index]
                        future = pool.submit(request_questions, offset + next_index, assignment)
                        active[future] = (offset + next_index, assignment)
                        output['executionAssignments'].append(assignment)
                        next_index += 1
                    if stop.is_set():
                        for future in active:
                            future.cancel()  # Cancel only work that has not started.
                    if not active:
                        break
                    running = sum(not future.done() for future in active)
                    progress_state = (completed_count, running, stop.is_set())
                    if progress_state != last_progress:
                        label = '완료된 응답 정리 중' if stop.is_set() else '문제 생성 중'
                        emit('quiz_stage', message=f'{label} · 완료 {completed_count-completed_before_round}/{len(assignments)}묶음 · 동시 {running}개')
                        last_progress = progress_state
                    done, _ = wait(active, timeout=.2, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in sorted(done, key=lambda f: active[f][0]):
                        index, assignment = active.pop(future)
                        try:
                            raw = future.result()
                            issues = []
                            accepted, rejected = validate_job(raw, assignment, concepts, sources, set(), issues)
                            accepted_by_index[index] = accepted
                            output['generationAudit'].append({'unitId': assignment['unitId'],
                                'round': output['refillRounds'], 'requested': sum(assignment['counts'].values()),
                                'returned': len(raw['questions']), 'accepted': len(accepted),
                                'reportedUnfilled': raw.get('unfilled'), 'issues': issues,
                                'reason': _text(raw.get('reason'))})
                            if issues:
                                messages.append('형식·출처 안내가 있는 문항도 모두 표시했어요.')
                            if len(raw['questions']) + (raw.get('unfilled') if type(raw.get('unfilled')) is int else 0) != sum(assignment['counts'].values()):
                                messages.append('응답 수량을 실제 유효한 문항 기준으로 정리했어요.')
                            if raw.get('unfilled'):
                                messages.append(_text(raw.get('reason')) or '근거가 충분하지 않은 문항은 생성하지 않았어요.')
                        except CancelledError:
                            pass
                        except (BudgetExceeded, InterruptedError) as error:
                            mark_stop(error)
                        except Exception as failure:
                            record_failure(failure, 'questions', assignment['unitId'])
                        completed_count += 1
                        with progress_lock:
                            stream_fractions[index] = 1
                            percent = 30 + 63 * sum(stream_fractions.values()) / max(1, len(assignments))
                        progress(percent, f"생성 응답을 정리하고 있어요. · {completed_count}/{len(assignments)}묶음")
                        merge_results()
                        save()
        run_assignments(assignments)
        if not stop.is_set() and len(output['questions']) < config['totalCount']:
            output['completionStopReason'] = '추가 호출 없이 생성된 문항을 모두 보관했어요. 요청 수보다 적을 수 있어요.'
            messages.append(output['completionStopReason'])
    except BudgetExceeded:
        output['budgetStopped'] = True
        output['creditStopped'] = bool(getattr(getattr(provider, 'billing', None), 'exhausted', False))
        messages.append(('크레딧이 부족해서 문제집 생성을 중단했어요.' if output['creditStopped']
                         else '이번 출제의 사용 한도에 도달해 중단했어요.') + ' 완료된 문제는 보관했어요.')
    except InterruptedError:
        output['cancelled'] = True
        messages.append('문제 출제를 취소했어요. 완료된 문제와 사용량은 보관했어요.')
    except Exception as failure:
        record_failure(failure, phase)
    finally:
        provider.context = {}
        progress(97, '완성된 문항과 풀이 정보를 저장하고 있어요.')
        save()
    return output
