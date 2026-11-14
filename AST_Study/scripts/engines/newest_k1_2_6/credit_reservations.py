"""Offline reservation recovery. Unconfirmed usage is recorded, never held indefinitely."""
import atexit
import errno
import json
import os
import re
import threading
import uuid
from decimal import Decimal
from pathlib import Path

from synesis_paths import resolve_path

_OWNERS = {}
_OWNER_LOCK = threading.RLock()


@atexit.register
def _close_owners():
    for (pid, _), (_, stream) in list(_OWNERS.items()):
        try:
            stream.close()
            if pid == os.getpid():
                Path(stream.name).unlink(missing_ok=True)
        except OSError:
            pass
    _OWNERS.clear()


def _lock(stream, blocking):
    stream.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.lockf(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB), 1)


def _unlock(stream):
    stream.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.lockf(stream.fileno(), fcntl.LOCK_UN, 1)


def owner(wallet_path):
    """The OS releases this lease even after a crash, kill or power loss; no timeout guess."""
    key = (os.getpid(), str(Path(wallet_path).resolve()))
    with _OWNER_LOCK:
        if key not in _OWNERS:
            identifier = uuid.uuid4().hex
            folder = Path(wallet_path).parent / 'credit-owners'
            folder.mkdir(parents=True, exist_ok=True)
            stream = (folder / (identifier + '.lock')).open('w+b')
            stream.write(b'0'); stream.flush()
            _lock(stream, True)
            _OWNERS[key] = (identifier, stream)
        return {'ownerId': _OWNERS[key][0], 'ownerPid': os.getpid(), 'reservationVersion': 2}


def owner_alive(wallet_path, hold):
    identifier = hold.get('ownerId', '')
    if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
        return False
    local = _OWNERS.get((os.getpid(), str(Path(wallet_path).resolve())))
    if local and local[0] == identifier:
        return True
    path = Path(wallet_path).parent / 'credit-owners' / (identifier + '.lock')
    try:
        with path.open('r+b') as stream:
            try:
                _lock(stream, False)
            except OSError as failure:
                if failure.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    return True
                raise
            _unlock(stream)
        return False
    except FileNotFoundError:
        return False
    except OSError:
        return True  # An unreadable lease is not proof that its owner has stopped.


def _amount(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError('Invalid settled usage')
    return amount


def _operation(wallet, record):
    return wallet.setdefault('creditOperations', {}).setdefault(record['operationId'], {
        'category': record.get('category', 'analysis'),
        'createdAtMs': record.get('operationCreatedAtMs', record.get('createdAtMs', 0)),
        'credits': '0', 'unknownRequests': 0})


def pending(wallet, request_id, record, now, reason):
    """Release user funds permanently; retain uncertain provider cost for SYNESIS."""
    records = wallet.setdefault('creditPendingRequests', {})
    if request_id not in records:
        record = dict(record)
        if not record.get('unknown'):
            operation = _operation(wallet, record)
            operation['unknownRequests'] = int(operation.get('unknownRequests', 0)) + 1
        record.update(unknown=True, payer='synesis', customerChargeUsd='0',
                      reservationReleasedAtMs=now, reservationReleaseReason=reason)
        records[request_id] = record
    wallet.setdefault('creditHolds', {}).pop(request_id, None)


def settle(wallet, request_id, record, usd, rate):
    usd = _amount(usd)
    holds = wallet.setdefault('creditHolds', {})
    records = wallet.setdefault('creditPendingRequests', {})
    previous = records.pop(request_id, None) or holds.get(request_id)
    holds.pop(request_id, None)
    operation = _operation(wallet, record)
    if previous and previous.get('unknown'):
        operation['unknownRequests'] = max(0, int(operation.get('unknownRequests', 0)) - 1)
    charges = wallet.setdefault('creditCharges', {})
    if request_id in charges:
        return
    sponsored = bool((previous and previous.get('unknown')) or record.get('unknown')
                     or record.get('payer') == 'synesis')
    customer_usd = Decimal(0) if sponsored else usd
    from pdf_k120_reservation import metadata
    policy=metadata(previous or record)
    spendable=None
    if policy and not sponsored:
        from pdf_credit_billing import available
        # The current hold is already released. Everything still held belongs
        # to other requests and cannot be consumed by this over-estimate miss.
        spendable=max(Decimal(0),available(wallet))
    credits = customer_usd * rate
    if spendable is not None and credits>spendable:
        credits=spendable
        customer_usd=credits/rate
    wallet['highWaterCredits'] = str(Decimal(str(wallet['highWaterCredits'])) + credits)
    operation['credits'] = str(Decimal(str(operation.get('credits', 0))) + credits)
    charges[request_id] = {'usd': str(customer_usd), 'credits': str(credits),
                           'providerUsd': str(usd), 'payer': 'synesis' if sponsored else 'customer',
                           'operationId': record['operationId']}
    if policy:
        covered=max(Decimal(0),usd-customer_usd)
        charges[request_id].update(policy,customerChargeUsd=str(customer_usd),
            synesisCoveredUsd=str(covered),payer='synesis' if customer_usd==0 and usd>0 else
                'shared' if covered>0 else 'customer')


def reconcile(wallet_path, wallet, rate, now):
    """Replay confirmed ledger amounts and release dead/finished owners; never perform network I/O."""
    changed = False
    ledgers = {}
    for collection in ('creditHolds', 'creditPendingRequests'):
        for request_id, record in list(wallet.get(collection, {}).items()):
            if not isinstance(record, dict) or not record.get('operationId'):
                continue
            entry = None
            reference = record.get('ledgerPath')
            if reference:
                try:
                    path = resolve_path(reference, wallet_path)
                    if path not in ledgers:
                        ledgers[path] = json.loads(path.read_text(encoding='utf-8'))
                    ledger = ledgers[path]
                    if ledger.get('operationId') == record['operationId']:
                        entry = next((item for item in ledger.get('requests', [])
                                      if item.get('requestId') == request_id), None)
                except (OSError, ValueError, TypeError, AttributeError):
                    pass  # A lost or incomplete ledger is not evidence of a zero-cost response.
            confirmed = None
            if entry and entry.get('state') == 'not_sent':
                confirmed = Decimal(0)
            elif entry and entry.get('state') == 'settled' and entry.get('estimatedUsd') is not None:
                try:
                    confirmed = _amount(entry['estimatedUsd'])
                except (ValueError, ArithmeticError):
                    pass
            if request_id in wallet.get('creditCharges', {}):
                settle(wallet, request_id, record, 0, rate)
                changed = True
            elif confirmed is not None:
                settle(wallet, request_id, record, confirmed, rate)
                changed = True
            elif collection == 'creditHolds' and (record.get('unknown') or not owner_alive(wallet_path, record)):
                pending(wallet, request_id, record, now,
                        'usage_unconfirmed' if record.get('unknown') else 'owner_stopped')
                changed = True
    return changed
