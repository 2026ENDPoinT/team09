"""Observe an acknowledged response without closing its active SSE connection.

Only final text resets silence. Status reads never create a generation, and
only an identity-checked terminal response can replace the live stream.
"""
import json
import socket
import threading
import urllib.error
import urllib.request
from collections import deque
from pdf_study_tail import WINDOW_SECONDS, MIN_WINDOW_CHARS, OUTPUT_LOOP_AFTER_SECONDS, native_timings

INTERVAL = 10.0
TERMINAL = ('completed', 'incomplete', 'failed', 'cancelled')


class StatusReady(Exception):
    pass


class IdleStatusWatch:
    def __init__(self, request, stream, *, open_url, update, check, clock, timeout,
                 started=None, tail_after=None, foreground=False):
        self.request, self.stream = request, stream
        self.open_url, self.update, self.check, self.clock = open_url, update, check, clock
        self.timeout = timeout
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.thread = None
        self.response_id = None
        self.last_text = clock()
        self.last_poll = float('-inf')
        self.reads = 0
        self.native = None
        self.cancelled = False
        self.failure = None
        self.started = clock() if started is None else started
        self.tail_after = tail_after
        self.progress_samples = deque()
        self.status_history = deque(maxlen=24)
        self.output_loop = False
        self.foreground = foreground

    def _read_error(self, error, prefix):
        fields={prefix+'ReadError':type(error).__name__}
        if self.foreground and isinstance(error,urllib.error.HTTPError):
            fields[prefix+'HttpStatus']=error.code
            # Foreground generations are not necessarily retrievable until
            # storage completes. A 404 neither stops their SSE nor settles cost.
            if error.code==404:fields[prefix+'ReceiptPending']=True
        self.update(**fields)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        with self.lock:
            self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=.2)

    def acknowledge(self, response_id):
        with self.lock:
            if self.thread is not None:
                return
            self.response_id = response_id
            # The first check is ten seconds after acknowledgement; no GET is
            # possible before an ID exists, even if receipt delivery was slow.
            self.last_text = self.clock()
            self.thread = threading.Thread(target=self._observe, name='study-idle-status', daemon=True)
            self.thread.start()

    def progress(self, chars=0, *, output_loop=False):
        with self.lock:
            self.last_text = self.clock()
            self.progress_samples.append((self.last_text, chars))
            self._window_chars(self.last_text)
            self.output_loop = self.output_loop or output_loop

    def _window_chars(self, now):
        while self.progress_samples and self.progress_samples[0][0] < now-WINDOW_SECONDS:
            self.progress_samples.popleft()
        return sum(chars for _, chars in self.progress_samples)

    def check_stream(self):
        self.check()
        with self.lock:
            if self.cancelled:
                raise InterruptedError('Study request cancelled during idle status check')
            if self.native is not None:
                raise StatusReady()
            if self.failure is not None:
                raise OSError('Idle status observer stopped') from self.failure

    def _observe(self):
        try:
            self._run()
        except Exception as error:
            # A broken observer must never leave the main thread blocked on an
            # unbounded socket. Fall back to the existing bounded GET recovery.
            with self.lock:
                if not self.stopped.is_set():
                    self.failure = error
                    self._interrupt_read()

    def recover_now(self):
        """Bounded, read-only terminal lookup before K1.1.2 replaces a stall.

        The request's stream owner still validates and settles the response.
        A heartbeat/status alone never updates its last output timestamp.
        """
        with self.lock:
            if self.native is not None:return True
            if self.response_id is None:return False
            response_id=self.response_id
        auth=self.request.get_header('Authorization')
        request=urllib.request.Request('https://api.openai.com/v1/responses/'+response_id,
            headers={**({'Authorization':auth} if isinstance(auth,str) else {}),
                     'Cache-Control':'no-cache'},method='GET')
        try:
            with self.open_url(request,timeout=min(self.timeout,6.0)) as response:
                value=json.load(response)
            if not isinstance(value,dict) or value.get('id')!=response_id:
                raise ValueError('Status response ID mismatch')
            with self.lock:
                if self.native is not None:return True
                self.update(stallStatus=value.get('status'),stallStatusChecked=True)
                if value.get('status') in TERMINAL:
                    self.native=value
                    self.update(networkPhase='recovered_original',recoveredOriginalResponse=True,
                                idleStatusRecovered=True,streamReconnects=0)
                    self._interrupt_read()
                    return True
        except (OSError,ValueError) as error:
            self._read_error(error,'stallStatus')
        return False

    def _interrupt_read(self):
        # Shutdown wakes a blocked BufferedReader without concurrently closing
        # its buffer. The owning request thread closes/releases it normally.
        try:
            self.stream.fp.raw._sock.shutdown(socket.SHUT_RDWR)
        except (AttributeError, OSError):
            pass

    def _run(self):
        while not self.stopped.wait(.05):
            try:
                self.check()
            except InterruptedError:
                with self.lock:
                    if self.stopped.is_set():
                        return
                    self.cancelled = True
                    self._interrupt_read()
                return
            with self.lock:
                if self.stopped.is_set():
                    return
                now = self.clock()
                next_check = self.last_text + INTERVAL
                if self.tail_after is not None:
                    # Slow trickles can keep the idle timer fresh indefinitely.
                    # After the tail threshold, check status even while SSE lives.
                    next_check = min(next_check, self.started+self.tail_after)
                    if self.output_loop:next_check=min(next_check,self.started+OUTPUT_LOOP_AFTER_SECONDS)
                if now < max(next_check, self.last_poll + INTERVAL):
                    continue
                self.last_poll = now
                self.reads += 1
                self.update(idleStatusReads=self.reads, idleStatusCheckIntervalSeconds=INTERVAL,
                            idleStatusSilenceSeconds=round(now-self.last_text, 4))
            auth = self.request.get_header('Authorization')
            get = urllib.request.Request(
                'https://api.openai.com/v1/responses/' + self.response_id,
                headers={**({'Authorization': auth} if isinstance(auth, str) else {}),
                         'Cache-Control': 'no-cache'}, method='GET')
            try:
                with self.open_url(get, timeout=self.timeout) as response:
                    value = json.load(response)
                if not isinstance(value, dict) or value.get('id') != self.response_id:
                    raise ValueError('Status response ID mismatch')
                with self.lock:
                    if self.stopped.is_set():
                        return
                    status = value.get('status')
                    ended = self.clock()
                    chars = self._window_chars(ended)
                    row = {'atSeconds': round(ended-self.started, 4),
                           'readSeconds': round(ended-now, 4), 'status': status,
                           'recentTextChars': chars, **native_timings(value)}
                    self.status_history.append(row)
                    if status in TERMINAL + ('queued', 'in_progress'):
                        slow = (self.tail_after is not None and status in ('queued', 'in_progress')
                                and ((ended-self.started >= self.tail_after and chars < MIN_WINDOW_CHARS)
                                     or (ended-self.started >= OUTPUT_LOOP_AFTER_SECONDS and self.output_loop)))
                        self.update(idleStatus=status, idleStatusHistory=list(self.status_history),
                                    slowResponsePending=slow, slowResponseAgeSeconds=round(ended-self.started,4),
                                    slowResponseWindowChars=chars,
                                    slowResponseCause='repeated_terminal_controls' if self.output_loop else 'low_text_progress',
                                    **native_timings(value))
                    if status in TERMINAL:
                        self.native = value
                        self.update(networkPhase='recovered_original', recoveredOriginalResponse=True,
                                    idleStatusRecovered=True, streamReconnects=0)
                        self._interrupt_read()
                        return
            except (OSError, ValueError) as error:
                # A failed read is not evidence that the original job failed.
                # Keep consuming its SSE and retry only this GET after 10s.
                with self.lock:
                    if not self.stopped.is_set():
                        self._read_error(error,'idleStatus')


def watched_events(events, watch):
    try:
        yield from events
    except (OSError, ValueError, StatusReady):
        # Socket shutdown after a GET completion may surface as EOF or OSError.
        if watch.cancelled:
            raise InterruptedError('Study request cancelled during idle status check')
        if watch.native is None:
            raise
        yield {'type': 'response.' + watch.native['status'], 'response': watch.native}
