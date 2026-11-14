"""Locked shared money admission for explicitly approved, isolated experiments.

No credentials or network transport are loaded. ``approved-window.json`` is an
external, explicit approval checkpoint, never created or expanded by this code.
The original registry remains cumulative; only IDs after that checkpoint consume
the new approval. Without a checkpoint the historical $1 / $0.98 cap applies.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from audit_pdf_cost_metrics import request_metrics, reserve_amount, usage_metrics

ACCOUNTING_VERSION = 1
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _money(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(name + ' must be finite and nonnegative.')
    return value


def _sum(rows):
    return float(sum((Decimal(str(_money(row['amountUsd'], 'amountUsd'))) for row in rows), Decimal(0)))


def _request_id(entry):
    key = entry.get('requestId') if isinstance(entry, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise ValueError('A nonempty requestId is required.')
    return key


def _atomic_json(path, data):
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class SharedBudget:
    """All providers/variants at ``root`` use one thread/process-locked registry.

    ``reserve`` raises the active Provider module's ``BudgetExceeded`` before
    network access. Reusing a request ID is an error, including previously
    cancelled requests. ``settle`` cannot release an unknown paid reservation.
    Snapshots reconcile registered IDs against saved run ledgers, leaving both
    ledgers and unregistered historical operations untouched.
    """

    def __init__(self, root, variant):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not isinstance(variant, str) or not variant.strip():
            raise ValueError('A variant name is required.')
        self.variant = variant
        self.path = self.root / 'budget.json'
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(str(self.root), threading.RLock())

    @contextmanager
    def _locked(self):
        with self._lock, (self.root / 'budget.lock').open('a+b') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _read(self):
        data = (json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else
                {'limitUsd': 1.0, 'requests': {}, 'scope': 'new calls for this request only'})
        if not isinstance(data, dict) or data.get('limitUsd') != 1.0 or not isinstance(data.get('requests'), dict):
            raise ValueError('The historical $1 registry must remain intact.')
        for key, row in data['requests'].items():
            if not isinstance(key, str) or not key or not isinstance(row, dict):
                raise ValueError('Invalid aggregate request registry.')
            _money(row.get('amountUsd'), 'amountUsd')
        return data

    def _approval(self, data):
        path = self.root / 'approved-window.json'
        if not path.exists():
            if data.get('approvedWindowSha256'):
                raise ValueError('The bound explicit approval checkpoint is missing.')
            return set(), 1.0, .98, None
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if data.get('approvedWindowSha256') not in (None, digest):
            raise ValueError('An active approval checkpoint cannot be changed implicitly.')
        approval = json.loads(raw)
        if (not isinstance(approval, dict) or approval.get('schemaVersion') != 1 or
                not isinstance(approval.get('authorization'), str) or not approval['authorization'].strip() or
                not isinstance(approval.get('createdAtUtc'), str) or not approval['createdAtUtc'].strip()):
            raise ValueError('An explicit, dated approval is required.')
        limit = _money(approval.get('approvedLimitUsd'), 'approvedLimitUsd')
        execution = _money(approval.get('executionCapUsd'), 'executionCapUsd')
        # An approval never spends its final two cents of contingency headroom.
        if limit <= .02 or execution <= 0 or Decimal(str(execution)) > Decimal(str(limit)) - Decimal('.02'):
            raise ValueError('The approved window must retain at least $0.02 headroom.')
        ids = approval.get('checkpointRequestIds')
        if (not isinstance(ids, list) or any(not isinstance(key, str) or not key for key in ids) or
                len(set(ids)) != len(ids) or not set(ids).issubset(data['requests'])):
            raise ValueError('Approval IDs must be unique existing aggregate requests.')
        if approval.get('baseRequestCount', len(ids)) != len(ids):
            raise ValueError('Approval checkpoint count does not match its IDs.')
        _money(approval.get('baseActualKnownUsd'), 'baseActualKnownUsd')
        _money(approval.get('baseCommittedUsd'), 'baseCommittedUsd')
        data['approvedWindowSha256'] = digest
        return set(ids), limit, execution, {
            key: approval[key] for key in ('createdAtUtc', 'authorization', 'approvedLimitUsd',
                'executionCapUsd', 'baseActualKnownUsd', 'baseCommittedUsd')}

    @staticmethod
    def _apply_metrics(old, entry, metrics):
        state = entry.get('state')
        if state == 'not_sent' and 'sentAtMs' in entry:
            raise ValueError('A transmitted request cannot be released as not_sent.')
        terminal = old.get('state') in ('settled', 'not_sent')
        if terminal and state not in ('settled', 'not_sent'):
            return  # A stale ledger reservation cannot undo a known settlement.
        if terminal and state != old['state']:
            raise ValueError('Conflicting terminal states for an aggregate request.')
        if (state == old.get('state') == 'settled' and 'estimatedUsd' in old and
                old['estimatedUsd'] != entry.get('estimatedUsd')):
            raise ValueError('Conflicting settled amounts for an aggregate request.')
        amount = metrics['committedUsd']
        if state not in ('settled', 'not_sent'):
            amount = max(old['amountUsd'], amount)
        old.update(state=state, amountUsd=amount,
                   reservedUsd=entry.get('reservedUsd', old.get('reservedUsd', 0)),
                   estimatedUsd=entry.get('estimatedUsd', 0),
                   actualKnownUsd=metrics['usageBasedUsd'] + metrics['additionalCacheWritePremiumUsd'],
                   missingCacheWriteUpperBoundUsd=metrics['missingCacheWriteUpperBoundUsd'],
                   conservativeUnknownReservedUsd=(amount if state not in ('settled', 'not_sent') else 0))
        if 'cacheWritePremiumUsd' in entry:
            old['cacheWritePremiumUsd'] = entry['cacheWritePremiumUsd']

    def _reconcile(self, data):
        entries = []
        # Nested run folders also support small batch probes. Do not scan copied
        # source/backups, and never enroll an unrelated request into this cap.
        for path in sorted((self.root / 'runs').glob('**/usage/*.json')):
            ledger = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(ledger, dict) or not isinstance(ledger.get('requests'), list):
                raise ValueError('A persisted usage ledger must retain its request array.')
            matching = [entry for entry in ledger['requests']
                        if isinstance(entry, dict) and entry.get('requestId') in data['requests']]
            if matching and ledger.get('model') != 'gpt-6-luna':
                raise ValueError('This experiment cap supports gpt-6-luna only.')
            entries.extend(matching)
        totals = usage_metrics(entries)
        by_id = {row['requestId']: row for row in totals['requestMetrics']}
        # usage_metrics already detects conflicts and resolves stale snapshots.
        # Keep the same selected state and largest unresolved reservation when
        # choosing the full entry, rather than a later stale ledger snapshot.
        selected = {}
        for entry in entries:
            key = entry['requestId']
            if entry.get('state') != by_id[key]['state']:
                continue
            if (key not in selected or entry.get('state') in ('settled', 'not_sent') or
                    entry.get('reservedUsd', 0) > selected[key].get('reservedUsd', 0)):
                selected[key] = entry
        for key, metrics in by_id.items():
            self._apply_metrics(data['requests'][key], selected[key], metrics)
        data['accountingVersion'] = ACCOUNTING_VERSION

    def _summarize(self, data, approval):
        checkpoint, limit, execution, metadata = approval
        rows = list(data['requests'].values())
        current = [row for key, row in data['requests'].items() if key not in checkpoint]
        data.update(committedUsd=_sum(rows),
                    settledUsd=_sum(row for row in rows if row.get('state') == 'settled'),
                    requestCount=len(rows))
        committed = _sum(current)
        data['activeWindow'] = {
            'approvedLimitUsd': limit, 'executionCapUsd': execution,
            'committedUsd': committed,
            'settledUsd': _sum(row for row in current if row.get('state') == 'settled'),
            'actualKnownUsd': math.fsum(row.get('actualKnownUsd', row.get('estimatedUsd', 0))
                                       for row in current if row.get('state') == 'settled'),
            'missingCacheWriteUpperBoundUsd': math.fsum(row.get('missingCacheWriteUpperBoundUsd', 0) for row in current),
            'conservativeUnknownReservedUsd': _sum(row for row in current if row.get('state') not in ('settled', 'not_sent')),
            'requestCount': len(current), 'checkpointRequestCount': len(checkpoint),
            'remainingUsd': max(0., float(Decimal(str(limit)) - Decimal(str(committed)))),
            'executionRemainingUsd': max(0., float(Decimal(str(execution)) - Decimal(str(committed))))}
        if metadata:
            data['activeWindow'].update(approval=metadata, approvalPath='approved-window.json')
        return data

    def _operate(self, entry=None, settle=False, reconcile=False):
        with self._locked():
            data = self._read()
            if reconcile or data.get('accountingVersion') != ACCOUNTING_VERSION:
                self._reconcile(data)
            approval = self._approval(data)
            self._summarize(data, approval)
            if entry is not None:
                key = _request_id(entry)
                if settle:
                    if key not in data['requests']:
                        raise ValueError('An aggregate request must be reserved before settlement.')
                    old = data['requests'][key]
                    if old.get('variant') != self.variant:
                        raise ValueError('A variant cannot settle another variant\'s reservation.')
                    self._apply_metrics(old, entry, request_metrics(entry))
                else:
                    if key in data['requests']:
                        raise ValueError('Duplicate aggregate reservation.')
                    if entry.get('state') != 'reserved':
                        raise ValueError('Only an unsent reserved request can be admitted.')
                    amount = reserve_amount(entry.get('reservedUsd'))
                    window = data['activeWindow']
                    if Decimal(str(window['committedUsd'])) + Decimal(str(amount)) > Decimal(str(window['executionCapUsd'])):
                        # Lazy import keeps snapshots/metrics offline and preserves
                        # exception identity when a frozen Provider is imported.
                        from pdf_ai import BudgetExceeded
                        raise BudgetExceeded('The shared approved experiment window cap was reached.')
                    data['requests'][key] = {'variant': self.variant, 'state': 'reserved',
                        'amountUsd': amount, 'reservedUsd': entry['reservedUsd']}
            self._summarize(data, approval)
            _atomic_json(self.path, data)
            return data

    def reserve(self, entry):
        return self._operate(entry)

    def settle(self, entry):
        return self._operate(entry, settle=True)

    def snapshot(self):
        return self._operate(reconcile=True)
