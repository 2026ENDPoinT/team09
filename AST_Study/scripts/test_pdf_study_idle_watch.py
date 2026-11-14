"""Offline socket tests: a blocked live SSE coexists with read-only status GETs."""
import io
import json
import socket
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import pdf_study_connection as net
import pdf_study_idle_watch as idle
from test_pdf_responses_transport import native
from test_pdf_stream_resume import request, create


class LiveStream:
    def __init__(self):
        self.reader, self.writer = socket.socketpair()
        self.file = self.reader.makefile('rb')
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=self.reader))
        self.headers = {'Content-Type': 'text/event-stream'}
        self.closed = False
        self.send(create())

    def send(self, event):
        self.writer.sendall(('data: ' + json.dumps(event) + '\n\n').encode())

    def readline(self, size=-1):
        return self.file.readline(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        self.file.close()
        self.reader.close()


class IdleWatchTests(unittest.TestCase):
    def setUp(self):
        self.stream = LiveStream()
        self.addCleanup(self.stream.writer.close)
        self.addCleanup(self.stream.__exit__)
        self.calls = []
        self.updates = []
        self.deltas = []
        self.get = lambda: native()
        self.cancel = False
        self.started = time.monotonic()
        self.get_times = []
        self.interval = patch.object(idle, 'INTERVAL', .15)
        self.interval.start()
        self.addCleanup(self.interval.stop)

    def opener(self, req, timeout):
        self.calls.append(req)
        if req.full_url.endswith('/cancel'):
            return io.StringIO(json.dumps({**native(), 'status': 'cancelled'}))
        if req.method == 'POST':
            return self.stream
        self.get_times.append(time.monotonic())
        self.assertNotIn('?', req.full_url)
        return io.StringIO(json.dumps(self.get()))

    def check(self):
        if self.cancel:
            raise InterruptedError()

    def run_request(self):
        return net.request_once(request(), open_url=self.opener,
                                update=lambda **x: self.updates.append(x),
                                check=self.check, on_delta=self.deltas.append, resume_stream=True)

    def send_later(self, action):
        thread = threading.Thread(target=action, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(1))
        return thread

    def test_pending_gets_repeat_without_closing_stream_or_reposting(self):
        statuses = iter(['queued', 'in_progress', 'completed'])
        def get():
            self.assertFalse(self.stream.closed)
            return {**native(), 'status': next(statuses)}
        self.get = get
        self.assertEqual(self.run_request(), native())
        self.assertEqual([r.method for r in self.calls], ['POST', 'GET', 'GET', 'GET'])
        self.assertGreaterEqual(self.get_times[0]-self.started, .14)
        self.assertTrue(all(b-a >= .14 for a,b in zip(self.get_times,self.get_times[1:])))
        self.assertTrue(any(u.get('idleStatusRecovered') for u in self.updates))

    def test_deltas_continue_while_get_is_waiting_and_reset_silence(self):
        first = threading.Event()
        delivered = threading.Event()
        delta_at = []
        def send():
            first.wait(2)
            time.sleep(.08)
            delta_at.append(time.monotonic())
            self.stream.send({'type': 'response.output_text.delta', 'delta': 'real text'})
        self.send_later(send)
        def get():
            if len(self.get_times) == 1:
                first.set()
                # The main thread must deliver text without waiting for this GET.
                self.assertTrue(delivered.wait(2))
                return {**native(), 'status': 'in_progress'}
            return native()
        self.get = get
        def on_delta(text):
            self.deltas.append(text)
            delivered.set()
        got = net.request_once(request(), open_url=self.opener, update=lambda **x: None,
                               resume_stream=True, on_delta=on_delta)
        self.assertEqual(got, native())
        self.assertEqual(self.deltas, ['real text'])
        self.assertGreaterEqual(self.get_times[1]-delta_at[0], .14)

    def test_active_stream_longer_than_interval_needs_no_get(self):
        def send():
            for _ in range(8):
                time.sleep(.04)
                self.stream.send({'type': 'response.output_text.delta', 'delta': 'x'})
            self.stream.send({'type': 'response.completed', 'response': native()})
        self.send_later(send)
        self.assertEqual(self.run_request(), native())
        self.assertEqual(len(self.deltas), 8)
        self.assertEqual([r.method for r in self.calls], ['POST'])

    def test_invalid_id_and_network_error_leave_original_alive(self):
        def get():
            self.assertFalse(self.stream.closed)
            if len(self.get_times) == 1:
                return {**native(), 'id': 'resp_wrong'}
            if len(self.get_times) == 2:
                raise TimeoutError()
            return native()
        self.get = get
        self.assertEqual(self.run_request(), native())
        self.assertEqual(len(self.get_times), 3)
        self.assertEqual(sum(r.method=='POST' for r in self.calls), 1)

    def test_stream_completion_wins_over_late_get_without_duplicate_delivery(self):
        release = threading.Event()
        finished = threading.Event()
        def get():
            self.stream.send({'type': 'response.completed', 'response': native()})
            release.wait(2)
            finished.set()
            return {**native(), 'status': 'failed'}
        self.get = get
        try:
            self.assertEqual(self.run_request(), native())
            self.assertFalse(finished.is_set())
        finally:
            release.set()
        self.assertTrue(finished.wait(1))
        time.sleep(.06)
        self.assertFalse(any(u.get('idleStatusRecovered') for u in self.updates))
        self.assertEqual([r.method for r in self.calls], ['POST', 'GET'])

    def test_user_cancel_stops_acknowledged_job_not_new_generation(self):
        def get():
            if len(self.get_times) == 1:
                self.cancel = True
                return {**native(), 'status': 'in_progress'}
            return {**native(), 'status': 'cancelled'}
        self.get = get
        result = self.run_request()
        self.assertIsInstance(result, net.GuardedStudyResponse)
        self.assertEqual(result.reason, 'user_cancelled')
        self.assertEqual(sum(r.full_url.endswith('/cancel') for r in self.calls), 1)
        self.assertEqual(sum(r.method=='POST' and not r.full_url.endswith('/cancel') for r in self.calls), 1)

    def test_keepalives_do_not_reset_text_silence(self):
        def send():
            for _ in range(3):
                time.sleep(.03)
                self.stream.send({'type':'keepalive'})
        self.send_later(send)
        self.assertEqual(self.run_request(), native())
        self.assertEqual(len(self.get_times), 1)
        self.assertLess(self.get_times[0]-self.started, .4)


class PooledIdleIntegrationTests(unittest.TestCase):
    def test_real_ten_second_silence_fetches_terminal_while_pooled_sse_stays_open(self):
        from pdf_study_http import StudyHttpTransport
        release = threading.Event()
        calls = []
        times = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                calls.append('POST')
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                times.append(time.monotonic())
                self.wfile.write(('data: '+json.dumps(create())+'\n\n').encode())
                self.wfile.flush()
                release.wait(15)
            def do_GET(self):
                calls.append('GET')
                times.append(time.monotonic())
                raw = json.dumps(native()).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        transport = StudyHttpTransport()
        url = 'http://127.0.0.1:'+str(server.server_port)
        def open_url(req, timeout):
            local = urllib.request.Request(url+'/responses', data=req.data,
                                            headers=dict(req.header_items()), method=req.method)
            return transport.open(local, timeout)
        result = []; errors = []; done = threading.Event()
        def run():
            try:
                result.append(net.request_once(request(), open_url=open_url,
                                                update=lambda **x:None, resume_stream=True))
            except BaseException as error:
                errors.append(error)
            finally:
                done.set()
        worker = threading.Thread(target=run, daemon=True)
        try:
            self.assertEqual(idle.INTERVAL, 10.0)
            worker.start()
            self.assertTrue(done.wait(13), 'Completed GET must wake the live pooled SSE reader')
            self.assertEqual(errors, [])
            self.assertEqual(result, [native()])
            self.assertEqual(calls, ['POST','GET'])
            self.assertGreaterEqual(times[1]-times[0], 9.9)
            self.assertLess(times[1]-times[0], 12)
        finally:
            release.set()
            worker.join(2)
            transport.close()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
