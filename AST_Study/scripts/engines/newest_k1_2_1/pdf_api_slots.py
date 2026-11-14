"""Cross-process request slots and rolling API admission for every PDF worker.

The account's confirmed Build tier is the default. Launch is an explicit local
setting, never inferred from a requested concurrency or a model name. State only
contains anonymous timing/token counts and allowlisted rate-limit headers.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import math
import os
import re
import tempfile
from threading import Lock
import time
import uuid

from synesis_paths import runtime_state

MAX_PARALLEL_REQUESTS = 14
MAX_STARTUP_PARALLEL_REQUESTS = 16
STARTUP_PRIORITY_REQUESTS = 2
RATE_WINDOW_SECONDS = 60.0
RATE_UTILIZATION = .80


@dataclass(frozen=True)
class Admission:
    directory: Path
    model: str
    ticket: str
    max_output: int


class RateLimitRequestTooLarge(ValueError):
    """One request cannot fit the configured account/project safety budget."""


def _try_lock(handle):
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(handle):
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _handle(path):
    handle = path.open('a+b')
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    return handle


def _root(directory):
    root = Path(directory) if directory is not None else runtime_state() / 'api-slots'
    root.mkdir(parents=True, exist_ok=True)
    return root


class StartupPrioritySlots:
    """A document's two-use capability, shared explicitly with its workers.

    The scheduler closes it on the first completed network request. Closing
    never interrupts an admitted request; subsequent admissions drain to 14.
    The capability contains no document identifiers or request contents.
    """
    def __init__(self, root, marker):
        self.directory = root.resolve()
        self._marker = marker
        self._pid = os.getpid()
        self._remaining = STARTUP_PRIORITY_REQUESTS
        self._open = True
        self._mutex = Lock()

    def close(self):
        # Take the shared admission guard before the in-process capability
        # mutex, matching api_slot's order and preventing a close/claim race.
        if os.getpid() != self._pid:
            return
        guard = _handle(self.directory / 'rate-state.lock')
        try:
            while not _try_lock(guard):
                time.sleep(.005)
            try:
                with self._mutex:
                    if not self._open:
                        return
                    self._open = False
                    path = Path(self._marker.name)
                    _unlock(self._marker)
                    self._marker.close()
                    try:
                        path.unlink()
                    except OSError:
                        pass
            finally:
                _unlock(guard)
        finally:
            guard.close()


@contextmanager
def startup_priority_slots(directory=None):
    """Open an initial-fill window for at most two explicit priority calls.

    Pass the yielded capability to api_slot(priority=capability), including in
    worker threads. Other requests can only occupy the ordinary 14 locks. The
    first two priority admissions use separate locks 14/15; all processes still
    share the hard limit of 16. Call capability.close() on the first network
    completion, and always exit this context when the document operation ends.
    An OS-held marker lock, rather than a persisted counter, survives crashes
    safely: an unlocked leftover marker never grants startup capacity.
    """
    root = _root(directory).resolve()
    guard = _handle(root / 'rate-state.lock')
    marker = None
    try:
        try:
            while not _try_lock(guard):
                time.sleep(.005)
            try:
                marker = _handle(root / ('startup-' + uuid.uuid4().hex + '.lock'))
                if not _try_lock(marker):
                    raise RuntimeError('cannot acquire startup lifetime lock')
                capability = StartupPrioritySlots(root, marker)
            finally:
                _unlock(guard)
        finally:
            guard.close()
    except BaseException:
        if marker is not None:
            marker.close()
        raise
    try:
        yield capability
    finally:
        capability.close()


def _tier_limits(model):
    # Standard public limits; a lower observed account/project limit wins below.
    tier = os.environ.get('SYNESIS_OPENAI_TIER', 'build').strip().lower()
    launch = tier == 'launch'
    luna = model.startswith('gpt-6-luna')
    tokens = (10_000_000 if luna else 4_000_000) if launch else (2_000_000 if luna else 1_000_000)
    return tokens, (10_000 if launch else 5_000)


def _bucket(model):
    # Snapshot names share the same model-family bucket; unrelated models do not.
    for family in ('gpt-6-luna', 'gpt-6-sol', 'gpt-6-astra', 'gpt-6-terra'):
        if model == family or model.startswith(family + '-'):
            return family
    return model


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _load(root, now):
    path = root / 'rate-state.json'
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(state, dict) or not isinstance(state.get('models'), dict):
            raise ValueError('invalid state')
        for record in state['models'].values():
            if not isinstance(record, dict) or not isinstance(record.get('requests', []), list):
                raise ValueError('invalid bucket')
            if any(not isinstance(row, list) or len(row) not in (2,3) or
                   not all(_number(x) and x >= 0 for x in row[:2]) or
                   (len(row)==3 and (not isinstance(row[2],str) or not 0<len(row[2])<=128))
                   for row in record.get('requests', [])):
                raise ValueError('invalid request')
            observed = record.get('observed', {})
            if (not isinstance(observed, dict) or
                    any(not _number(value) or value < 0 for value in observed.values())):
                raise ValueError('invalid observation')
        if not _number(state.get('blockedUntil', 0)):
            raise ValueError('invalid recovery time')
        return state
    except FileNotFoundError:
        return {'models': {}}
    except (ValueError, TypeError):
        # Do not turn a damaged state file into fresh capacity. Recover after a
        # full window; save this marker so polling cannot restart that window.
        state = {'models': {}, 'blockedUntil': now + RATE_WINDOW_SECONDS}
        _save(root, state)
        return state


def _save(root, state):
    fd, name = tempfile.mkstemp(prefix='.r-', suffix='.tmp', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, separators=(',', ':'))
        os.replace(name, root / 'rate-state.json')
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _prune(state, now):
    for record in state['models'].values():
        record['requests'] = [row for row in record.get('requests', [])
                              if row[0] > now - RATE_WINDOW_SECONDS]


def _capacity(model, record):
    tokens, requests = _tier_limits(model)
    observed = record.get('observed', {})
    for key, current in (('tokens', tokens), ('requests', requests)):
        value = observed.get('limit_' + key)
        if _number(value) and value > 0:
            if key == 'tokens':
                tokens = min(current, value)
            else:
                requests = min(current, value)
    project_tokens = observed.get('limit_project-tokens')
    if _number(project_tokens) and project_tokens > 0:
        tokens = min(tokens, project_tokens)
    return max(1, int(tokens * RATE_UTILIZATION)), max(1, int(requests * RATE_UTILIZATION))


def _allowed(state, model, cost, now):
    if state.get('blockedUntil', 0) > now:
        return False
    _prune(state, now)
    record = state['models'].setdefault(_bucket(model), {'requests': []})
    tokens, requests = _capacity(model, record)
    if cost > tokens:
        raise RateLimitRequestTooLarge('요청 한 개가 분당 토큰 안전 한도를 넘어요. 요청 범위를 더 작게 나눠 주세요.')
    rows = record['requests']
    if len(rows) >= requests or sum(row[1] for row in rows) + cost > tokens:
        return False
    observed = record.get('observed', {})
    # A server header can expose other clients' traffic in the shared project.
    # Count our own admissions after that observation against its remainder.
    for key in ('tokens', 'requests', 'project-tokens'):
        observed_at = observed.get('at_' + key, 0)
        later = [row for row in rows if row[0] >= observed_at]
        amount = (1 + len(later) if key == 'requests'
                  else cost + sum(row[1] for row in later))
        reset = observed.get('reset_' + key, 0)
        remaining = observed.get('remaining_' + key)
        if _number(reset) and reset > now and _number(remaining) and amount > remaining:
            return False
    return True


def _startup_open(root):
    # Called under the admission guard. A crashed process leaves only an
    # unlocked anonymous marker; never interpret its mere existence as a grant.
    for path in root.glob('startup-*.lock'):
        handle = _handle(path)
        try:
            if not _try_lock(handle):
                return True
            _unlock(handle)
        finally:
            handle.close()
        try:
            path.unlink()
        except OSError:
            pass
    return False


def _slot(root, priority, parallel_limit=None):
    """Probe actual lock ownership and choose once under the admission guard."""
    free = []
    selected = None
    used_priority = False
    base = MAX_PARALLEL_REQUESTS if parallel_limit is None else parallel_limit
    startup_allowed = parallel_limit not in (40,60,80)
    peak = MAX_STARTUP_PARALLEL_REQUESTS if parallel_limit is None else base + (STARTUP_PRIORITY_REQUESTS if startup_allowed else 0)
    # Inspect the largest live profile even for legacy callers so they see the
    # actual cross-process occupancy rather than only their first 14/20 locks.
    inspected = max(80, MAX_STARTUP_PARALLEL_REQUESTS, peak)
    try:
        for number in range(inspected):
            handle = _handle(root / f'{number}.lock')
            if _try_lock(handle):
                free.append((number, handle))
            else:
                handle.close()
        active = inspected - len(free)
        eligible = False
        if priority is not None and startup_allowed:
            with priority._mutex:
                eligible = priority._open and priority._remaining > 0 and priority._pid == os.getpid()
        if eligible:
            # Priority calls alone can use these two locks. A third flagged
            # request is an ordinary request, even while startup is still open.
            candidates = [handle for number, handle in free if number >= base
                          and peak - STARTUP_PRIORITY_REQUESTS <= number < peak
                          and active < base + STARTUP_PRIORITY_REQUESTS]
            if candidates:
                selected = candidates[0]
                used_priority = True
        elif active < base or startup_allowed and active < base + STARTUP_PRIORITY_REQUESTS and _startup_open(root):
            candidates = [handle for number, handle in free if number < base]
            if candidates:
                selected = candidates[0]
        return selected, used_priority
    finally:
        for _, handle in free:
            if handle is not selected:
                _unlock(handle)
                handle.close()


@contextmanager
def api_slot(check=None, directory=None, *, model=None, input_tokens=0, max_output=0, priority=None,
             parallel_limit=None, count_parallel=True, input_tokens_estimator=None):
    """Admit once, then hold a shared slot only during the network request.

    Legacy callers without a model retain global slot limiting. Model-aware
    callers reserve max(conservative input estimate, output ceiling) for 60 s.
    Waiting never sends or retries a paid request and regularly checks cancel.
    Default callers use 14 ordinary / 16 startup requests; parallel_limit=20
    selects 20 / 22; parallel_limit=40, 60 or 80 has no extra startup slots.
    A two-use capability grants startup priority in the legacy profiles. A trusted
    hedge may bypass count admission, but still reserves shared TPM/RPM usage.
    An optional local input estimator is refreshed only before admission, outside
    the shared rate lock. Invalid evidence falls back to the original input bound;
    the output ceiling and all server/project limits remain unchanged.
    """
    if model is not None and (not isinstance(model, str) or not model):
        raise ValueError('model must be a nonempty string')
    if parallel_limit is not None and (type(parallel_limit)is not int or parallel_limit not in (20,40,60,80)):
        raise ValueError('unsupported parallel profile')
    if type(count_parallel)is not bool:
        raise ValueError('count_parallel must be boolean')
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
           for value in (input_tokens, max_output)):
        raise ValueError('token estimates must be nonnegative integers')
    if input_tokens_estimator is not None and not callable(input_tokens_estimator):
        raise ValueError('input estimator must be callable')
    if priority is False:
        priority = None
    if priority is not None and not isinstance(priority, StartupPrioritySlots):
        raise ValueError('priority must be an explicit startup capability or None')
    root = _root(directory).resolve()
    if priority is not None and priority.directory != root:
        raise ValueError('startup capability belongs to a different slot directory')
    held = None
    admitted = False
    admission = None
    while not admitted:
        if check is not None:
            check()
        estimated_input = input_tokens
        # Never call a provider-dependent function while holding rate-state.lock:
        # usage settlement can hold the provider lock before taking that lock.
        if model is not None and input_tokens_estimator is not None:
            try:
                candidate = input_tokens_estimator()
                if type(candidate) is int and 0 <= candidate <= input_tokens:
                    estimated_input = candidate
            except Exception:
                pass
        cost = max(1, estimated_input, max_output)
        guard = _handle(root / 'rate-state.lock')
        try:
            if _try_lock(guard):
                try:
                    if model is not None:
                        now = time.time()
                        state = _load(root, now)
                        allowed = _allowed(state, model, cost, now)
                    else:
                        allowed = True
                    if allowed:
                        held, used_priority = _slot(root, priority, parallel_limit) if count_parallel else (None, False)
                        if held is not None or not count_parallel:
                            try:
                                if model is not None:
                                    admission = Admission(root,_bucket(model),uuid.uuid4().hex,max_output)
                                    state['models'][admission.model]['requests'].append([now,cost,admission.ticket])
                                    _save(root, state)
                                if used_priority:
                                    with priority._mutex:
                                        priority._remaining -= 1
                                admitted = True
                            except BaseException:
                                if held is not None:
                                    _unlock(held)
                                    held.close()
                                held = None
                                raise
                finally:
                    _unlock(guard)
        finally:
            guard.close()
        if not admitted:
            time.sleep(.025)
    try:
        yield admission
    finally:
        if held is not None:
            _unlock(held)
            held.close()


def settle_rate_usage(admission, input_tokens, max_output):
    """Refine this request's input bound only after receiving measured usage.

    The output ceiling stays reserved; actual completion length is deliberately
    not used. Failed/unknown requests never call this function and retain their
    full admission estimate. No request is removed, so RPM remains unchanged.
    A missed observation/write leaves the conservative reservation in place and
    never invalidates the already paid response.
    """
    if not isinstance(admission,Admission):return False
    if any(not isinstance(value,int) or isinstance(value,bool) or value<0
           for value in (input_tokens,max_output)):return False
    cost=max(1,input_tokens,max_output,admission.max_output)
    guard=None
    try:
        guard=_handle(admission.directory/'rate-state.lock')
        deadline=time.monotonic()+1
        while not _try_lock(guard):
            if time.monotonic()>=deadline:return False
            time.sleep(.005)
        try:
            now=time.time()
            state=_load(admission.directory,now)
            _prune(state,now)
            record=state['models'].get(admission.model,{})
            for row in record.get('requests',[]):
                if len(row)==3 and row[2]==admission.ticket:
                    row[1]=cost
                    _save(admission.directory,state)
                    return True
            # An expired ticket, a legacy row without a ticket or a different
            # process/model's admission cannot consume or refund a fresh slot.
            return False
        finally:
            _unlock(guard)
    except (OSError,ValueError,TypeError):
        return False
    finally:
        if guard is not None:guard.close()


_DURATION = re.compile(r'(\d+(?:\.\d+)?)(ms|s|m|h)')


def _reset_seconds(value):
    text = str(value).strip().lower()
    if not text:
        return None
    parts = list(_DURATION.finditer(text))
    if not parts or ''.join(part.group(0) for part in parts) != text:
        return None
    return sum(float(part.group(1)) * {'ms': .001, 's': 1, 'm': 60, 'h': 3600}[part.group(2)]
               for part in parts)


def observe_rate_limits(model, headers, directory=None):
    """Share allowlisted response limits; header values never elevate the tier.

    Invalid/missing headers are ignored. Other headers, URLs, keys and response
    contents are never retained. Observation errors do not discard a paid reply.
    """
    if not isinstance(model, str) or not model or headers is None:
        return
    try:
        values = {str(k).lower(): v for k, v in headers.items()}
        observed = {}
        for dimension in ('tokens', 'requests', 'project-tokens'):
            for kind in ('limit', 'remaining'):
                value = values.get(f'x-ratelimit-{kind}-{dimension}')
                if value is not None:
                    try:
                        number = int(str(value))
                    except (ValueError, TypeError):
                        continue
                    if number >= 0 and (kind != 'limit' or number > 0):
                        observed[f'{kind}_{dimension}'] = number
            reset = _reset_seconds(values.get(f'x-ratelimit-reset-{dimension}', ''))
            if reset is not None and 0 <= reset <= 86_400:
                observed['reset_' + dimension] = time.time() + reset
        if not observed:
            return
        root = _root(directory)
        guard = _handle(root / 'rate-state.lock')
        try:
            # Never delay receipt/preservation of a paid reply over observation.
            if not _try_lock(guard):
                return
            try:
                now = time.time()
                state = _load(root, now)
                _prune(state, now)
                record = state['models'].setdefault(_bucket(model), {'requests': []})
                old = record.get('observed', {})
                # A partial header set must not erase a known lower project cap.
                old.update(observed)
                for dimension in ('tokens', 'requests', 'project-tokens'):
                    if 'remaining_' + dimension in observed:
                        old['at_' + dimension] = now
                record['observed'] = old
                _save(root, state)
            finally:
                _unlock(guard)
        finally:
            guard.close()
    except (OSError, ValueError, TypeError):
        return
