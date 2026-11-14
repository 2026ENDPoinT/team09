"""Persist desktop cancellation separately from billing and retire stopped attempts.

No generation POST, no deletion of paid evidence, and no engine-specific policy.
Only a later invocation can replace an explicitly cancelled attempt.
"""
import json
import re
import time
import urllib.request
from pathlib import Path

from pdf_pipeline import read_json_cache, write_json


def retryable(entry):
    return entry.get('cancellationDisposition') in (
        'server_stopped', 'connection_closed_unconfirmed')


def enable(provider):
    from pdf_worker_control import register_intent
    def persist():
        with provider._lock:
            provider.ledger['desktopCancelledAtMs'] = int(time.time() * 1000)
            write_json(provider.ledger_path, provider.ledger)
    register_intent(provider.ledger['operationId'], persist)


def _retire_cache(folder, entry):
    key = entry.get('responseCacheKey')
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
        return
    cache = Path(folder) / 'generated/paid-responses' / (key + '.json')
    # A completed value always wins, including a locally completed JSON frame.
    if cache.is_file():
        return
    archive = cache.parent / 'cancelled' / entry['requestId']
    for path in cache.parent.glob(key + '.*.json'):
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / path.name
        # A crash between archive and ledger publication is safely repeatable.
        if target.exists() and target.read_bytes() != path.read_bytes():
            raise ValueError('취소된 응답 보관 기록이 일치하지 않아요.')
        path.replace(target)


def prepare(provider, *, open_url=None):
    """Called under the provider/document lock before cache and batch guards."""
    if getattr(provider, '_cancel_history_prepared', False):
        return
    provider._cancel_history_prepared = True
    if open_url is None:
        transport = getattr(provider, 'study_http_transport', None)
        open_url = (lambda req, timeout: transport.open(req, timeout)) if transport else urllib.request.urlopen
    for path in sorted((Path(provider.folder) / 'usage').glob('*.json')):
        if path == provider.ledger_path:
            continue
        ledger = read_json_cache(path)
        if not isinstance(ledger, dict) or ledger.get('model') != provider.model:
            continue
        for entry in ledger.get('requests', []):
            if not isinstance(entry, dict) or entry.get('state') == 'not_sent':
                continue
            if retryable(entry):
                continue
            if not (ledger.get('desktopCancelledAtMs') or entry.get('clientStopReason') == 'user_cancelled'):
                continue
            if not re.fullmatch(r'[a-f0-9]{32}', str(entry.get('requestId', ''))):
                continue
            key = entry.get('responseCacheKey', '')
            cache = Path(provider.folder) / 'generated/paid-responses' / (key + '.json')
            if not re.fullmatch(r'[a-f0-9]{64}', key):
                cache = None
            if cache is not None and cache.is_file():
                continue
            if cache is not None:
                raw = read_json_cache(cache.with_suffix('.raw.json'))
                choices = raw.get('choices', []) if isinstance(raw, dict) else []
                if choices and choices[0].get('finish_reason') == 'stop':
                    continue  # Preserve a completed answer saved just before the close.
            ident = entry.get('responseId')
            native = None
            if ident:
                from pdf_study_connection import RESPONSE_ID
                if not isinstance(ident, str) or not RESPONSE_ID.fullmatch(ident):
                    continue
                if cache is not None:
                    for suffix in ('.cancel.receipt.json', '.responses.raw.json'):
                        candidate = read_json_cache(cache.with_suffix(suffix))
                        if isinstance(candidate, dict) and candidate.get('id') == ident and candidate.get('status') in ('completed', 'cancelled', 'failed', 'incomplete'):
                            native = candidate
                            break
                if native is None:
                    if provider.transport is not None:
                        continue  # Unit-test/custom transports never reach the network.
                    request = urllib.request.Request('https://api.openai.com/v1/responses/' + ident + '/cancel',
                        data=b'{}', method='POST', headers={'Authorization': 'Bearer ' + provider.key, 'Content-Type': 'application/json'})
                    try:
                        with open_url(request, timeout=6) as stream:
                            native = json.load(stream)
                    except (OSError, ValueError):
                        continue  # Never grant a replacement while cancellation is unconfirmed.
                    if not isinstance(native, dict) or native.get('id') != ident:
                        continue
                    if cache is not None:
                        write_json(cache.with_suffix('.cancel.receipt.json'), native)
                if native.get('status') == 'completed':
                    # Let the existing paid-response adapter recover and settle it.
                    if cache is not None:
                        write_json(cache.with_suffix('.responses.raw.json'), native)
                    continue
                if native.get('status') not in ('cancelled', 'failed', 'incomplete'):
                    continue
                entry['serverTerminalStatus'] = native['status']
                disposition = 'server_stopped'
            else:
                # Closing a foreground connection is its cancellation mechanism.
                # Missing IDs cannot be cancelled remotely; retain the unknown hold.
                disposition = 'connection_closed_unconfirmed'
            _retire_cache(provider.folder, entry)
            entry.update(cancellationDisposition=disposition, cancellationResolvedAtMs=int(time.time() * 1000))
            if native is not None:
                from pdf_responses_transport import _usage
                from pdf_study_receipts import receipt_cost
                usage = _usage(native.get('usage'), [])
                if isinstance(usage, dict) and all(type(usage.get(k)) is int for k in ('prompt_tokens', 'completion_tokens')):
                    actual, premium = receipt_cost(provider.model, usage, entry)
                    entry.update(state='settled', usage=usage, estimatedUsd=actual, cacheWritePremiumUsd=premium,
                                 recoveryBillingPending=True)
            write_json(path, ledger)
