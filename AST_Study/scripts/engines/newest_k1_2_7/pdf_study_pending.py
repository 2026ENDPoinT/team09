"""Read-only accounting for unfinished original teaching requests in this scope."""
import math
from pathlib import Path

from pdf_auth_rejection import is_authentication_rejection
from pdf_study_receipts import strict_object


def pending_originals(folder, model, unit_ids):
    units = set(unit_ids)
    count = 0
    reserved = 0.0
    unreadable = 0
    for path in sorted((Path(folder) / 'usage').glob('*.json')):
        try:
            ledger = strict_object(path.read_text(encoding='utf-8'))
            if ledger.get('model') != model:
                continue
            entries = ledger['requests']
            if not isinstance(entries, list):
                raise ValueError('Invalid request ledger')
        except (OSError, ValueError, KeyError, TypeError):
            unreadable += 1
            continue
        for entry in entries:
            if (not isinstance(entry, dict) or entry.get('kind') != 'region_study'
                    or entry.get('state') not in ('reserved', 'usage_unknown', 'failed_or_uncertain')
                    or not entry.get('sentAtMs') or is_authentication_rejection(entry)
                    or not isinstance(entry.get('unitIds'), list)
                    or not units.intersection(x for x in entry['unitIds'] if isinstance(x, str))):
                continue
            count += 1
            amount = entry.get('reservedUsd')
            if type(amount) in (int, float) and math.isfinite(amount) and amount >= 0:
                reserved += amount
    return {'requests': count, 'reservedUsd': reserved, 'unreadableLedgers': unreadable}


def retry_original_ids(provider, identities):
    """Link only this replacement's source units, never every missing document request."""
    units = set(provider.context.get('unitIds', []))
    result = set()
    for path in (provider.folder / 'usage').glob('*.json'):
        try:
            ledger = strict_object(path.read_text(encoding='utf-8'))
            if ledger.get('model') != provider.model:
                continue
            for entry in ledger.get('requests', []):
                if (entry.get('requestId') in provider.unavailable_study_request_ids
                        and not entry.get('unresolvedRetryApproved')
                        and (entry.get('payloadHash') in identities
                             or units.intersection(entry.get('unitIds', [])))):
                    result.add(entry['requestId'])
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return sorted(result)
