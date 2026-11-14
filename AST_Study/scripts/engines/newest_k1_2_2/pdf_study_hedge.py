"""One optional hedge: missing ID or confirmed slow K1.1.1 teaching response.

Desktop-only opt-in leaves standalone comparisons unchanged. No timer starts
while waiting for local admission/upload slots. Attempts never share receipts
or overwrite the winner's cache. Unknown loser usage keeps its reservation.
"""
import copy
import re
import threading
import time
import uuid
import pdf_study_tail as tail

DELAY = 10.0
STRATEGIES = {'newest-k1', 'newest-k1-1', 'newest-k1-11', 'newest-k1-1-1', 'newest-k1-1-2','newest-k1-1-3','newest-k1-2-2'}
TASKS = {'region_teaching', 'region_teaching_batch', 'region_groups'}


def enabled(provider, payload, options):
    return (getattr(provider, 'study_no_id_hedge', False)
            and provider.context.get('strategy') in STRATEGIES
            and (provider.context.get('studyDurable') is True or
                 provider.context.get('strategy')=='newest-k1-2-2' and provider.context.get('studyForegroundResponses')is True)
            and isinstance(payload, dict) and payload.get('task') in TASKS
            and not options.get('cache_only') and not options.get('study_recovery'))


class Attempt:
    def __init__(self, race, index):
        self.race, self.index = race, index
        self.token = uuid.uuid4().hex
        self.sent = None
        self.response_id = None
        self.entry = None
        self.canonical = None
        self.cache = None
        self.done = False
        self.value = None
        self.error = None
        self.preview = []
        self.finished = threading.Event()
        self.slow_pending = False
        self.status_checked = None
        self.preview_emitted = False
        self.slow_cause = None

    def update(self, **fields):
        with self.race.lock:
            if fields.get('responseId'):
                self.response_id = fields['responseId']
            if fields.get('networkPhase') == 'uploading_request' and self.sent is None:
                self.sent = time.monotonic()
            if 'slowResponsePending' in fields:
                self.slow_pending = fields['slowResponsePending'] is True
                self.status_checked = time.monotonic()
                self.slow_cause = fields.get('slowResponseCause')
            if fields.get('lastEventType') in ('response.completed','response.incomplete','response.failed','response.cancelled'):
                self.slow_pending = False

    def check(self):
        # Preserve an unidentified connection so a late receipt can still be
        # cancelled/settled. A known losing job uses normal server cancellation.
        with self.race.lock:
            if (self.response_id or self.sent is None) and self.race.winner not in (None, self):
                raise InterruptedError('Study hedge superseded')

    def cancellation_reason(self):
        return 'hedge_superseded' if self.race.winner not in (None,self) else 'user_cancelled'

    def bind_stream(self, stream):
        pass  # The legacy no-ID policy retains its original receipt channel.

    def delta(self, value):
        with self.race.lock:
            if self.race.hedged:
                self.preview.append(value)
            elif self.race.preview is not None:
                self.race.preview(value)
                self.preview_emitted = True


