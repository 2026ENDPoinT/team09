"""Reuse local source extraction without trusting semantic-plan annotations.

This cache contains the extractor's original output, not ``blocks.json``: the
latter can acquire planRole and other AI-plan fields later in the pipeline.
Every caller receives a separate decoded copy. No request or token is added.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
from pathlib import Path
import tempfile
import threading
import time

VERSION = 'source-layout-cache-k122-bundles-v2'
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _source_hash(source):
    value = hashlib.sha256()
    with source.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(part)
    return value.hexdigest()


def _implementation(extractor):
    """Invalidate conservatively even if an extractor edit omitted VERSION."""
    try:
        path = inspect.getsourcefile(extractor)
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None
    except (OSError, TypeError):
        return None


def _identity(folder, document, targets, layout_version, extractor):
    # nativeText is used by fragment_page's unsupported-frame fallback. Other
    # mutable page-analysis/generation fields do not affect local extraction.
    pages = [{'number': document['pages'][n - 1]['number'],
              'nativeText': document['pages'][n - 1].get('nativeText', '')}
             for n in targets]
    if (any(type(n) is not int or n < 1 or n > len(document['pages']) for n in targets)
            or len(set(targets)) != len(targets)
            or any(item['number'] != n for n, item in zip(targets, pages))):
        raise ValueError('Invalid local-layout page selection')
    return {'version': VERSION, 'layoutVersion': layout_version,
            'extractorImplementation': _implementation(extractor),
            'documentId': document['documentId'],
            'sourceFingerprint': document['fingerprint'],
            'sourceSha256': _source_hash(folder / 'source.pdf'),
            'targets': list(targets), 'sourcePages': pages}


def _valid_blocks(blocks, targets):
    if not isinstance(blocks, list):
        return False
    ids = set()
    for block in blocks:
        if (not isinstance(block, dict) or not isinstance(block.get('id'), str)
                or not block['id'] or block['id'] in ids
                or type(block.get('page')) is not int or block['page'] not in targets
                or not isinstance(block.get('text'), str)
                or not isinstance(block.get('kind'), str)
                or type(block.get('hasVisual')) is not bool):
            return False
        box = block.get('bbox')
        if (not isinstance(box, list) or len(box) != 4
                or any(type(n) not in (int, float) or not math.isfinite(n) for n in box)
                or not 0 <= box[0] < box[2] <= 1
                or not 0 <= box[1] < box[3] <= 1):
            return False
        ids.add(block['id'])
    # The real extractor retains an entire-page block even for a blank page.
    return {block['page'] for block in blocks} == set(targets)


def _valid_audit(audit, blocks, targets, layout_version):
    if not isinstance(audit, dict) or audit.get('version') != layout_version:
        return False
    pages = audit.get('pages')
    if (not isinstance(pages, list) or not all(isinstance(p, dict) for p in pages)
            or [p.get('page') for p in pages] != targets):
        return False
    fragments = []
    for page in pages:
        if not isinstance(page.get('fragments'), list):
            return False
        fragments.extend(page['fragments'])
    return fragments == blocks


def extract_layout(folder, document, targets, cache=None, extractor=None, *,
                   layout_version=None, diagnostics=None):
    """Return fresh-equivalent blocks, reusing only an exact immutable source.

    ``cache`` keeps the existing extractor audit destination. The authoritative
    unannotated cache is shared across study/planning cache roots underneath this
    document folder. Set ``diagnostics`` to a dict to receive hit/reason/timing.
    Corrupt, incomplete, changed-source and unavailable caches are ordinary
    misses; the original extractor remains the fallback.
    """
    from pdf_pipeline import check_cancel, read_json_cache, write_json
    if extractor is None or layout_version is None:
        from pdf_new_concept_v02_regions import extract, VERSION as current_version
        extractor = extractor or extract
        layout_version = current_version if layout_version is None else layout_version
    folder, targets = Path(folder), list(targets)
    started = time.monotonic()
    status = {'hit': False, 'reason': 'miss', 'version': VERSION}

    def finish(blocks):
        status['seconds'] = round(time.monotonic() - started, 6)
        if diagnostics is not None:
            diagnostics.update(status)
        return copy.deepcopy(blocks)

    check_cancel(folder)
    try:
        identity = _identity(folder, document, targets, layout_version, extractor)
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        status['reason'] = 'source_identity_unavailable'
        return finish(extractor(folder, document, targets, cache))
    key = _digest(identity)
    path = folder / 'generated' / 'local-layout-cache' / (key + '.json')
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(str(path.resolve()), threading.Lock())
    with lock:
        check_cancel(folder)
        saved = read_json_cache(path)
        if saved is not None:
            try:
                good = (saved.get('identity') == identity
                        and saved.get('complete') is True
                        and _valid_blocks(saved.get('blocks'), targets)
                        and _valid_audit(saved.get('audit'), saved['blocks'], targets, layout_version)
                        and saved.get('payloadSha256') == _digest([saved['blocks'], saved['audit']]))
            except (ValueError, TypeError, KeyError):
                good = False
            if good:
                if cache is not None:
                    try:
                        write_json(Path(cache) / 'local-layout.json', saved['audit'])
                    except OSError:
                        status['auditRestoreUnavailable'] = True
                status.update(hit=True, reason='exact_source_hit')
                return finish(saved['blocks'])
            status['reason'] = 'invalid_cache'

        # Capture the independent audit before callers can mutate plan fields.
        # A temporary destination also allows reading_plan(cache=None) to seed
        # the same local cache used by grouping and generation.
        with tempfile.TemporaryDirectory(prefix='synesis-layout-') as temporary:
            audit_root = Path(cache) if cache is not None else Path(temporary)
            blocks = extractor(folder, document, targets, audit_root)
            audit = read_json_cache(audit_root / 'local-layout.json')
        check_cancel(folder)
        if not _valid_blocks(blocks, targets) or not _valid_audit(audit, blocks, targets, layout_version):
            status['reason'] = 'extractor_audit_unavailable'
            return finish(blocks)
        try:
            if _identity(folder, document, targets, layout_version, extractor) != identity:
                status['reason'] = 'source_changed_during_extraction'
                return finish(blocks)
            write_json(path, {'identity': identity, 'complete': True,
                             'blocks': blocks, 'audit': audit,
                             'payloadSha256': _digest([blocks, audit])})
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            # Failure to save derived local data must not discard valid work.
            status['reason'] = 'cache_write_unavailable'
        return finish(blocks)
