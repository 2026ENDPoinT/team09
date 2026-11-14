"""Resume one exact lost planner request after a fresh receipt lookup and an approved retry.

Never treats a 404 as free usage, changes source/cache identities, or authorizes
teaching regeneration. The alternate is linked durably to its original request.
"""
import json
import math
import re


def local_planner_originals(provider, identities, max_output):
    """Identify only exact, fully uploaded Responses planners with a lost ID.

    This grants no resend or cost settlement. The caller may preserve the
    source partition locally instead of repeating this semantic planning call.
    Other missing/settled/recoverable originals keep their existing guard.
    """
    context = provider.context
    if (context.get('kind') != 'region_plan'
            or context.get('strategy') not in ('new-concept-v99','newest-k1','newest-k1-1','newest-k1-11','newest-k1-1-1','newest-k1-1-2','newest-k1-1-3','newest-k1-2-5')
            or context.get('studyConnectionRepairAllowed') is not True):
        return []
    from pdf_study_receipts import proven_unsent
    from pdf_auth_rejection import is_authentication_rejection
    ledgers = [(provider.ledger_path, provider.ledger)]
    for path in (provider.folder / 'usage').glob('*.json'):
        if path == provider.ledger_path:
            continue
        try:
            ledgers.append((path, json.loads(path.read_text(encoding='utf-8'))))
        except (OSError, ValueError, TypeError):
            continue
    originals = []
    for _, ledger in ledgers:
        if (not isinstance(ledger, dict) or ledger.get('model') != provider.model
                or not isinstance(ledger.get('requests'), list)):
            continue
        for entry in ledger.get('requests', []):
            if (not isinstance(entry, dict) or entry.get('payloadHash') not in identities
                    or proven_unsent(entry) or is_authentication_rejection(entry)):
                continue
            if entry.get('state') not in ('reserved', 'settled', 'usage_unknown', 'failed_or_uncertain'):
                continue
            key = entry.get('responseCacheKey')
            sent = entry.get('requestBodyBytesSent')
            if (entry.get('kind') != 'region_plan' or entry.get('inputApi') != 'responses'
                    or entry.get('state') == 'settled' or entry.get('responseId')
                    or entry.get('maxOutputTokens') != max_output
                    or not entry.get('sentAtMs') or entry.get('requestUploadComplete') is not True
                    or type(sent) is not int or sent <= 0
                    or sent != entry.get('requestBodyBytesExpected') or sent != entry.get('requestBodyBytes')
                    or not isinstance(entry.get('requestId'), str) or not entry['requestId']
                    or not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key)
                    or entry.get('pages') != context.get('pages')):
                return []
            cache = provider.folder / 'generated' / 'paid-responses' / (key + '.json')
            if any(cache.with_suffix(suffix).exists() for suffix in
                   ('.json', '.raw.json', '.responses.raw.json', '.incomplete.json',
                    '.partial.json', '.stream.partial.json')):
                return []
            originals.append({k: entry[k] for k in
                ('requestId', 'responseCacheKey', 'reservedUsd', 'state', 'pages') if k in entry})
    return originals


def planner_restart(provider, identities, max_output, request_id=None):
    context = provider.context
    if (getattr(provider, 'retry_missing_responses', False) is not True
            or context.get('kind') != 'region_plan'
            or (context.get('studyConnectionRepairAllowed') is not True
                and not (request_id is not None and context.get('studyDurable') is True))):
        return None
    ledgers = []
    for path in sorted((provider.folder / 'usage').glob('*.json')):
        if path == provider.ledger_path:
            continue
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if value.get('model') == provider.model and isinstance(value.get('requests'), list):
                ledgers.append((path, value))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    entries = [entry for _, ledger in ledgers for entry in ledger['requests'] if isinstance(entry, dict)]
    entries.extend(provider.ledger['requests'])
    linked = {entry.get('durableRecoveryOf') for entry in entries if entry.get('durableRecoveryOf')}
    candidates = []
    for path, ledger in ledgers:
        for entry in ledger['requests']:
            if not isinstance(entry, dict):
                continue
            ident = entry.get('requestId')
            if (not isinstance(ident, str) or not ident or ident in linked
                    or request_id is not None and ident != request_id
                    or entry.get('kind') != 'region_plan' or entry.get('inputApi') != 'chat'
                    or entry.get('payloadHash') not in identities or entry.get('maxOutputTokens') != max_output
                    or entry.get('state') not in ('reserved', 'failed_or_uncertain', 'usage_unknown')
                    or not entry.get('sentAtMs') or entry.get('durableRecoveryConsumed')
                    or entry.get('durableRecoveryOf') or entry.get('foregroundRecoveryOf')
                    or entry.get('receiptLookupHttpStatus') != 404
                    or entry.get('receiptLookupAtMs', 0) < provider.ledger.get('createdAtMs', float('inf'))):
                continue
            reserved = entry.get('reservedUsd')
            if not isinstance(reserved, (int, float)) or not math.isfinite(reserved) or reserved < 0:
                continue
            candidates.append({'path': path, 'ledger': ledger, 'entry': entry})
    # Ambiguous histories must not authorize another request.
    return candidates[0] if len(candidates) == 1 else None