class Race:
    def __init__(self, provider, payload, options):
        self.provider, self.payload, self.options = provider, payload, options
        self.context = copy_context(provider.context)
        self.lock = threading.RLock()
        self.hedged = False
        self.winner = None
        self.preview = options.get('on_study_delta')
        self.attempts = [Attempt(self, 0)]
        self.started = time.monotonic()
        self.tail_enabled = (getattr(provider,'study_slow_response_hedge',True)
                             and tail.enabled(self.context, payload, options))
        self.hedge_reason = None

    def extra_reason(self, attempt=None):
        """Recheck before reserving: no stale status can authorize a second POST."""
        with self.lock:
            original = self.attempts[0]
            if self.winner is not None or original.sent is None:
                return None
            if original.done:
                entry=original.entry or {}
                if (self.tail_enabled and original.error is not None
                        and entry.get('serverTerminalStatus')=='failed'
                        and entry.get('serverErrorCode')=='server_error'):
                    return 'confirmed_server_failure'
                return None
            now = time.monotonic()
            if original.response_id is None and now-original.sent >= DELAY:
                return 'missing_response_id'
            if (self.tail_enabled and original.response_id and original.slow_pending
                    and now-original.sent >= (tail.OUTPUT_LOOP_AFTER_SECONDS
                        if original.slow_cause=='repeated_terminal_controls' else tail.AFTER_SECONDS)
                    and original.status_checked is not None
                    and now-original.status_checked <= tail.STATUS_FRESH_SECONDS):
                return ('confirmed_output_loop' if original.slow_cause=='repeated_terminal_controls'
                        else 'confirmed_slow_response')
            return None

    def launch(self, attempt):
        def run():
            try:
                self.provider.context = copy_context(self.context)
                options = {**self.options, 'on_study_delta': attempt.delta}
                options.pop('on_delivery_reset',None)
                complete = getattr(self.provider, '_complete_admitted', self.provider._complete_once)
                value = complete(self.payload, **options, _hedge_attempt=attempt)
                schema = (self.options.get('response_format') or {}).get('json_schema', {}).get('schema')
                if schema:
                    from pdf_study_batch_transport import _validate
                    _validate(value, schema, schema)
                self.accept_result(attempt,value)
            except Exception as error:
                with self.lock:
                    attempt.error = error
            finally:
                with self.lock:
                    attempt.done = True
                attempt.finished.set()
        # A late unidentified loser cannot hold the learner's completed result
        # hostage. Its reservation and private receipt survive worker shutdown.
        thread = threading.Thread(target=run, name='study-no-id-'+str(attempt.index), daemon=True)
        thread.start()

    def accept_result(self, attempt, value):
        with self.lock:
            attempt.value = value
            if self.winner is None:self.winner = attempt

    def run(self):
        from pdf_pipeline import check_cancel, write_json
        original = self.attempts[0]
        self.launch(original)
        while True:
            check_cancel(self.provider.folder)
            with self.lock:
                winner = self.winner
                if winner is not None:
                    break
                reason = self.extra_reason() if not self.hedged else None
                if all(a.done for a in self.attempts) and reason is None:
                    error = original.error or self.attempts[-1].error
                    if self.hedged:
                        error.study_hedge_exhausted = True
                    raise error
                if reason is not None:
                    self.hedged = True
                    self.hedge_reason = reason
                    extra = Attempt(self, 1)
                    self.attempts.append(extra)
                    self.launch(extra)
            time.sleep(.02)
        # Each attempt has a private raw/receipt cache. Only validated winner
        # content is published to the established logical cache identity.
        if winner.canonical is not None:
            write_json(winner.canonical, winner.value)
        with self.provider._lock:
            for attempt in self.attempts:
                if attempt.entry is not None:
                    attempt.entry.update(hedgeWinner=attempt is winner,
                                         hedgeExtraStarted=self.hedged,
                                         hedgeResultSeconds=round(time.monotonic()-self.started,3))
                    if self.hedge_reason:attempt.entry['hedgeReason']=self.hedge_reason
            if any(a.entry is not None for a in self.attempts):
                write_json(self.provider.ledger_path, self.provider.ledger)
        if self.hedged and self.preview is not None:
            if winner is not original and original.preview_emitted:
                # Never append the replacement to the original's partial text.
                reset=self.options.get('on_delivery_reset')
                if callable(reset):reset()
            for part in winner.preview:
                self.preview(part)
        return winner.value


def complete(provider, payload, options):
    if (provider.context.get('strategy') in ('newest-k1-1-2','newest-k1-1-3','newest-k1-2-2')
            and provider.context.get('kind')=='region_study'
            and payload.get('task')=='region_teaching'):
        from pdf_study_progress_attempts import FourAttemptRace
        return FourAttemptRace(provider,payload,options).run()
    if (provider.context.get('strategy')=='newest-k1-1-1'
            and provider.context.get('kind')=='region_study'
            and payload.get('task')=='region_teaching'):
        from pdf_study_attempts import FourAttemptRace
        return FourAttemptRace(provider,payload,options).run()
    return Race(provider, payload, options).run()


def copy_context(context):
    # Share the two-use startup capability, including its mutex, rather than
    # trying to deep-copy a lock or minting additional priority admissions.
    result=copy.deepcopy({key:value for key,value in context.items() if key!='_startup_priority'})
    if '_startup_priority'in context:result['_startup_priority']=context['_startup_priority']
    return result


def recover_cached(provider, canonical, response_format, *, exclude_group=None):
    """Recover privately cached paid success after a crash before publication."""
    from pdf_pipeline import read_json_cache, write_json
    from pdf_study_batch_transport import _validate
    from pdf_study_rejection import is_rejected
    schema=(response_format or {}).get('json_schema',{}).get('schema')
    if not schema:return None
    with provider._lock:
        ledgers=[provider.ledger]
        for path in (provider.folder/'usage').glob('*.json'):
            if path!=provider.ledger_path:
                ledger=read_json_cache(path)
                if isinstance(ledger,dict):ledgers.append(ledger)
        for ledger in ledgers:
            for entry in ledger.get('requests',[]):
                # A live sibling must win through this race's deadline/validation
                # checks, never by being re-labelled as another attempt's cache.
                if (exclude_group is not None and entry.get('hedgeGroup')==exclude_group
                        or entry.get('attemptExpired') is True
                        or entry.get('clientStopReason') in ('attempt_deadline','hedge_superseded','user_cancelled')):
                    continue
                key=entry.get('responseCacheKey','')
                if (entry.get('logicalResponseCacheKey')!=canonical.stem
                        or not isinstance(key,str) or not re.fullmatch('[a-f0-9]{64}',key)):
                    continue
                private=canonical.with_name(key+'.json')
                if is_rejected(private,entry):continue
                value=read_json_cache(private)
                if not isinstance(value,dict):continue
                try:_validate(value,schema,schema)
                except (ValueError,TypeError,KeyError):continue
                write_json(canonical,value)
                return value
    return None
