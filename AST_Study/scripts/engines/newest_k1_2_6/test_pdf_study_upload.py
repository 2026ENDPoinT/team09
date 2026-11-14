"""Upload timeout regressions on loopback TCP/TLS only; no model or paid calls."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import select
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import urllib3

import pdf_study_http as http
import pdf_study_upload as upload


@contextmanager
def receiver(*, pause=0., delay_per_read=0., header_pause=0., tls=None):
    records=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_POST(self):
            record={'length':int(self.headers['Content-Length']),
                    'transferEncoding':self.headers.get('Transfer-Encoding'),
                    'port':self.client_address[1]};records.append(record)
            time.sleep(pause);left=record['length'];digest=hashlib.sha256()
            try:
                while left:
                    data=self.rfile.read(min(16384,left))
                    if not data:return
                    digest.update(data);left-=len(data)
                    if delay_per_read:time.sleep(delay_per_read)
                record['sha256']=digest.hexdigest();time.sleep(header_pause)
                self.reply({'sha256':record['sha256'],'bytes':record['length']})
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
        def do_GET(self):self.reply({'receipt':'original'})
        def reply(self,value):
            data=json.dumps(value).encode();self.send_response(200)
            self.send_header('Content-Length',str(len(data)));self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(data);self.wfile.flush()
    class Server(ThreadingHTTPServer):daemon_threads=True;request_queue_size=64
    server=Server(('127.0.0.1',0),Handler)
    if tls is not None:server.socket=tls.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield ('https'if tls else'http')+'://127.0.0.1:'+str(server.server_port),records
    finally:server.shutdown();server.server_close();thread.join()


@contextmanager
def tunnel_proxy():
    tunnels=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_CONNECT(self):
            host,port=self.path.rsplit(':',1);tunnels.append(self.path)
            upstream=socket.create_connection((host,int(port)),timeout=3)
            self.send_response(200);self.end_headers();self.wfile.flush()
            try:
                while True:
                    readable,_,_=select.select([self.connection,upstream],[],[],3)
                    if not readable:return
                    for current in readable:
                        data=current.recv(65536)
                        if not data:return
                        (upstream if current is self.connection else self.connection).sendall(data)
            except (OSError,ConnectionResetError):pass
            finally:upstream.close();self.close_connection=True
    class Server(ThreadingHTTPServer):daemon_threads=True;request_queue_size=64
    server=Server(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port),tunnels
    finally:server.shutdown();server.server_close();thread.join()


def request(url,body):return urllib.request.Request(url,data=body,method='POST',headers={'Content-Type':'application/json'})


class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name)
        command=[shutil.which('openssl')or'openssl','req','-x509','-newkey','rsa:2048','-nodes',
                 '-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1',
                 '-keyout',str(root/'key.pem'),'-out',str(root/'cert.pem')]
        subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        cls.server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);cls.server_tls.load_cert_chain(root/'cert.pem',root/'key.pem')
        cls.client_tls=ssl.create_default_context(cafile=str(root/'cert.pem'))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def transport(self,*,trust=True):
        with patch.object(urllib.request,'getproxies',return_value={}):t=http.StudyHttpTransport()
        if trust:
            for manager in (t.pool,t.control_pool):manager.connection_pool_kw['ssl_context']=self.client_tls
        self.addCleanup(t.close);return t

    def test_old_connect_timeout_reproduces_but_new_upload_preserves_exact_bytes(self):
        body=b'x'*6_413_836
        with receiver(pause=.2)as(url,records):
            old=urllib3.PoolManager(retries=False)
            try:
                with self.assertRaises(urllib3.exceptions.HTTPError):
                    old.request('POST',url,body=body,retries=False,
                                timeout=urllib3.Timeout(connect=.04,read=.5,total=.5))
            finally:old.clear()
            t=self.transport();fields={}
            with patch.object(http,'CONNECT_TIMEOUT',.04),patch.object(upload,'UPLOAD_IDLE_TIMEOUT',.7):
                with t.open(request(url,body),.5,update=lambda**x:fields.update(x))as response:value=json.load(response)
            self.assertEqual(value,{'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)})
            self.assertEqual(fields['requestBodyBytesSent'],len(body));self.assertTrue(fields['requestUploadComplete'])
            self.assertIsNone(records[-1]['transferEncoding']);self.assertEqual(len(records),2)

    def test_progressing_upload_may_exceed_header_budget_without_losing_header_wait(self):
        body=b'y'*(12*1024*1024);fields={}
        with receiver(pause=.1,delay_per_read=.001)as(url,records):
            t=self.transport()
            with patch.object(http,'CONNECT_TIMEOUT',.05),patch.object(upload,'UPLOAD_IDLE_TIMEOUT',1):
                with t.open(request(url,body),.5,update=lambda**x:fields.update(x))as response:value=json.load(response)
            self.assertEqual(value['sha256'],hashlib.sha256(body).hexdigest());self.assertEqual(len(records),1)
            self.assertGreater(fields['requestUploadSeconds'],.5)
            self.assertIn('lastNetworkProgressAtMs',fields)

    def test_blocked_upload_exits_without_retry_or_claiming_zero_transmission(self):
        body=b'z'*(12*1024*1024);fields={}
        with receiver(pause=.8)as(url,records):
            t=self.transport();start=time.monotonic()
            with patch.object(http,'CONNECT_TIMEOUT',.05),patch.object(upload,'UPLOAD_IDLE_TIMEOUT',.08):
                with self.assertRaises(urllib.error.URLError)as failure:t.open(request(url,body),1,update=lambda**x:fields.update(x))
            self.assertLess(time.monotonic()-start,.6);self.assertEqual(len(records),1)
            self.assertFalse(getattr(failure.exception,'request_not_sent',False))
            self.assertEqual(fields['transportFailurePhase'],'uploading_request');self.assertTrue(fields['requestWriteAttempted'])
            previous={k:fields[k]for k in ('transportFailurePhase','requestBodyBytesSent','requestWireBytesSent')}
            with t.open(urllib.request.Request(url+'/receipt',method='GET'),1,update=lambda**x:fields.update(x))as response:
                self.assertEqual(json.load(response),{'receipt':'original'})
            self.assertEqual({k:fields[k]for k in previous},previous,'receipt GET overwrote original upload evidence')

    def test_finished_upload_then_silent_headers_is_still_bounded(self):
        fields={}
        with receiver(header_pause=.4)as(url,records):
            t=self.transport();start=time.monotonic()
            with self.assertRaises(urllib.error.URLError):t.open(request(url,b'{}'),.05,update=lambda**x:fields.update(x))
            self.assertLess(time.monotonic()-start,.3);self.assertEqual(len(records),1)
            self.assertTrue(fields['requestUploadComplete']);self.assertEqual(fields['transportFailurePhase'],'waiting_headers')

    def test_cancel_before_first_write_is_proven_unsent(self):
        stop=threading.Event()
        def update(**fields):
            if fields.get('networkPhase')=='uploading_request':stop.set()
        def check():
            if stop.is_set():raise InterruptedError('cancelled')
        with receiver()as(url,records):
            t=self.transport()
            with self.assertRaises(http.RequestNotSentError)as failure:t.open(request(url,b'{}'),1,update=update,check=check)
            self.assertTrue(failure.exception.cancelled);self.assertEqual(records,[])

    def test_cancel_during_partial_upload_is_not_marked_unsent_or_reposted(self):
        stop=threading.Event();fields={}
        def update(**values):
            fields.update(values)
            if values.get('requestBodyBytesSent',0)>16384:stop.set()
        def check():
            if stop.is_set():raise InterruptedError('cancelled')
        with receiver(pause=.25)as(url,records):
            t=self.transport()
            with self.assertRaises(InterruptedError)as failure:t.open(request(url,b'x'*(12*1024*1024)),1,update=update,check=check)
            self.assertFalse(getattr(failure.exception,'request_not_sent',False));self.assertEqual(len(records),1)
            self.assertTrue(fields['requestWriteAttempted'])

    def test_tls_upload_longer_than_actual_six_second_connect_limit_is_allowed(self):
        body=b't'*6_413_836;fields={}
        with receiver(pause=6.25,tls=self.server_tls)as(url,records):
            t=self.transport()
            with t.open(request(url,body),10,update=lambda**x:fields.update(x))as response:value=json.load(response)
            self.assertEqual(value['sha256'],hashlib.sha256(body).hexdigest());self.assertEqual(len(records),1)
            self.assertGreater(fields['requestUploadSeconds'],6)

    def test_tls_reused_connection_resets_upload_policy_and_does_not_leak_timeout(self):
        with receiver(pause=.15,tls=self.server_tls)as(url,records):
            t=self.transport()
            for body in (b'{}',b'r'*6_413_836,b'{}'):
                fields={}
                with patch.object(http,'CONNECT_TIMEOUT',.04):
                    with t.open(request(url,body),1,update=lambda**x:fields.update(x))as response:value=json.load(response)
                self.assertEqual(value['bytes'],len(body));self.assertEqual(fields['requestBodyBytesSent'],len(body))
            self.assertEqual(len(records),3);self.assertEqual(len({r['port']for r in records}),1)

    def test_tls_certificate_validation_is_not_disabled(self):
        with receiver(tls=self.server_tls)as(url,records):
            t=self.transport(trust=False)
            with self.assertRaises(urllib.error.URLError):t.open(request(url,b'{}'),1)
            self.assertEqual(records,[])

    def test_https_connect_proxy_keeps_tls_and_does_not_count_tunnel_bytes_as_post(self):
        with receiver(tls=self.server_tls)as(url,records),tunnel_proxy()as(proxy,tunnels):
            with patch.object(urllib.request,'getproxies',return_value={'https':proxy}),patch.object(urllib.request,'proxy_bypass',return_value=False):
                t=http.StudyHttpTransport()
            self.addCleanup(t.close);t.pool.connection_pool_kw['ssl_context']=self.client_tls
            fields={};body=b'proxied exact source'
            with t.open(request(url,body),2,update=lambda**x:fields.update(x))as response:value=json.load(response)
            self.assertEqual(value['sha256'],hashlib.sha256(body).hexdigest());self.assertEqual(len(tunnels),1)
            self.assertEqual(fields['requestBodyBytesSent'],len(body));self.assertEqual(len(records),1)
            self.assertTrue(t.pool.connection_pool_kw['ssl_context'].check_hostname)


if __name__=='__main__':unittest.main()
