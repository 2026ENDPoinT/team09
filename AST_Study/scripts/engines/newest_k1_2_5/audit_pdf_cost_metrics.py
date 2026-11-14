"""Offline usage/cap accounting for isolated Luna cost experiments.

No provider, credentials, network or mutable budget state is imported here.
The original ledgers remain the evidence; these are report-only calculations.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

LONG_CONTEXT_THRESHOLD = 272000
RESERVATION_MULTIPLIER = 1.25


def _money(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(name+' must be finite and nonnegative.')
    return value


def _tokens(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(name+' must be a nonnegative integer.')
    return value


def reserve_amount(reserved_usd):
    """Retain the experiment's 25% cache-write safety hold before sending."""
    return float(Decimal(str(_money(reserved_usd, 'reservedUsd')))*Decimal('1.25'))


def can_reserve(committed_usd, reserved_usd, execution_cap_usd=.98):
    """The caller must hold its cross-process lock across check and write."""
    committed = Decimal(str(_money(committed_usd, 'committedUsd')))
    reserve = Decimal(str(_money(reserved_usd, 'reservedUsd')))*Decimal('1.25')
    cap = Decimal(str(_money(execution_cap_usd, 'executionCapUsd')))
    return committed+reserve <= cap


def request_metrics(entry):
    """Known usage and a conservative cap amount for one persisted request.

    ``cache_write_tokens`` is the actual observed API key; similarly named
    cache_creation_tokens is not substituted. Input already includes cached
    input, so cached tokens must never be added to it again.
    """
    if not isinstance(entry, dict) or not isinstance(entry.get('requestId'), str):
        raise ValueError('A persisted requestId is required.')
    row = {'requestId': entry['requestId'], 'state': entry.get('state'),
        'requests': 0, 'notSentRequests': 0, 'settledRequests': 0,
        'unknownUsageRequests': 0, 'inputTokens': 0, 'cachedInputTokens': 0,
        'cacheWriteTokens': 0, 'outputTokens': 0, 'totalTokens': 0,
        'usageBasedUsd': 0., 'knownCacheWritePremiumUsd': 0.,
        'additionalCacheWritePremiumUsd': 0.,
        'unknownReservedUsd': 0., 'conservativeUnknownReservedUsd': 0.,
        'missingCacheWriteUpperBoundUsd': 0., 'committedUsd': 0.,
        'normalizedNoCacheUsd': 0., 'cacheWriteFieldPresent': None}
    if entry.get('state') == 'not_sent':
        row['notSentRequests'] = 1
        return row
    row['requests'] = 1
    if entry.get('state') != 'settled':
        reserve = _money(entry.get('reservedUsd'), 'reservedUsd')
        row.update(unknownUsageRequests=1, unknownReservedUsd=reserve,
            conservativeUnknownReservedUsd=reserve_amount(reserve),
            committedUsd=reserve_amount(reserve))
        return row
    usage = entry.get('usage')
    if (usage is None and entry.get('documentedFlexNoCharge') is True
            and entry.get('usageUnreported') is True and entry.get('estimatedUsd')==0
            and entry.get('requestedServiceTier')==entry.get('returnedServiceTier')=='flex'
            and entry.get('feeEvidence')=='native_resource_unavailable_flex_unavailable'):
        # Known-zero rejection without a usage receipt. Do not fabricate tokens.
        row.update(settledRequests=1,documentedNoCharge=True,usageUnreported=True)
        return row
    if not isinstance(usage, dict):
        raise ValueError('A settled request must retain its usage object.')
    details = usage.get('prompt_tokens_details', usage.get('input_tokens_details', {}))
    if not isinstance(details, dict):
        raise ValueError('Token details must be an object.')
    inputs = _tokens(usage.get('prompt_tokens', usage.get('input_tokens')), 'input tokens')
    outputs = _tokens(usage.get('completion_tokens', usage.get('output_tokens')), 'output tokens')
    cached = _tokens(details.get('cached_tokens', 0), 'cached tokens')
    writes = _tokens(details.get('cache_write_tokens', 0), 'cache write tokens')
    if cached > inputs or writes > inputs:
        raise ValueError('Cached/write tokens cannot exceed complete input tokens.')
    writes = min(writes, inputs-cached)
    amount = _money(entry.get('estimatedUsd'), 'estimatedUsd')
    # Follow the existing provider's long-context input multiplier. Conservatively
    # double the cache-write premium there rather than undercount the cap.
    tier_multiplier = 2 if entry.get('billedServiceTier') in ('fast', 'priority') else .5 if entry.get('billedServiceTier')=='flex' else 1
    multiplier = (2 if inputs > LONG_CONTEXT_THRESHOLD else 1) * tier_multiplier
    premium = writes*.025*multiplier/1_000_000
    included = entry.get('cacheWritePremiumUsd')
    if included is not None:
        included = _money(included, 'cacheWritePremiumUsd')
        if not math.isclose(included, premium, abs_tol=1e-10):
            raise ValueError('Included cache-write premium does not match saved usage.')
    additional_premium = premium if included is None else 0.
    present = 'cache_write_tokens' in details
    # Historical responses without the field do not establish a zero write fee.
    # Keep a worst-case uncached-input premium in the cap, separately from the
    # fee actually observable in usage. Current responses normally give 0.
    missing_bound = 0. if present else (inputs-cached)*.025*multiplier/1_000_000
    row.update(settledRequests=1, inputTokens=inputs, cachedInputTokens=cached,
        cacheWriteTokens=writes, outputTokens=outputs, totalTokens=inputs+outputs,
        usageBasedUsd=amount, knownCacheWritePremiumUsd=premium,
        additionalCacheWritePremiumUsd=additional_premium,
        missingCacheWriteUpperBoundUsd=missing_bound,
        committedUsd=amount+additional_premium+missing_bound,
        normalizedNoCacheUsd=(inputs*.10+outputs*.50)/1_000_000 * tier_multiplier,
        cacheWriteFieldPresent=present)
    return row


