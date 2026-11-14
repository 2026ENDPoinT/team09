"""K1.1.3 only: wait for temporary reservations, before sending an attempt.

No sleep holds Provider._lock. Settlement, other PDFs, cancellation and a winning
sibling remain free to progress. A waiter reuses the SAME attempt (no POST/retry
budget/timer is consumed). Unknown usage retains the operation's conservative cap.
"""
import threading
import time

POLL_SECONDS = .5
_LOCK = threading.Lock()


class WalletState:
    def __init__(self):
        self.lock = threading.Lock()
        self.until = 0
        self.value = None

    def read(self, billing):
        from pdf_credit_billing import wallet_lock, balance, available
        with self.lock:
            if time.monotonic() >= self.until:
                with wallet_lock(billing.path) as wallet:
                    self.value = (balance(wallet), available(wallet),
                        any(not h.get('unknown') for h in wallet.get('creditHolds', {}).values()))
                self.until = time.monotonic() + POLL_SECONDS
            return self.value


def complete(provider, payload, options):
    from pdf_ai import BudgetExceeded, CreditExceeded
    from pdf_credit_billing import CreditReservationPending, decimal, RATE
    from pdf_pipeline import check_cancel
    attempt = options.get('_hedge_attempt')
    started = None
    checks = 0
    while True:
        check_cancel(provider.folder)
        if attempt is not None: attempt.check()
        try:
            value = provider._complete_once(payload, **options)
            if started is not None and attempt is not None and attempt.entry is not None:
                # API latency is still measured from attempt.sent, not this wait.
                attempt.entry.update(reservationWaitSeconds=round(waited, 3),
                                     reservationWaitChecks=checks)
            return value
        except BudgetExceeded as error:
            # Never repeat a sent request or reinterpret a genuine spending cap.
            if attempt is not None and (attempt.entry is not None or attempt.sent is not None): raise
            wallet_wait = (isinstance(error.__cause__, CreditReservationPending)
                           and hasattr(error, 'reservation_wait_usd'))
            operation_wait = hasattr(error, 'operation_wait_usd')
            if not wallet_wait and not operation_wait: raise
            if started is None: started = time.monotonic()
            if wallet_wait:
                with _LOCK:
                    if not hasattr(provider, '_k113_wallet_state'):
                        provider._k113_wallet_state = WalletState()
            while True:
                time.sleep(POLL_SECONDS)
                check_cancel(provider.folder)
                if attempt is not None: attempt.check()
                checks += 1
                if wallet_wait:
                    balance, available, active = provider._k113_wallet_state.read(provider.billing)
                    required = decimal(error.reservation_wait_usd) * RATE
                    if balance < required or (available < required and not active):
                        raise CreditExceeded(provider.billing.stop_message()) from error
                    ready = available >= required
                else:
                    with provider._lock:
                        active = sum(x['reservedUsd'] for x in provider.ledger['requests']
                                     if x.get('state') == 'reserved')
                        ready = provider.spent + error.operation_wait_usd <= provider.max_usd
                        if not ready and not active: raise error
                if ready: break
            waited = time.monotonic() - started
