"""K1.2.0 admission: retain hard reservations and record unsent waiting.

Admission never changes a prompt, output ceiling, wallet balance or operation
budget. A failed large reservation is not a permanent ban on smaller requests.
"""
import threading
import time
import uuid

POLL_SECONDS = .5


class WalletState:
    def __init__(self):
        self.lock = threading.Lock()
        self.until, self.value = 0, None

    def read(self, billing):
        with self.lock:
            if time.monotonic() >= self.until:
                self.value = _wallet(billing)
                self.until = time.monotonic() + POLL_SECONDS
            return self.value


def _wallet(billing):
    from pdf_credit_billing import wallet_lock, balance, available
    with wallet_lock(billing.path) as wallet:
        return (balance(wallet), available(wallet),
                any(not h.get('unknown') for h in wallet.get('creditHolds', {}).values()))


def _credit_error(provider, error, required_usd=None):
    from pdf_ai import CreditExceeded
    from pdf_credit_billing import decimal, RATE
    balance, available, _ = _wallet(provider.billing)
    required_usd = (required_usd if required_usd is not None
                    else getattr(error, 'reservation_required_usd', None))
    detail = (provider.billing.stop_message() +
              f' 남은 잔고 {balance * decimal("2.3"):.2f}원'
              f' · 지금 예약 가능한 금액 {available * decimal("2.3"):.2f}원')
    if required_usd is not None:
        detail += f' · 이 단락의 예약 필요액 {decimal(required_usd) * RATE * decimal("2.3"):.2f}원'
    detail += '이에요. 예약액은 실제 청구액이 아니며, 전송하지 않은 요청에는 비용이 들지 않아요.'
    failure = CreditExceeded(detail)
    failure.reservation_required_usd = required_usd
    failure.available_credits = str(available)
    failure.balance_credits = str(balance)
    return failure


class AdmissionRecord:
    """All attempts share a unit map, not Provider's thread-local context."""
    def __init__(self, provider, attempt):
        self.provider, self.attempt = provider, attempt
        context = dict(getattr(provider, 'context', {}) or {})
        self.units = list(context.get('unitIds') or [])
        self.started = time.monotonic()
        self.value = {'startedAtMs': int(time.time() * 1000), 'waitIntervals': [],
                      'reservationWaitSeconds': 0., 'reservationWaitChecks': 0}
        self.token = getattr(attempt, 'token', None) or uuid.uuid4().hex
        with provider._lock:
            if not hasattr(provider, '_admission_timings'): provider._admission_timings = {}
            for unit in self.units:
                provider._admission_timings.setdefault(unit, {})[self.token] = self.value

    def wait_finished(self, started, wall_started, checks):
        elapsed = time.monotonic() - started
        with self.provider._lock:
            self.value['waitIntervals'].append([wall_started, wall_started + elapsed * 1000])
            self.value['reservationWaitSeconds'] += elapsed
            self.value['reservationWaitChecks'] += checks

    def finish(self, error=None):
        with self.provider._lock:
            self.value.update(endedAtMs=int(time.time() * 1000),
                              totalSeconds=round(time.monotonic() - self.started, 3),
                              state='failed' if error else 'completed')
            if error is not None:
                self.value.update(error=type(error).__name__, failureReason=str(error))
            entry = getattr(self.attempt, 'entry', None)
            if isinstance(entry, dict):
                self.value['requestId'] = entry.get('requestId')
                entry.update(reservationWaitSeconds=round(self.value['reservationWaitSeconds'], 3),
                             reservationWaitChecks=self.value['reservationWaitChecks'])


def complete(provider, payload, options):
    from pdf_ai import BudgetExceeded, CreditExceeded
    from pdf_credit_billing import CreditReservationPending, decimal, RATE
    from pdf_pipeline import check_cancel
    attempt = options.get('_hedge_attempt')
    record = AdmissionRecord(provider, attempt)
    error_out = None
    try:
        while True:
            check_cancel(provider.folder)
            if attempt is not None: attempt.check()
            billing = getattr(provider, 'billing', None)
            if billing is not None and billing.exhausted:
                # Recheck the wallet after a different envelope was too large.
                # reserve() still atomically checks THIS request's entire bound;
                # clearing this shortcut cannot admit an unfunded request.
                balance, _, _ = _wallet(billing)
                if balance > 0: billing.exhausted = False
            try:
                return provider._complete_once(payload, **options)
            except BudgetExceeded as error:
                # Never resend an acknowledged/reserved request here.
                if attempt is not None and (attempt.entry is not None or attempt.sent is not None): raise
                wallet_wait = (isinstance(error.__cause__, CreditReservationPending)
                               and hasattr(error, 'reservation_wait_usd'))
                operation_wait = hasattr(error, 'operation_wait_usd')
                if isinstance(error, CreditExceeded) and billing is not None:
                    raise _credit_error(provider, error) from error
                if not wallet_wait and not operation_wait: raise
                if wallet_wait:
                    with provider._lock:
                        if not hasattr(provider, '_k120_wallet_state'):
                            provider._k120_wallet_state = WalletState()
                wait_started, wall_started, checks = time.monotonic(), time.time() * 1000, 0
                try:
                    while True:
                        time.sleep(POLL_SECONDS)
                        check_cancel(provider.folder)
                        if attempt is not None: attempt.check()
                        checks += 1
                        if wallet_wait:
                            balance, available, active = provider._k120_wallet_state.read(billing)
                            required = decimal(error.reservation_wait_usd) * RATE
                            if balance < required or (available < required and not active):
                                raise _credit_error(provider, error, error.reservation_wait_usd) from error
                            ready = available >= required
                        else:
                            with provider._lock:
                                active = sum(x['reservedUsd'] for x in provider.ledger['requests']
                                             if x.get('state') == 'reserved')
                                ready = provider.spent + error.operation_wait_usd <= provider.max_usd
                                if not ready and not active: raise error
                        if ready: break
                finally:
                    record.wait_finished(wait_started, wall_started, checks)
    except BaseException as error:
        error_out = error
        raise
    finally:
        record.finish(error_out)
