"""Cross-process local credit accounting. No provider/model/prompt changes."""
from contextlib import contextmanager
from decimal import Decimal
from synesis_paths import resolve_path, portable
from pathlib import Path
import json
import os
import tempfile
import threading
import time

RATE = Decimal(1400) / Decimal('2.3')
_LOCK = threading.RLock()
START_MESSAGE = '크레딧이 부족해서 요약/개념 생성을 하지 못했어요.'
STOP_MESSAGE = '크레딧이 부족해서 요약/개념 생성이 중단됐어요. 완료된 내용은 보관했어요.'

class InsufficientCredits(RuntimeError):
    pass

class CreditReservationPending(InsufficientCredits):
    pass

def decimal(value):
    return Decimal(str(value or 0))

@contextmanager
def wallet_lock(path, *, recover=True):
    path = resolve_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.with_suffix('.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.lockf(lock.fileno(), fcntl.LOCK_EX)
        try:
            wallet = json.loads(path.read_text(encoding='utf-8'), parse_float=Decimal)
            if not wallet.get('liveBilling'):
                raise RuntimeError('호출별 크레딧 장부가 준비되지 않았어요.')
            if recover:
                from credit_reservations import reconcile
                if reconcile(path, wallet, RATE, int(time.time()*1000)):
                    save(path, wallet)
            yield wallet
        finally:
            if os.name == 'nt':
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.lockf(lock.fileno(), fcntl.LOCK_UN)

def save(path, wallet):
    fd, temp = tempfile.mkstemp(prefix='credit-billing-', suffix='.tmp', dir=Path(path).parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(portable(wallet, path), stream, ensure_ascii=False, indent=2, default=str)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

def balance(wallet):
    purchased = sum((decimal(p.get('credits')) for p in wallet['purchases']), Decimal(0))
    used = max(Decimal(0), decimal(wallet['highWaterCredits']) - decimal(wallet['baselineCredits']))
    return purchased - used + decimal(wallet.get('balanceAdjustmentCredits'))

def available(wallet):
    return balance(wallet) - sum((decimal(h['credits']) for h in wallet.get('creditHolds', {}).values()), Decimal(0))

class Billing:
    def __init__(self, path, operation_id, category, created_at_ms=None, ledger_path=None):
        self.path = resolve_path(path)
        self.operation_id, self.category = operation_id, category
        self.created_at_ms = created_at_ms or int(time.time()*1000)
        self.exhausted = False
        self.ledger_path = str(ledger_path) if ledger_path is not None else None

    def stop_message(self):
        if self.category == 'summary':
            return STOP_MESSAGE
        if self.category == 'planning':
            return '크레딧이 부족해서 묶음 판단이 중단됐어요. 완료된 판단 기록은 보관했어요.'
        if self.category == 'quiz':
            return '크레딧이 부족해서 문제집 생성을 중단했어요. 완료된 문제는 보관했어요.'
        return '크레딧이 부족해서 AI 답변을 생성하지 못했어요.'

    def record(self):
        with wallet_lock(self.path) as wallet:
            operations=wallet.setdefault('creditOperations', {})
            if self.operation_id not in operations:
                operations[self.operation_id]={'category':self.category,'createdAtMs':self.created_at_ms,
                                               'credits':'0','unknownRequests':0}
                save(self.path,wallet)

    def admission(self, maximum_usd):
        required = decimal(maximum_usd) * RATE * Decimal('.95')
        with wallet_lock(self.path) as wallet:
            if required > 0 and available(wallet) < required:
                raise InsufficientCredits(START_MESSAGE)

    def planning_admission(self):
        required=Decimal(8)/Decimal('2.3')
        with wallet_lock(self.path) as wallet:
            if available(wallet)<required:
                raise InsufficientCredits('크레딧이 부족해서 묶음 판단을 시작하지 못했어요. 최소 8원 상당의 크레딧이 필요해요.')

    def reserve(self, request_id, usd, *, split_before_stop=False, reservation_metadata=None):
        if self.exhausted: raise InsufficientCredits(self.stop_message())
        credits = decimal(usd) * RATE
        if not credits.is_finite() or credits < 0:raise ValueError('Invalid credit reservation')
        from pdf_k120_reservation import metadata
        policy=metadata(reservation_metadata)
        if policy and decimal(policy.get('customerReservedUsd'))!=decimal(usd):
            raise ValueError('Customer reservation differs from its recorded estimate')
        with wallet_lock(self.path) as wallet:
            if policy and (request_id in wallet.get('creditCharges', {})
                           or request_id in wallet.get('creditPendingRequests', {})):
                return  # Reusing a request ID never holds customer funds again.
            old=wallet.get('creditHolds',{}).get(request_id)
            if policy and old:
                if old.get('operationId')!=self.operation_id or decimal(old.get('credits'))!=credits:
                    raise ValueError('Existing credit reservation changed')
                return
            if available(wallet) < credits:
                if split_before_stop:
                    # A trusted, still-unsent batch may be split into smaller
                    # requests. Its larger output reservation must not make
                    # the ordinary smaller-request credit stop sticky yet.
                    raise CreditReservationPending('묶음의 예약 비용을 감당하기 어려워 더 작은 요청으로 나눠 확인해요.')
                active = any(not hold.get('unknown') for hold in wallet.get('creditHolds', {}).values())
                if balance(wallet) >= credits and active:
                    raise CreditReservationPending('진행 중인 호출의 실제 비용 확인 후 다시 시도해요.')
                self.exhausted = True
                raise InsufficientCredits(self.stop_message())
            from credit_reservations import owner
            wallet.setdefault('creditHolds', {})[request_id] = {
                'credits':str(credits), 'operationId':self.operation_id, 'createdAtMs':int(time.time()*1000),
                'operationCreatedAtMs':self.created_at_ms, 'category':self.category,
                'ledgerPath':self.ledger_path, **owner(self.path), **policy}
            wallet.setdefault('creditOperations', {}).setdefault(self.operation_id, {
                'category':self.category, 'createdAtMs':self.created_at_ms, 'credits':'0', 'unknownRequests':0})
            save(self.path, wallet)

    def settle(self, request_id, usd=None):
        with wallet_lock(self.path) as wallet:
            from credit_reservations import pending, settle
            if request_id in wallet.get('creditCharges', {}): return dict(wallet['creditCharges'][request_id])
            record = (wallet.get('creditPendingRequests', {}).get(request_id)
                      or wallet.get('creditHolds', {}).get(request_id)
                      or {'operationId':self.operation_id, 'category':self.category,
                          'createdAtMs':self.created_at_ms, 'ledgerPath':self.ledger_path})
            if usd is None:
                pending(wallet, request_id, record, int(time.time()*1000), 'usage_unconfirmed')
            else:
                settle(wallet, request_id, record, usd, RATE)
            save(self.path, wallet)
            charge=wallet.get('creditCharges',{}).get(request_id)
            return dict(charge) if charge else None
