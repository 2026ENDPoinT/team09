"""Select exact source passages by ID instead of asking models to retype them.

The transport representation is lossless for source text. Restored quotations
still pass the existing per-unit source and exact-quote checks before a question
can become a candidate; passage IDs never grant a wider assessment scope.
"""
from __future__ import annotations

import copy

MAX_QUOTE_CHARS = 240
_WIRE_METADATA = ('sourceId', 'sourceKind', 'pages', 'standardKnowledgeUsed')


def wire_generation_payload(payload):
    """Return a copied payload and a ``(sourceId, quoteId) -> text`` index.

    Every code point of a source appears in exactly one consecutive passage. No
    whitespace, LaTeX escape, Unicode sequence or source body is normalized.
    Duplicate IDs are allowed only for identical complete source records.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get('sources'), list):
        raise ValueError('출제 근거 목록의 형식이 올바르지 않아요.')
    wire = copy.deepcopy(payload)
    wire['sources'] = []
    quotes, seen = {}, {}
    for source in payload['sources']:
        if (not isinstance(source, dict) or not isinstance(source.get('sourceId'), str)
                or not source['sourceId'].strip() or not isinstance(source.get('text'), str)):
            raise ValueError('출제 근거의 ID 또는 본문이 올바르지 않아요.')
        sid, text = source['sourceId'], source['text']
        if sid in seen:
            if source != seen[sid]:
                raise ValueError('같은 출처 ID의 본문 또는 메타데이터가 서로 달라요.')
            continue
        seen[sid] = source
        passages = []
        for index, start in enumerate(range(0, len(text), MAX_QUOTE_CHARS), 1):
            qid, passage = f'q{index}', text[start:start + MAX_QUOTE_CHARS]
            passages.append({'quoteId': qid, 'text': passage})
            quotes[sid, qid] = passage
        wire['sources'].append({**{key: copy.deepcopy(source[key]) for key in _WIRE_METADATA if key in source},
                                'quotes': passages})
    return wire, quotes


def resolve_generation_quotes(raw, quotes):
    """Restore selected passages while preserving valid legacy exact quotes.

    An unresolved ID leaves that entire question unconverted so the ordinary
    question validator rejects it without discarding its valid peers. If an
    unknown ID is mixed with a legacy quote, remove that fallback quote to avoid
    treating the unrecognized selection as an implicit legacy approval.
    """
    resolved = copy.deepcopy(raw)
    if not isinstance(resolved, dict) or not isinstance(resolved.get('questions'), list):
        return resolved
    for question in resolved['questions']:
        if not isinstance(question, dict) or not isinstance(question.get('evidence'), list):
            continue
        evidence = question['evidence']
        invalid = []
        for item in evidence:
            if not isinstance(item, dict) or 'quoteId' not in item:
                continue
            sid, qid = item.get('sourceId'), item['quoteId']
            if not isinstance(sid, str) or not isinstance(qid, str) or (sid, qid) not in quotes:
                invalid.append(item)
        if invalid:
            for item in invalid:
                item.pop('quote', None)
            continue
        for item in evidence:
            if isinstance(item, dict) and 'quoteId' in item:
                item['quote'] = quotes[item['sourceId'], item.pop('quoteId')]
    return resolved
