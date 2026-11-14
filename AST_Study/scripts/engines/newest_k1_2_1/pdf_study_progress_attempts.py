"""K1.1.2: 30s backup; after 60s, check 30s output stalls every 10s.

Each attempt sends the identical source and owns its own receipt/cost hold.
Retry count admission is separate; Provider still enforces shared TPM and money.
Local admission/upload-slot waiting does not consume an API request's deadline.
"""
import socket
import threading
import time

from pdf_study_hedge import Attempt, Race

BACKUP_SECONDS = 30.0
ATTEMPT_SECONDS = 60.0
STALL_SECONDS = 30.0
CHECK_SECONDS = 10.0
MAX_ATTEMPTS = 4


class TimedAttempt(Attempt):
    def __init__(self, race, index, *, reason='initial', replaces=None):
        super().__init__(race,index)
        self.reason, self.replaces = reason, replaces
        self.stop_reason = None
        self.expired = False
        self.replacement_handled = False
        self.stream = None
        self.socket = None
        self.cancel_callback = None
        self.cancel_started = False
        self.last_output = None
        self.output_chars = 0
        self.next_check = None
        self.probing = False
        self.terminal_pending = False
        self.status_probe = None
        self.stall_checks = 0

    def _interrupt_read(self):
        # Wake a blocked read without closing its BufferedReader concurrently.
        # The owning request then closes it and cancels its known server ID.
        try:
            connection=self.socket if self.socket is not None else self.stream.fp.raw._sock
            connection.shutdown(socket.SHUT_RDWR)
        except (AttributeError,OSError):pass

    def bind_socket(self, connection):
        # Cover upload/header waiting before an HTTP response stream exists.
        # The transport clears the reference before returning/releasing it.
        with self.race.lock:
            self.socket=connection
            if connection is not None and (self.stop_reason is not None
                    or self.race.winner not in (None,self)):
                self._interrupt_read()

    def stop(self, reason):
        with self.race.lock:
            if self.done or self is self.race.winner:return
            if self.stop_reason is None:self.stop_reason=reason
            if reason=='attempt_deadline':self.expired=True
            self._interrupt_read()
            self._cancel_background()

    def bind_cancel(self, callback):
        with self.race.lock:
            self.cancel_callback=callback
            if self.stop_reason is not None:self._cancel_background()

    def _cancel_background(self):
        if self.cancel_started or self.cancel_callback is None:return
        self.cancel_started=True
        def cancel():
            try:self.cancel_callback()
            except Exception:pass  # Unknown cost remains reserved in the ledger.
        # Send the known server ID's cancellation immediately, independently of
        # a stuck read. Only this bounded control call survives worker exit.
        threading.Thread(target=cancel,name='study-attempt-cancel',daemon=False).start()

    def bind_stream(self, stream):
        with self.race.lock:
            self.stream=stream
            if self.stop_reason is not None or self.race.winner not in (None,self):
                self._interrupt_read()

    def update(self, **fields):
        super().update(**fields)
        with self.race.lock:
            chars = fields.get('finalTextChars')
            if isinstance(chars, int) and chars > self.output_chars:
                self.output_chars = chars
                self.last_output = time.monotonic()

    def bind_status_probe(self, callback):
        with self.race.lock:
            self.status_probe = callback

    def check(self):
        # Cancellation only. The supervisor owns the periodic stall decision;
        # stream readers must not impose the old unconditional 60s cutoff.
        with self.race.lock:
            if self.stop_reason is not None or self.race.winner not in (None,self):
                raise InterruptedError('Study attempt stopped: '+self.cancellation_reason())

    def stalled(self, now):
        last = self.last_output if self.last_output is not None else self.sent
        return (self.sent is not None and now-self.sent >= ATTEMPT_SECONDS
                and last is not None and now-last >= STALL_SECONDS)

    def check_stall(self, now):
        with self.race.lock:
            if (self.done or self.stop_reason is not None or self.sent is None
                    or self.race.winner is not None or self.probing or self.terminal_pending):
                return False
            due = self.next_check if self.next_check is not None else self.sent+ATTEMPT_SECONDS
            if now < due:return False
            self.next_check = now+CHECK_SECONDS
            self.stall_checks += 1
            if self.entry is not None:
                self.entry.update(stallChecks=self.stall_checks,
                    stallCheckAgeSeconds=round(now-self.sent,3),
                    outputSilenceSeconds=round(now-(self.last_output if self.last_output is not None else self.sent),3))
            if not self.stalled(now):return True
            self.probing = True
            # Capture progress as well as time: any resumed output during the
            # GET protects this request, even if that control read is delayed.
            observed_chars = self.output_chars
            probe = self.status_probe
        def inspect():
            terminal = False
            try:
                if probe is not None:terminal = probe()
            except Exception:
                pass  # A bounded failed GET is not a completed result.
            finally:
                with self.race.lock:
                    self.probing = False
                    if self.done or self.race.winner is not None or self.stop_reason is not None:return
                    if terminal:
                        # The stream owner consumes, validates and bills the
                        # recovered receipt via the established path.
                        self.terminal_pending = True
                    elif self.output_chars == observed_chars and self.stalled(time.monotonic()):
                        self.stop('attempt_deadline')
        threading.Thread(target=inspect,name='study-stall-check',daemon=True).start()
        return True

    def cancellation_reason(self):
        return self.stop_reason or super().cancellation_reason()

    def delta(self, value):
        with self.race.lock:
            self.check()
            if self.race.buffer_preview:self.preview.append(value)
            else:super().delta(value)


