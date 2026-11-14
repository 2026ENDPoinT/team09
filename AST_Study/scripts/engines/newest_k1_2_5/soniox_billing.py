"""Recording-only Soniox usage-log settlement. Never uploads audio or estimates final charges.

The shared wallet helpers are reused unchanged; only voice operations are written.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from synesis_paths import resolve_path
from pathlib import Path
import threading
import time
import uuid

from asr_compare import api_key
from pdf_credit_billing import Billing, wallet_lock, save, decimal, RATE

_LOCK = threading.RLock()
URL = 'https://api.soniox.com/v1/usage-logs'


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


@contextmanager
def ledger_lock(path):
    path = resolve_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.with_suffix('.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.lockf(lock.fileno(), fcntl.LOCK_EX, 1)
        try:
            yield json.loads(path.read_text(encoding='utf-8'), parse_float=Decimal)
        finally:
            if os.name == 'nt':
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.lockf(lock.fileno(), fcntl.LOCK_UN, 1)


def request_started(path, reference, model):
    if not path:
        return
    with ledger_lock(path) as ledger:
        if ledger.get('sealed'):
            raise RuntimeError('billing_ledger_sealed')
        ledger.setdefault('requests', {})[reference] = {
            'reference': reference, 'model': model, 'startedAt': now_iso(), 'state': 'planned'}
        save(path, ledger)


def request_state(path, reference, state):
    if not path:
        return
    with ledger_lock(path) as ledger:
        ledger['requests'][reference]['state'] = state
        save(path, ledger)


def seal(path, duration_ms, abandoned=False):
    with ledger_lock(path) as ledger:
        ledger['durationMs'] = max(0, duration_ms)
        ledger['sealed'] = True
        ledger.setdefault('sealedAt', now_iso())
        ledger['abandoned'] = bool(abandoned)
        # A crash before submission cannot have incurred a provider charge.
        for request in ledger.get('requests', {}).values():
            if request['state'] == 'planned':
                request['state'] = 'no_charge'
        ledger['state'] = 'pending'
        ledger['nextAttemptMs'] = 0
        save(path, ledger)


def get_logs(session, key, start, end):
    """All pages in all <=31-day windows; no heuristic matching by account balance/time/cost."""
    logs = {}
    while start < end:
        stop = min(start + timedelta(days=30), end)
        params = {'start_time': start.isoformat().replace('+00:00', 'Z'),
                  'end_time': stop.isoformat().replace('+00:00', 'Z'), 'limit': 1000, 'sort': 'end_time_asc'}
        cursors = set()
        while True:
            response = session.get(URL, headers={'Authorization': 'Bearer ' + key}, params=params, timeout=(10, 20))
            if response.status_code != 200:
                raise RuntimeError('usage_http_' + str(response.status_code))
            data = response.json()
            if not isinstance(data.get('usage_logs'), list):
                raise RuntimeError('usage_invalid_schema')
            for entry in data['usage_logs']:
                identifier = entry.get('uuid')
                if not isinstance(identifier, str) or not identifier:
                    raise RuntimeError('usage_missing_uuid')
                if identifier in logs and logs[identifier] != entry:
                    raise RuntimeError('usage_conflicting_uuid')
                logs[identifier] = entry
            cursor = data.get('next_page_cursor')
            if not cursor:
                break
            if cursor in cursors:
                raise RuntimeError('usage_repeated_cursor')
            cursors.add(cursor); params['cursor'] = cursor
        start = stop
    return list(logs.values())


def reconcile(path, session=None, key=None, now=None):
    """Each Soniox UUID is charged once; missing logs remain pending, even after network failures."""
    import requests
    with ledger_lock(path) as ledger:
        if not ledger.get('sealed'):
            return summary(ledger)
        if ledger.get('state') == 'settled':
            return summary(ledger)
        now = now or datetime.now(timezone.utc)
        expected = {r: q for r, q in ledger.get('requests', {}).items() if q['state'] != 'no_charge'}
        error = None
        try:
            observed = ledger.setdefault('observed', {})
            if expected:
                key = key or api_key('SONIOX_API_KEY')
                if not key:
                    raise RuntimeError('usage_missing_key')
                start = instant(ledger['createdAt']) - timedelta(minutes=1)
                if now - start >= timedelta(days=91):
                    raise RuntimeError('usage_log_retention_expired')
                for log in get_logs(session or requests.Session(), key, start, now + timedelta(seconds=1)):
                    reference = log.get('client_reference_id')
                    if reference not in expected:
                        continue
                    if log.get('request_scope') != 'api' or log.get('model') != expected[reference]['model']:
                        raise RuntimeError('usage_reference_mismatch')
                    try:
                        usd = Decimal(str(log['cost_usd']))
                    except (KeyError, InvalidOperation, ValueError):
                        raise RuntimeError('usage_invalid_cost') from None
                    if not usd.is_finite() or usd < 0:
                        raise RuntimeError('usage_invalid_cost')
                    prior = observed.get(log['uuid'])
                    charge = {'reference': reference, 'usd': str(usd), 'model': log['model']}
                    if prior and prior != charge:
                        raise RuntimeError('usage_changed_cost')
                    observed[log['uuid']] = charge
            # Persist provider evidence BEFORE touching the wallet. A crash can safely replay it.
            save(path, ledger)
            if not expected and not observed and not resolve_path(ledger['walletPath'], path).exists():
                ledger.update(state='settled', settledUsd='0', settledCredits='0', pendingRequests=0)
                save(path, ledger)
                return summary(ledger)
            ledger['walletPath'] = str(resolve_path(ledger['walletPath'], path))
            billing = Billing(ledger['walletPath'], ledger['operationId'], 'voice', ledger['createdAtMs'])
            billing.record()
            # Reuse the existing cross-process wallet lock, preserving all PDF operations/holds/charges.
            with wallet_lock(ledger['walletPath']) as wallet:
                op = wallet['creditOperations'][ledger['operationId']]
                op['durationMs'] = ledger['durationMs']; op['estimated'] = False
                op['provider'] = 'soniox'; op['billingSource'] = 'soniox_usage_logs'
                save(ledger['walletPath'], wallet)
            with wallet_lock(ledger['walletPath']) as wallet:
                charges = wallet.get('creditCharges', {})
                for identifier, evidence in observed.items():
                    prior = charges.get('soniox-' + identifier)
                    if prior and (prior.get('operationId') != ledger['operationId'] or decimal(prior.get('usd')) != decimal(evidence['usd'])):
                        raise RuntimeError('usage_wallet_charge_conflict')
            for identifier, evidence in observed.items():
                billing.settle('soniox-' + identifier, Decimal(evidence['usd']))
            # Read authoritative debits after replay, rather than just trusting cached observations.
            with wallet_lock(ledger['walletPath']) as wallet:
                charges = wallet.get('creditCharges', {})
                ledger['settledUsd'] = str(sum((decimal(charges['soniox-' + i]['usd']) for i in observed if 'soniox-' + i in charges), Decimal(0)))
                ledger['settledCredits'] = str(sum((decimal(charges['soniox-' + i]['credits']) for i in observed if 'soniox-' + i in charges), Decimal(0)))
            found = {v['reference'] for v in observed.values()}
            ledger['pendingRequests'] = len(set(expected) - found)
            ledger['state'] = 'settled' if not ledger['pendingRequests'] else 'pending'
        except Exception as failure:
            # Never echo HTTP body/headers, tokens, full exception messages, or provider payloads.
            safe = str(failure)
            error = safe if safe.startswith(('usage_', 'billing_')) else type(failure).__name__
            ledger['state'] = 'pending'; ledger['lastError'] = error
        if error is None:
            ledger.pop('lastError', None)
        ledger['attempts'] = int(ledger.get('attempts', 0)) + 1
        delay = min(300, 15 * 2 ** min(ledger['attempts'] - 1, 5))
        if now - instant(ledger['createdAt']) > timedelta(days=1):
            delay = 3600
        ledger['nextAttemptMs'] = int(now.timestamp() * 1000) + delay * 1000
        save(path, ledger)
        return summary(ledger)


def summary(ledger):
    return {'lectureId': ledger['lectureId'], 'state': ledger.get('state', 'capturing'),
            'settledUsd': ledger.get('settledUsd', '0'), 'settledCredits': ledger.get('settledCredits', '0'),
            'pendingRequests': ledger.get('pendingRequests', 0), 'lastError': ledger.get('lastError')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--seal-ms', type=int)
    parser.add_argument('--abandoned', action='store_true')
    parser.add_argument('--seal-only', action='store_true')
    args = parser.parse_args()
    if args.seal_ms is not None:
        seal(args.ledger, args.seal_ms, args.abandoned)
    if not args.seal_only:
        print(json.dumps(reconcile(args.ledger), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