def _deduplicate(entries):
    selected = {};duplicates = 0
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('requestId'), str):
            raise ValueError('A persisted requestId is required.')
        key = entry['requestId']
        if key not in selected:
            selected[key] = entry
            continue
        duplicates += 1
        previous = selected[key]
        old_state, state = previous.get('state'), entry.get('state')
        if {old_state, state} == {'settled', 'not_sent'}:
            raise ValueError('Conflicting terminal states for one request.')
        if state == old_state == 'settled':
            if any(previous.get(k) != entry.get(k) for k in ('usage', 'estimatedUsd')):
                raise ValueError('Conflicting settled usage for one request.')
        elif state in ('settled', 'not_sent'):
            selected[key] = entry
        elif old_state not in ('settled', 'not_sent'):
            # Two unresolved snapshots must retain the larger safety hold.
            if _money(entry.get('reservedUsd'), 'reservedUsd') > _money(previous.get('reservedUsd'), 'reservedUsd'):
                selected[key] = entry
    return list(selected.values()), duplicates


def usage_metrics(entries):
    """Deduplicate requests and return exact accounting totals without mutation."""
    selected, duplicates = _deduplicate(entries)
    rows = [request_metrics(entry) for entry in selected]
    names = ('requests', 'notSentRequests', 'settledRequests', 'unknownUsageRequests',
        'inputTokens', 'cachedInputTokens', 'cacheWriteTokens', 'outputTokens',
        'totalTokens', 'usageBasedUsd', 'knownCacheWritePremiumUsd', 'additionalCacheWritePremiumUsd',
        'unknownReservedUsd', 'conservativeUnknownReservedUsd',
        'missingCacheWriteUpperBoundUsd', 'committedUsd', 'normalizedNoCacheUsd')
    totals = {name: math.fsum(row[name] for row in rows) for name in names}
    for name in names[:9]:
        totals[name] = int(totals[name])
    totals.update(duplicateSnapshotsIgnored=duplicates,
        missingCacheWriteFieldRequests=sum(row['cacheWriteFieldPresent'] is False for row in rows),
        requestMetrics=rows)
    return totals


def ledger_metrics(root):
    """Read only isolated run ledgers, excluding backups and historical studies."""
    root = Path(root)
    paths = sorted(root.glob('runs/*/usage/*.json'))
    entries = [];evidence = []
    for path in paths:
        raw = path.read_bytes();ledger = json.loads(raw)
        if ledger.get('model') != 'gpt-6-luna':
            raise ValueError('This price/cap audit supports gpt-6-luna only.')
        requests = ledger.get('requests')
        if not isinstance(requests, list):
            raise ValueError('A ledger must contain its requests array.')
        entries.extend(requests)
        evidence.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
            'model': ledger['model'], 'requests': len(requests)})
    value = usage_metrics(entries)
    value.update(ledgerEvidence=evidence, ledgerFiles=len(paths), additionalApiRequests=0)
    return value
