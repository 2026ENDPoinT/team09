"""Reconnect visual concept references to already persisted page transcriptions.

No OCR/model call and no rewriting of the user's saved concepts. Only complete,
located elements from the current document's ready page analysis are eligible.
Geometry is a provenance link, not a semantic correctness score.
"""
from __future__ import annotations

import math


def _box(value):
    if (not isinstance(value, list) or len(value) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        return None
    x0, y0, x1, y1 = value
    return value if 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1 else None


def _overlaps(left, right):
    a, b = _box(left), _box(right)
    if a is None or b is None:
        return False
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    aa, ba = (a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1])
    # A small reference must not pull in an unrelated whole-page transcription.
    return intersection / (aa + ba - intersection) >= .25


def transcription_index(document):
    eligible = {}
    for page in document.get('pages', []):
        analysis = page.get('pageAnalysis') or {}
        if (analysis.get('status') != 'ready'
                or analysis.get('documentId') != document.get('documentId')
                or analysis.get('page') != page.get('number')):
            continue
        for element in analysis.get('elements', []):
            if (element.get('status') == 'complete' and not element.get('uncertainDetails')
                    and element.get('kind') != 'decoration' and _box(element.get('bbox'))):
                eligible[page['number'], element.get('elementId')] = element
    by_page = {}
    for chunk in document.get('chunks', []):
        element = eligible.get((chunk.get('page'), chunk.get('elementId')))
        if (element is None or chunk.get('source') != 'ai_transcription'
                or chunk.get('documentId') != document.get('documentId')
                or not isinstance(chunk.get('text'), str) or not chunk['text'].strip()
                or not isinstance(chunk.get('id'), str) or not chunk['id'].strip()
                or chunk.get('bbox') != element.get('bbox')):
            continue
        by_page.setdefault(chunk['page'], []).append(chunk)
    return by_page


def recover_transcriptions(evidence, index, first, last, document_id):
    """Return matched chunks and whether *every* reference is safely covered.

    Partial coverage keeps the saved explanation as fallback; never use just a
    page number to import all its topics. A range crossing cannot establish full
    coverage of an explanation spanning out-of-range pages.
    """
    recovered, complete = {}, bool(evidence)
    for ref in evidence:
        page = ref.get('page')
        if (type(page) is not int or not first <= page <= last
                or ref.get('documentId', document_id) != document_id):
            complete = False
            continue
        matches = [chunk for chunk in index.get(page, [])
                   if ref.get('sourceId') in (chunk['id'], chunk.get('elementId'))
                   or (ref.get('source') == 'region_image'
                       and _overlaps(ref.get('bbox'), chunk['bbox']))]
        if not matches:
            complete = False
        for chunk in matches:
            recovered[chunk['id']] = chunk
    return list(recovered.values()), complete
