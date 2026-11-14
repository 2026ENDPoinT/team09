"""Restore checked tables hidden by an old display limit, without new API calls.

Only replies belonging to the exact saved learner output may supply a table.
Existing prose, source files, response caches and healthy tables stay untouched.
The caller supplies the ordinary table renderer so restoration uses the same
rectangularity, source binding, cell safety and duplicate checks as new output.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path

from pdf_new_concept_ver99_checks import prepare_response
from pdf_study_cache_reuse import block_key, repair_source_ids
from synesis_paths import io_path

VERSION = 'saved-source-tables-v4-cells'
PREVIOUS_VERSIONS = {'saved-source-tables-v1', 'saved-source-tables-v2',
                     'saved-source-tables-v3-multiple'}
IDENTITY = ('documentId', 'sourceFingerprint', 'strategy', 'model', 'scope', 'page')
MEMO_LIMIT = 16
_MEMO = OrderedDict()
_MEMO_LOCK = threading.RLock()


def _stamp(path):
    try:
        value = io_path(path).stat()
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    except OSError:
        return None


def _read(path, watched):
    watched[str(path)] = _stamp(path)
    try:
        return json.loads(io_path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _layout(root):
    # Directory metadata catches newly appearing cache/result/response files;
    # existing file stamps below also catch in-place edits, without rereading JSON.
    try:
        directories = sorted(p for p in root.iterdir() if p.is_dir())
        return (_stamp(root), tuple((str(p), _stamp(p), _stamp(p/'result.json')) for p in directories))
    except OSError:
        return None


def _apply_patch(value, patch):
    section = value['sections'][patch['section']]
    part = section['parts'][patch['part']]
    card = value['concepts'][patch['group']]['entries'][patch['entry']]
    old_body = part.get('body', '')
    part['body'] = old_body + '\n\n' + patch['markdown']
    card['explanation'] = card.get('explanation', '') + '\n\n' + patch['markdown']
    body = section.get('body', '')
    if old_body and body.count(old_body) == 1:
        section['body'] = body.replace(old_body, part['body'], 1)


def _finish(result, patches):
    # Memoize only small patches, never another copy of all paid learner prose.
    value = copy.deepcopy(result) if patches else dict(result)
    for patch in patches:
        _apply_patch(value, patch)
    value['savedTableVersion'] = VERSION
    if patches:
        value['savedTableRestoration'] = {'tables': [p['diagnostic'] for p in patches],
                                          'additionalApiRequests': 0}
    return value


def _key(value):
    return re.sub(r'\s+', '', str(value)).casefold()


def _refs(entry):
    return {e.get('sourceId') for e in entry.get('evidence', [])
            if isinstance(e, dict) and isinstance(e.get('sourceId'), str)}


def _signature(result):
    # Hierarchy/node IDs may change in a presentation upgrade. Teaching, its
    # placement and source bindings must be identical to the saved cache.
    def refs(entry):
        return sorted(json.dumps(e, sort_keys=True, ensure_ascii=False)
                      for e in entry.get('evidence', []) if isinstance(e, dict))
    try:
        return ([[(p.get('title'), p.get('body'), refs(p))
                  for p in s.get('parts', [])] for s in result.get('sections', [])],
                [[(e.get('name'), e.get('definition'), e.get('explanation'), refs(e))
                  for e in group.get('entries', [])] for group in result.get('concepts', [])])
    except (AttributeError, TypeError):
        return None


def _verified_patches(path, saved, table_renderer, watched):
    """Reconstruct possible appends against an exact historical learner result."""
    manifest = _read(path.parent/'manifest.json', watched)
    blocks = _read(path.parent/'blocks.json', watched)
    if not isinstance(manifest, dict) or not isinstance(blocks, list):
        return []
    value = copy.deepcopy(saved)
    patches = []
    allowed = {b['id']: b for b in blocks if isinstance(b, dict) and isinstance(b.get('id'), str)}
    for job in manifest.get('jobs', []):
        if not isinstance(job, dict) or not re.fullmatch(r'[A-Za-z0-9_-]+', str(job.get('id', ''))):
            continue
        targets = job.get('blocks')
        if not isinstance(targets, list) or not targets:
            continue
        try:
            if any(b['id'] not in allowed or block_key(b) != block_key(allowed[b['id']]) for b in targets):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        raw = _read(path.parent/f'response-{job["id"]}.json', watched)
        if not isinstance(raw, dict) or not raw.get('tables'):
            continue
        try:
            prepared = prepare_response(repair_source_ids(raw, [b['id'] for b in targets]))
            concepts = prepared.get('concepts', [])
            if not isinstance(concepts, list) or not all(isinstance(c, dict) for c in concepts):
                continue
            parts = [{'body': ''} for _ in concepts]
            cards = [{'explanation': ''} for _ in concepts]
            table_renderer(prepared.get('tables'), concepts, parts, cards,
                           {b['id']: b for b in targets})
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        for concept, rendered in zip(concepts, parts):
            rendered_tables = [p.strip() for p in rendered['body'].split('\n\n') if p.strip()]
            if not rendered_tables:
                continue
            ids = set(concept.get('blockIds', []))
            title = _key(concept.get('title', ''))
            if not ids or not ids.issubset(allowed):
                continue
            matches = [(si, pi, p) for si, s in enumerate(value.get('sections', []))
                       for pi, p in enumerate(s.get('parts', []))
                       if _key(p.get('title')) == title and ids.issubset(_refs(p))]
            entries = [(gi, ei, e) for gi, g in enumerate(value.get('concepts', []))
                       for ei, e in enumerate(g.get('entries', []))
                       if _key(e.get('name')) == title and ids.issubset(_refs(e))]
            if len(matches) != 1 or len(entries) != 1:
                continue
            si, pi, part = matches[0]
            gi, ei, card = entries[0]
            for markdown in rendered_tables:
                if any(markdown in {p.strip() for p in text.split('\n\n')}
                       for text in (part.get('body', ''), card.get('explanation', ''))):
                    continue
                patch = {'section': si, 'part': pi, 'group': gi, 'entry': ei, 'markdown': markdown,
                         'diagnostic': {'title': part.get('title'), 'rows': markdown.count('\n')-1,
                                        'sourceIds': sorted(ids)}}
                _apply_patch(value, patch)
                patches.append(patch)
    return patches


def _remaining_verified_patches(saved, current, patches):
    """Accept only exact source-verified table appends, never arbitrary edits."""
    expected = copy.deepcopy(saved)
    remaining = []
    try:
        for patch in patches:
            old_part = expected['sections'][patch['section']]['parts'][patch['part']]
            old_card = expected['concepts'][patch['group']]['entries'][patch['entry']]
            part = current['sections'][patch['section']]['parts'][patch['part']]
            card = current['concepts'][patch['group']]['entries'][patch['entry']]
            suffix = '\n\n' + patch['markdown']
            if (part.get('body', '').startswith(old_part.get('body', '') + suffix)
                    and card.get('explanation', '').startswith(old_card.get('explanation', '') + suffix)):
                _apply_patch(expected, patch)
            else:
                remaining.append(patch)
        if (_signature(expected) != _signature(current)
                or [s.get('body') for s in expected.get('sections', [])]
                != [s.get('body') for s in current.get('sections', [])]):
            return None
    except (KeyError, IndexError, TypeError):
        return None
    return remaining


def restore_saved_tables(folder, document, result, table_renderer):
    """Return a copy with provably source-matched missing tables, with no writes.

    Old complete results are valuable paid work; rebuilding or regenerating all
    their prose is unnecessary for a display-only repair. A missing/ambiguous
    provenance chain simply leaves that result as it was.
    """
    if not isinstance(result, dict) or result.get('savedTableVersion') == VERSION:
        return result
    if (result.get('documentId') != document.get('documentId')
            or result.get('sourceFingerprint') != document.get('fingerprint')):
        return result
    strategy = result.get('strategy')
    if not isinstance(strategy, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', strategy):
        return result
    signature = _signature(result)
    if signature is None:
        return result
    root = io_path(Path(folder)/'generated'/strategy)
    key = (str(root), VERSION, tuple(result.get(k) for k in IDENTITY),
           hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode('utf-8')).digest())
    if result.get('savedTableVersion') in PREVIOUS_VERSIONS:
        # This upgrade path also proves the derived section prose. Its memo
        # must not transfer to an edited section or another display marker.
        section_bodies = [s.get('body') for s in result.get('sections', [])]
        key += ('partial-source-tables', result.get('savedTableVersion'), hashlib.sha256(json.dumps(section_bodies,
            ensure_ascii=False).encode('utf-8')).digest())
    layout = _layout(root)
    with _MEMO_LOCK:
        memo = _MEMO.get(key)
        if memo and memo['layout'] == layout and all(_stamp(p) == stamp for p, stamp in memo['watched'].items()):
            _MEMO.move_to_end(key)
            return _finish(result, memo['patches'])
    watched = {}
    patches = []
    roots = sorted(root.glob('*/result.json'),
                   key=lambda p: (_stamp(p) or (0, 0, 0, 0, 0))[3], reverse=True)
    for path in roots:
        saved = _read(path, watched)
        if (not isinstance(saved, dict)
                or any(saved.get(k) != result.get(k) for k in IDENTITY)):
            continue
        saved_signature = _signature(saved)
        if saved_signature is None:
            continue
        same = saved_signature == signature
        if not same and result.get('savedTableVersion') not in PREVIOUS_VERSIONS:
            continue
        candidate = _verified_patches(path, saved, table_renderer, watched)
        if not same:
            candidate = _remaining_verified_patches(saved, result, candidate)
        if candidate is None:
            continue
        patches = candidate
        # A result can be copied to a newer cache without its old responses.
        # Continue to an exact historical copy if no usable table was found.
        if patches:
            break
    with _MEMO_LOCK:
        _MEMO[key] = {'layout': layout, 'watched': watched, 'patches': patches}
        _MEMO.move_to_end(key)
        while len(_MEMO) > MEMO_LIMIT:
            _MEMO.popitem(last=False)
    return _finish(result, patches)
