"""Independent connect / upload-idle / response-header phases for pooled HTTP.

The request bytes and Content-Length stay untouched. A healthy upload can outlive
the connect/header allowance; only a blocked write times out. Every attempted body byte is bounded before
the write. Only a proven incomplete JSON body can reconnect; ambiguous final
writes cannot. TLS and proxy setup remain owned by urllib3, and policy is scoped to the calling thread rather than a shared pool.
"""
from contextlib import contextmanager
import http.client
import sys
import threading
import time
import urllib3

CONNECT_TIMEOUT = 15.0
UPLOAD_IDLE_TIMEOUT = 30.0
WRITE_CHUNK_BYTES = 16 * 1024
_POLICY = threading.local()


class UploadPolicy:
    def __init__(self, request, timeout, *, control, update, check, clock=time.monotonic,
                 on_uploaded=lambda:None,on_socket=lambda connection:None):
        self.update, self.check, self.clock = update, check, clock
        self.auxiliary = control or request.method != 'POST'
        self.idle_timeout = min(timeout, UPLOAD_IDLE_TIMEOUT) if control else UPLOAD_IDLE_TIMEOUT
        self.body_size = len(request.data) if isinstance(request.data, (bytes, bytearray)) else None
        self.body_sent = self.wire_sent = 0
        self.write_attempted = False
        self.cancelled = False
        self.phase = 'connecting'
        self.upload_started = None
        self.last_update = 0.0
        self.body_attempted_upper = 0
        self.on_uploaded = on_uploaded
        self.on_socket = on_socket

    def diagnostics(self, **fields):
        if self.auxiliary:
            fields = {'control' + key[0].upper() + key[1:]: value for key, value in fields.items()}
        self.update(**fields)

    def check_active(self):
        try:
            self.check()
        except InterruptedError:
            # urllib3 wraps OSError subclasses (including InterruptedError) in
            # ProtocolError. Keep cancellation identity outside that wrapper.
            self.cancelled = True
            raise

    def connecting(self):
        self.check_active()
        self.phase = 'connecting'
        self.diagnostics(networkPhase=self.phase)

    def writing(self, size, headers):
        self.check_active()
        if self.upload_started is None:
            self.upload_started = self.clock()
            self.phase = 'uploading_request'
            self.diagnostics(networkPhase=self.phase, requestWriteIdleTimeoutSeconds=self.idle_timeout,
                        requestBodyBytesExpected=self.body_size)

    def progress(self, size, headers):
        self.wire_sent += size
        if not headers:
            self.body_sent += size
        now = self.clock()
        # A big image should not produce a ledger/UI write per TLS record.
        if now - self.last_update >= .2:
            self.last_update = now
            stamp = int(time.time() * 1000)
            fields = {'lastNetworkProgressAtMs': stamp} if self.body_sent else {}
            self.diagnostics(requestBodyBytesSent=self.body_sent, requestWireBytesSent=self.wire_sent,
                             lastUploadProgressAtMs=stamp, **fields)

    def uploaded(self):
        self.on_uploaded()
        self.phase = 'waiting_headers'
        fields = {'lastNetworkProgressAtMs': int(time.time() * 1000)} if self.body_sent else {}
        self.diagnostics(networkPhase=self.phase, requestBodyBytesSent=self.body_sent,
                    requestWireBytesSent=self.wire_sent,
                    requestUploadSeconds=round(self.clock() - self.upload_started, 4)
                    if self.upload_started is not None else 0.,
                    requestUploadComplete=self.body_size is None or self.body_sent == self.body_size,
                    **fields)

    def failed(self):
        self.diagnostics(transportFailurePhase=self.phase, requestBodyBytesSent=self.body_sent,
                    requestWireBytesSent=self.wire_sent,
                    requestWriteAttempted=self.write_attempted,
                    requestBodyBytesAttemptedUpperBound=self.body_attempted_upper)


@contextmanager
def upload_policy(policy):
    previous = getattr(_POLICY, 'value', None)
    _POLICY.value = policy
    try:
        yield
    finally:
        _POLICY.value = previous


class _ProgressConnection:
    def connect(self):
        policy = getattr(_POLICY, 'value', None)
        if policy is not None:
            policy.connecting()
        self._synesis_connecting = True
        try:
            # Includes CONNECT tunnelling and TLS certificate verification.
            return super().connect()
        finally:
            self._synesis_connecting = False

    def request(self, *args, **kwargs):
        self._synesis_sending_headers = True
        result = super().request(*args, **kwargs)
        policy = getattr(_POLICY, 'value', None)
        if policy is not None:
            policy.uploaded()
        return result

    def send(self, data):
        policy = getattr(_POLICY, 'value', None)
        # CONNECT is part of connection setup, not bytes of the model request.
        if policy is None or getattr(self, '_synesis_connecting', False):
            return super().send(data)
        if self.sock is None:
            if self.auto_open:
                self.connect()
            else:
                raise http.client.NotConnected()
        headers = getattr(self, '_synesis_sending_headers', True)
        policy.on_socket(self.sock)
        policy.writing(len(data) if isinstance(data, (bytes, bytearray, memoryview)) else 0, headers)
        self.sock.settimeout(policy.idle_timeout)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            # The production API uses bytes. Keep the stdlib contract for other
            # body types, while conservatively recording any attempted write.
            policy.write_attempted = True
            result = super().send(data)
        else:
            sys.audit('http.client.send', self, data)
            remaining = memoryview(data).cast('B')
            while remaining:
                policy.check_active()
                # Record the attempt BEFORE send: a timeout can leave some bytes
                # on the wire without returning an exact count. It is not proof
                # of zero transmission and must never enable another POST.
                policy.write_attempted = True
                if not headers:
                    policy.body_attempted_upper=max(policy.body_attempted_upper,
                        policy.body_sent+min(len(remaining),WRITE_CHUNK_BYTES))
                sent = self.sock.send(remaining[:WRITE_CHUNK_BYTES])
                if sent <= 0:
                    raise ConnectionResetError('Study upload connection closed')
                remaining = remaining[sent:]
                policy.progress(sent, headers)
            result = None
        self._synesis_sending_headers = False
        return result


class ProgressHTTPConnection(_ProgressConnection, urllib3.connection.HTTPConnection):
    pass


class ProgressHTTPSConnection(_ProgressConnection, urllib3.connection.HTTPSConnection):
    pass


class ProgressHTTPPool(urllib3.connectionpool.HTTPConnectionPool):
    ConnectionCls = ProgressHTTPConnection


class ProgressHTTPSPool(urllib3.connectionpool.HTTPSConnectionPool):
    ConnectionCls = ProgressHTTPSConnection


def configure_upload_pools(manager):
    # Copy the mapping; changing urllib3's process-global registry would affect
    # unrelated clients, mocks, and pools that use different timeout contracts.
    manager.pool_classes_by_scheme = {**manager.pool_classes_by_scheme,
                                      'http': ProgressHTTPPool, 'https': ProgressHTTPSPool}
