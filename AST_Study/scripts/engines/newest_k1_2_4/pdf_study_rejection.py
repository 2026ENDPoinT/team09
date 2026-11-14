"""Persist one rejected attempt without rejecting its logical request or siblings.

Native receipts and usage remain valid billing evidence. Only their reuse as
learner answers is prohibited. The marker always belongs to the actual private
response cache key, never to a logical key copied from the ledger.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

VERSION='study-delivery-rejection-v2'
REASON='repeated_short_field'
REASONS=frozenset((REASON,'repeated_blank_lines'))


def rejected_entry(entry):
    return (isinstance(entry,dict) and
        any(entry.get(field) in REASONS for field in ('deliveryViolation','streamOutputAnomaly')))


def _marker_path(response_cache):
    cache=Path(response_cache)
    if cache.suffix!='.json' or re.fullmatch(r'[a-f0-9]{64}',cache.stem) is None:
        raise ValueError('Delivery rejection requires an exact response cache key.')
    return cache.with_suffix('.delivery-rejected.json')


def mark_rejected(response_cache,entry,reason=None):
    """Record rejection before a delayed receipt can recreate a parsed cache."""
    path=_marker_path(response_cache)
    key=Path(response_cache).stem
    if reason is None and isinstance(entry,dict):
        reason=next((entry.get(f) for f in ('deliveryViolation','streamOutputAnomaly')
                     if entry.get(f) in REASONS),REASON)
    if reason not in REASONS or not isinstance(entry,dict) or entry.get('responseCacheKey')!=key:
        raise ValueError('Delivery rejection cannot be rebound to another attempt.')
    request_id=entry.get('requestId')
    response_id=entry.get('responseId')
    if not isinstance(request_id,str) or not request_id:
        raise ValueError('Delivery rejection requires its original request ID.')
    if response_id is not None and (not isinstance(response_id,str) or not response_id):
        raise ValueError('Delivery rejection response ID is invalid.')
    marker={'version':VERSION,'cacheKey':key,'requestId':request_id,
            'responseId':response_id,'reason':reason}
    from pdf_pipeline import write_json
    write_json(path,marker)
    return marker


def is_rejected(response_cache,entry=None):
    """Read only this cache's rejection; never follow logicalResponseCacheKey."""
    try:path=_marker_path(response_cache)
    except ValueError:return False  # Non-response paths have no delivery marker.
    key=Path(response_cache).stem
    if rejected_entry(entry) and entry.get('responseCacheKey')==key:return True
    if not path.exists():return False
    try:marker=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return True  # A damaged marker cannot release its cache.
    if not isinstance(marker,dict):return True
    # Explicitly unrelated markers cannot quarantine a normal sibling.
    if marker.get('cacheKey') not in (None,key):return False
    if marker.get('reason') is not None and marker.get('reason') not in REASONS:return False
    return True