class FourAttemptRace(Race):
    policy_metadata = {'hedgePolicy':'four-attempts-progress-30-60-v1',
                       'hedgeMaxAttempts':MAX_ATTEMPTS,'hedgeDelaySeconds':BACKUP_SECONDS,
                       'hedgeStallCheckAfterSeconds':ATTEMPT_SECONDS,
                       'hedgeOutputStallSeconds':STALL_SECONDS,'hedgeStallCheckIntervalSeconds':CHECK_SECONDS}

    def __init__(self, provider, payload, options):
        super().__init__(provider,payload,options)
        self.attempts=[TimedAttempt(self,0)]
        # Status reads still recover a completed original. They no longer decide
        # whether a 30s backup is permitted, nor trigger earlier extra requests.
        self.tail_enabled=False
        self.backup_started=False
        self.blocked_error=None
        self.closed=False
        self.backup_seconds=20.0 if self.context.get('strategy')=='newest-k1-2-1' else BACKUP_SECONDS
        if self.context.get('strategy')=='newest-k1-2-1':
            self.policy_metadata={**self.policy_metadata,'hedgeDelaySeconds':20.0,
                                  'hedgePolicy':'four-attempts-receipt-stall60-idle30-v1','hedgeKnownReceiptPolicy':'status_and_stall_only','hedgeDeferOnFinalTextWithinSeconds':10.0}
        # Without a reset callback, keep partial candidates private so a backup
        # can never be appended to the original's unfinished JSON/prose.
        self.buffer_preview=self.preview is not None and not callable(options.get('on_delivery_reset'))

    def extra_reason(self, attempt=None):
        with self.lock:
            if (self.winner is not None or attempt not in self.attempts
                    or not 0 < attempt.index < MAX_ATTEMPTS or attempt.stop_reason is not None):
                return None
            return attempt.reason

    def accept_result(self, attempt, value):
        with self.lock:
            attempt.check()
            attempt.value=value
            if self.winner is None:self.winner=attempt

    def _append(self, reason, replaces=None):
        attempt=TimedAttempt(self,len(self.attempts),reason=reason,replaces=replaces)
        self.attempts.append(attempt)
        self.hedged=True
        self.hedge_reason=reason
        return attempt

    def _write_state(self):
        from pdf_pipeline import write_json
        with self.provider._lock:
            for a in self.attempts:
                if a.entry is None:continue
                a.entry.update(hedgeExtraStarted=len(self.attempts)>1,
                               hedgeReason=a.reason,attemptExpired=a.expired,
                               hedgeAttemptsScheduled=len(self.attempts),hedgeRaceFinished=self.closed)
                if a.replaces is not None:a.entry['replacesAttempt']=a.replaces
                if a.stop_reason is not None:a.entry['clientStopReason']=a.stop_reason
                if self.winner is not None:
                    a.entry.update(hedgeWinner=a is self.winner,
                                   hedgeResultSeconds=round(time.monotonic()-self.started,3))
            if any(a.entry is not None for a in self.attempts):
                write_json(self.provider.ledger_path,self.provider.ledger)

    def _retry_blocked(self, attempt):
        from pdf_ai import BudgetExceeded, CreditExceeded, RemoteDisabled
        from pdf_auth_rejection import is_authentication_rejection
        return (isinstance(attempt.error,(BudgetExceeded,CreditExceeded,RemoteDisabled))
                or (attempt.entry is None and isinstance(attempt.error,(ValueError,TypeError)))
                or is_authentication_rejection(attempt.entry or {}))

    def run(self):
        from pdf_ai import AiResponseError
        from pdf_pipeline import check_cancel, write_json
        self.launch(self.attempts[0])
        try:
            while True:
                check_cancel(self.provider.folder)
                launches=[];changed=False
                with self.lock:
                    if self.winner is not None:break
                    now=time.monotonic()
                    for a in self.attempts:
                        if a.check_stall(now):changed=True
                        if a.done and a.error is not None and self._retry_blocked(a):
                            self.blocked_error=a.error
                    # A failed/expired lane is replaced once. Cleanup may still
                    # be settling its receipt; it cannot hold up the new request.
                    for a in list(self.attempts):
                        if (a.done or a.expired) and not a.replacement_handled:
                            a.replacement_handled=True
                            if len(self.attempts)<MAX_ATTEMPTS and self.blocked_error is None:
                                reason='attempt_deadline' if a.expired else 'attempt_failed'
                                launches.append(self._append(reason,a.index));changed=True
                    live=[a for a in self.attempts if not a.done and not a.expired]
                    if (not self.backup_started and len(live)==1 and live[0].sent is not None
                            and now-live[0].sent>=self.backup_seconds and len(self.attempts)<MAX_ATTEMPTS
                            and self.blocked_error is None
                            and live[0].response_id is None
                            and not (live[0].last_output is not None and now-live[0].last_output<10.0)):
                        launches.append(self._append('elapsed_'+str(int(self.backup_seconds))+'_seconds',live[0].index))
                        self.backup_started=True;changed=True
                    if not live and not launches:
                        error=self.blocked_error
                        if error is None:
                            error=AiResponseError('같은 단락을 최대 4회 요청했지만 정상 완료된 결과를 받지 못했어요. '
                                                  '완료된 다른 단락은 보관했어요. 잠시 후 이 단락을 다시 생성해 주세요.')
                        error.study_hedge_exhausted=True  # No fifth delivery fallback.
                        raise error
                if changed:self._write_state()
                for attempt in launches:self.launch(attempt)
                time.sleep(.02)
            winner=self.winner
            if winner.canonical is not None:write_json(winner.canonical,winner.value)
            self._write_state()
            if (self.hedged or self.buffer_preview) and self.preview is not None:
                original=self.attempts[0]
                if winner is not original and original.preview_emitted:
                    reset=self.options.get('on_delivery_reset')
                    if callable(reset):reset()
                for part in winner.preview:self.preview(part)
            return winner.value
        finally:
            self.closed=True
            for a in self.attempts:
                if a is not self.winner:a.stop('hedge_superseded' if self.winner is not None else 'user_cancelled')
            self._write_state()
