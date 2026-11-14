"""Append locally lost interpretation boundaries from exact existing paid work.

No source claim is generated here. The same canonical response is validated with
the previous filler rule and the current rule. Only a reversible difference made
of newly retained boundary sentences may be appended to matching saved prose.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import OrderedDict
from pathlib import Path
import re
import threading

from pdf_new_concept_ver99_checks import interpretation_boundary, prepare_learner_segment
from pdf_saved_tables import (IDENTITY, _signature as _prose_signature, _stamp,
                              _layout, _read, _verified_patches, _finish as _table_view)
from pdf_study_cache_reuse import block_key
from synesis_paths import io_path

VERSION = 'saved-interpretation-boundaries-v1'
MEMO_LIMIT = 16
_MEMO = OrderedDict()
_LOCK = threading.RLock()


def _signature(value):
    prose = _prose_signature(value)
    if prose is None:
        return None
    try:
        return prose, [s.get('body') for s in value.get('sections', [])]
    except (AttributeError, TypeError):
        return None


def _append(value, patch):
    section = value['sections'][patch['section']]
    part = section['parts'][patch['part']]
    card = value['concepts'][patch['group']]['entries'][patch['entry']]
    old = part['body']
    suffix = '\n\n' + '\n\n'.join(patch['sentences'])
    part['body'] += suffix
    card['explanation'] += suffix
    section['body'] = section['body'].replace(old, part['body'], 1)


def _finish(result, patches):
    value = copy.deepcopy(result) if patches else dict(result)
    for patch in patches:
        _append(value, patch)
    value['savedBoundaryVersion'] = VERSION
    if patches:
        value['savedBoundaryRestoration'] = {'additionalApiRequests': 0,
            'items': [{'title': p['title'], 'sentences': p['sentences'],
                       'sourceIds': p['sourceIds']} for p in patches]}
    return value


def _legacy_field(text, raw_concept, field):
    """Reverse only exact retained source segments, including their spacing."""
    if 'segments' in raw_concept:
        pieces = [(s.get('text'), s.get('blockIds')) for s in raw_concept['segments']
                  if isinstance(s, dict) and s.get('kind') == field]
    else:
        pieces = [(raw_concept.get(field), raw_concept.get('blockIds'))]
    previous, sentences, sources = text, [], set()
    for piece, refs in pieces:
        if not isinstance(piece, str):
            continue
        current, current_removed = prepare_learner_segment(piece)
        legacy, legacy_removed = prepare_learner_segment(piece, preserve_boundaries=False)
        if current == legacy or not current or current not in previous:
            continue
        additions = [s for s in legacy_removed if s not in current_removed]
        if (previous.count(current) != 1 or not additions
                or any(not interpretation_boundary(s) for s in additions)
                or not isinstance(refs, list) or not refs or not all(isinstance(s, str) for s in refs)):
            return None
        if legacy:
            previous = previous.replace(current, legacy, 1)
        elif previous == current:
            previous = ''
        elif previous.startswith(current+'\n\n'):
            previous = previous[len(current)+2:]
        elif previous.endswith('\n\n'+current):
            previous = previous[:-len(current)-2]
        elif '\n\n'+current+'\n\n' in previous:
            previous = previous.replace('\n\n'+current+'\n\n', '\n\n', 1)
        else:
            return None
        sentences.extend(s for s in additions if s not in sentences)
        sources.update(refs)
    return previous, sentences, sources


def _roundtrip_pairs(old, new, raw):
    """Every changed learner field must revert exactly under the old rule."""
    try:
        old_parts, new_parts = old['summary']['parts'], new['summary']['parts']
        old_cards, new_cards = old['concepts'], new['concepts']
        if not len(old_parts) == len(new_parts) == len(old_cards) == len(new_cards):
            return []
        pairs = []
        for before, after, old_card, new_card in zip(old_parts, new_parts, old_cards, new_cards):
            if (any(before.get(k) != after.get(k) for k in set(before) | set(after)
                    if k not in ('body', 'easyExplanation'))
                    or any(old_card.get(k) != new_card.get(k) for k in set(old_card) | set(new_card)
                           if k not in ('definition', 'explanation', 'easyExplanation'))):
                return []
            source_concepts = [c for c in raw.get('concepts', []) if isinstance(c, dict)
                               and c.get('title') == new_card.get('name')]
            if len(source_concepts) != 1:
                return []
            sentences, sources = [], set()
            previous = {}
            for field in ('definition', 'explanation', 'easyExplanation'):
                text = new_card.get(field)
                if not isinstance(text, str) or not isinstance(old_card.get(field), str):
                    return []
                reversed_field = _legacy_field(text, source_concepts[0], field)
                if reversed_field is None:
                    return []
                previous[field], removed, refs = reversed_field
                if previous[field] != old_card[field]:
                    return []
                sentences.extend(s for s in removed if s not in sentences)
                sources.update(refs)
            body = '\n\n'.join(previous[k] for k in ('definition', 'explanation') if previous[k].strip())
            if body != before['body'] or previous['easyExplanation'] != before.get('easyExplanation', ''):
                return []
            if sentences:
                if not sources.issubset({e.get('sourceId') for e in before.get('evidence', [])}):
                    return []
                pairs.append((before, old_card, sentences, sorted(sources)))
        return pairs
    except (KeyError, TypeError, AttributeError):
        return []


def _patches_for(value, pairs):
    patches = []
    for old_part, old_card, sentences, sources in pairs:
        parts = [(si, pi, p) for si, s in enumerate(value.get('sections', []))
                 for pi, p in enumerate(s.get('parts', []))
                 if all(p.get(k) == old_part.get(k) for k in ('title', 'body', 'easyExplanation', 'evidence'))]
        cards = [(gi, ei, c) for gi, g in enumerate(value.get('concepts', []))
                 for ei, c in enumerate(g.get('entries', []))
                 if all(c.get(k) == old_card.get(k) for k in
                        ('name', 'definition', 'explanation', 'easyExplanation', 'evidence'))]
        if len(parts) != 1 or len(cards) != 1:
            continue
        si, pi, part = parts[0]
        gi, ei, card = cards[0]
        body = value['sections'][si].get('body')
        if not isinstance(body, str) or not part.get('body') or body.count(part['body']) != 1:
            continue
        existing = '\n'.join(str(part.get(k, '')) for k in ('body', 'easyExplanation'))
        existing += '\n' + '\n'.join(str(card.get(k, '')) for k in ('definition', 'explanation', 'easyExplanation'))
        additions = [s for s in sentences if s not in existing]
        if not additions:
            continue
        patch = {'section': si, 'part': pi, 'group': gi, 'entry': ei,
                 'sentences': additions, 'title': part['title'],
                 'sourceIds': sources}
        _append(value, patch)
        patches.append(patch)
    return patches


def restore_saved_boundaries(folder, document, result, validator, table_renderer=None):
    """Return an additive presentation repair, with no cache writes or API calls."""
    if not isinstance(result, dict) or result.get('savedBoundaryVersion') == VERSION:
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
           hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).digest())
    layout = _layout(root)
    with _LOCK:
        memo = _MEMO.get(key)
        if memo and memo['layout'] == layout and all(_stamp(p) == stamp for p, stamp in memo['watched'].items()):
            _MEMO.move_to_end(key)
            return _finish(result, memo['patches'])
    watched, patches = {}, []
    roots = sorted(root.glob('*/result.json'),
                   key=lambda p: (_stamp(p) or (0, 0, 0, 0, 0))[3], reverse=True)
    for path in roots:
        saved = _read(path, watched)
        if (not isinstance(saved, dict) or any(saved.get(k) != result.get(k) for k in IDENTITY)
                or _signature(saved) is None):
            continue
        if _signature(saved) != signature:
            # Tables may already have been restored earlier in display_saved.
            # Reconstruct that exact source-proven view, never strip markdown.
            if table_renderer is None:
                continue
            table_patches = _verified_patches(path, saved, table_renderer, watched)
            if _signature(_table_view(saved, table_patches)) != signature:
                continue
        manifest = _read(path.parent/'manifest.json', watched)
        blocks = _read(path.parent/'blocks.json', watched)
        if not isinstance(manifest, dict) or not isinstance(blocks, list):
            continue
        allowed = {b['id']: b for b in blocks if isinstance(b, dict) and isinstance(b.get('id'), str)}
        value = copy.deepcopy(result)
        for job in manifest.get('jobs', []):
            if not isinstance(job, dict) or not re.fullmatch(r'[A-Za-z0-9_-]+', str(job.get('id', ''))):
                continue
            targets = job.get('blocks')
            if not isinstance(targets, list) or not targets:
                continue
            try:
                if any(b['id'] not in allowed or block_key(b) != block_key(allowed[b['id']]) for b in targets):
                    continue
                raw = _read(path.parent/f'response-{job["id"]}.json', watched)
                if not isinstance(raw, dict):
                    continue
                old = validator(raw, job, document, preserve_boundaries=False)
                new = validator(raw, job, document)
                patches.extend(_patches_for(value, _roundtrip_pairs(old, new, raw)))
            except (KeyError, ValueError, TypeError, IndexError):
                continue
        # Only one exact historical result may supply these appends.
        if patches:
            break
    with _LOCK:
        _MEMO[key] = {'layout': layout, 'watched': watched, 'patches': patches}
        _MEMO.move_to_end(key)
        while len(_MEMO) > MEMO_LIMIT:
            _MEMO.popitem(last=False)
    return _finish(result, patches)
