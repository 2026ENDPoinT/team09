"""Lossless publication fallback, not a quality judge or repair/model call."""
import copy
import json
import uuid
from pdf_quiz_study_contract import preserve_metadata


def preserve_question(raw, assignment, concepts, sources, reason):
    from pdf_quiz import _text, _quote_key, TYPES
    item = raw if isinstance(raw, dict) else {}
    prior_warnings = item.get('warnings', [])
    warnings = [reason] + [w for w in prior_warnings if isinstance(w, str)] if isinstance(prior_warnings, list) else [reason]
    text = lambda key: _text(item.get(key))
    stem = text('stem') or ('원본 응답: ' + json.dumps(raw, ensure_ascii=False))
    answer = text('answer') or '생성 응답에 답안이 없어요.'
    explanation = text('explanation') or '생성 응답에 해설이 없어요.'
    kind = item.get('type')
    opts = item.get('options')
    options = []
    if isinstance(opts, list):
        options = [copy.deepcopy(o) for o in opts if isinstance(o, dict)]
    malformed_choices = 'distractors' in item
    if malformed_choices:
        # A malformed wire response still owns its original answer and choices.
        # Keep every supplied choice visible; never invent missing alternatives.
        options = [{'id': '모범답안', 'text': answer}]
        raw_choices = item['distractors']
        if isinstance(raw_choices, list):
            options += [{'id': str(i + 1), 'text': _text(o.get('text')) or json.dumps(o, ensure_ascii=False)}
                        if isinstance(o, dict) else {'id': str(i + 1), 'text': json.dumps(o, ensure_ascii=False)}
                        for i, o in enumerate(raw_choices)]
        elif raw_choices is not None:
            options.append({'id': '원본 선택지', 'text': json.dumps(raw_choices, ensure_ascii=False)})
    usable_mcq = (len(options) == 4 and {o.get('id') for o in options if isinstance(o.get('id'), str)} == set('ABCD')
                  and answer in set('ABCD') and all(_text(o.get('text')) for o in options))
    if malformed_choices or kind not in TYPES or kind == 'mcq' and not usable_mcq or kind == 'ox' and answer not in ('O', 'X'):
        # Preserve malformed choices visibly; never invent a fourth choice/answer.
        choices = '\n'.join(f"{o.get('id', i+1)}. {o.get('text', '')}" for i, o in enumerate(options))
        if choices:
            stem += '\n\n생성된 선택지:\n' + choices
        warnings.append('형식을 완성하지 못해 원문과 답안을 비교하는 방식으로 표시해요.')
        kind = 'essay'
    if kind != 'mcq':
        options = []
    else:
        for o in options:
            o['explanation'] = _text(o.get('explanation')) or '선지 해설이 제공되지 않았어요.'
    ids = [c for c in item.get('conceptIds', []) if isinstance(c, str) and c in concepts] if isinstance(item.get('conceptIds'), list) else []
    evidence = []
    for e in item.get('evidence', []) if isinstance(item.get('evidence'), list) else []:
        if not isinstance(e, dict) or not isinstance(e.get('sourceId'), str):
            continue
        source = sources.get(e['sourceId']); quote = _text(e.get('quote'))
        allowed = source and any(e['sourceId'] in concepts[c]['sourceIds'] for c in assignment['conceptIds'])
        if not allowed or not quote or _quote_key(quote) not in _quote_key(source['text']):
            continue  # Keep invalid claims in rawQuestion, never fabricate a PDF link.
        pages = source.get('pages', [])
        evidence.append({'sourceId': e['sourceId'], 'quote': quote, 'page': pages[0] if pages else 0,
                         'sourceKind': source['sourceKind'], 'originalSourceIds': source.get('originalSourceIds', []),
                         'standardKnowledgeUsed': source.get('standardKnowledgeUsed') is True})
    if not evidence:
        warnings.append('출처 연결을 확인하지 못했어요. 원본 PDF와 비교해 주세요.')
    points = [p for p in item.get('keyPoints', []) if isinstance(p, str) and p.strip()] if isinstance(item.get('keyPoints'), list) else []
    published = {'id': uuid.uuid4().hex, 'unitId': assignment['unitId'], 'type': kind, 'conceptIds': ids,
            'concept': ' · '.join(concepts[c]['title'] for c in ids), 'stem': stem, 'options': options,
            'answer': answer, 'explanation': explanation, 'keyPoints': points if kind == 'essay' else [],
            'evidence': evidence, 'warnings': list(dict.fromkeys(warnings)), 'rawQuestion': copy.deepcopy(raw)}
    if text('targetId'):
        published['targetId'] = text('targetId')
    return preserve_metadata(item, published)
