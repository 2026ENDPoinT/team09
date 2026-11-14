"""Local sockets only: early HTTP responses, immediate SSE, 16 parallel waits."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import errno,json,threading,unittest,urllib.error,urllib.request
from unittest.mock import patch
import urllib3
from pdf_study_http import StudyHttpTransport,RequestNotSentError
from pdf_study_upload import ProgressHTTPConnection,ProgressHTTPPool
from pdf_study_chat import collect


@contextmanager
def server(mode):
    calls=[];lock=threading.Lock();all_arrived=threading.Event();preview=threading.Event();release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=self.rfile.read(int(self.headers['Content-Length']))
            with lock:
                calls.append(body)
                if len(calls)==16:all_arrived.set()
            if mode=='lost':self.close_connection=True;return
            if mode in ('parallel','control')and not all_arrived.wait(3):return
            if mode=='control'and not release.wait(3):return
            self.send_response(200);self.send_header('Content-Type','text/event-stream'if mode=='sse'else'application/json');self.end_headers()
            try:
                if mode=='sse':
                    self.event({'id':'chatcmpl_fixture','choices':[{'index':0,'delta':{'content':'{"ok":true}'},'finish_reason':None}]})
                    if not release.wait(3):return
                    self.event({'id':'chatcmpl_fixture','choices':[{'index':0,'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':3,'completion_tokens':4}})
                    self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
                else:self.wfile.write(b'{"ok":true}')
            except (BrokenPipeError,ConnectionResetError):pass
        def event(self,value):self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode());self.wfile.flush()
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(b'{"receipt":"original"}');self.wfile.flush()
    class Server(ThreadingHTTPServer):daemon_threads=True;request_queue_size=64
    http=Server(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(http.server_port),calls,preview,release
    finally:release.set();http.shutdown();http.server_close();thread.join()


class PooledHttpTests(unittest.TestCase):
    def request(self,url):return urllib.request.Request(url,data=b'{"source":"exact"}',method='POST')
    def test_sixteen_responses_wait_concurrently_without_serializing_generation(self):
        with server('parallel')as(url,calls,_,__):
            t=StudyHttpTransport()
            try:
                def call(_):
                    with t.open(self.request(url),5)as stream:return json.load(stream)
                with ThreadPoolExecutor(max_workers=16)as pool:self.assertEqual(list(pool.map(call,range(16))),[{'ok':True}]*16)
                self.assertEqual(calls,[b'{"source":"exact"}']*16)
            finally:t.close()
    def test_short_first_sse_delta_arrives_before_the_rest_of_the_response(self):
        with server('sse')as(url,calls,preview,release):
            t=StudyHttpTransport()
            def call():
                with t.open(self.request(url),3)as stream:return collect(stream,on_delta=lambda _:preview.set())
            try:
                with ThreadPoolExecutor(max_workers=1)as pool:
                    result=pool.submit(call)
                    try:self.assertTrue(preview.wait(1),'First delta was buffered until completion');self.assertFalse(result.done())
                    finally:release.set()
                    self.assertEqual(result.result()['usage']['completion_tokens'],4)
                self.assertEqual(len(calls),1)
            finally:t.close()
    def test_lost_connection_is_not_automatically_posted_again(self):
        with server('lost')as(url,calls,_,__):
            t=StudyHttpTransport()
            try:
                with self.assertRaises(urllib.error.URLError):t.open(self.request(url),3)
                self.assertEqual(len(calls),1)
            finally:t.close()
    def test_control_reads_are_not_starved_by_sixteen_active_generation_connections(self):
        with server('control')as(url,calls,_,release):
            t=StudyHttpTransport()
            def call(_):
                with t.open(self.request(url),5)as stream:return json.load(stream)
            try:
                with ThreadPoolExecutor(max_workers=16)as pool:
                    futures=[pool.submit(call,n)for n in range(16)]
                    import time
                    deadline=time.monotonic()+2
                    while len(calls)<16 and time.monotonic()<deadline:time.sleep(.005)
                    self.assertEqual(len(calls),16)
                    try:
                        with t.open(urllib.request.Request(url+'/receipt',method='GET'),1)as stream:
                            self.assertEqual(json.load(stream),{'receipt':'original'})
                    finally:release.set()
                    self.assertEqual([f.result()for f in futures],[{'ok':True}]*16)
            finally:t.close()
    def test_broken_pipe_after_early_server_response_keeps_that_response(self):
        class EarlyResponse(ProgressHTTPConnection):
            def request(self,*args,**kwargs):
                super().request(*args,**kwargs)
                raise BrokenPipeError(errno.EPIPE,'Server has sent an early response')
        with server('normal')as(url,calls,_,__),patch.object(ProgressHTTPPool,'ConnectionCls',EarlyResponse):
            t=StudyHttpTransport()
            try:
                with t.open(self.request(url),3)as stream:self.assertEqual(json.load(stream),{'ok':True})
                self.assertEqual(len(calls),1)
            finally:t.close()
    def test_connection_failure_before_transmission_reconnects_without_an_extra_post(self):
        with server('normal')as(url,calls,_,__):
            t=StudyHttpTransport();updates=[];original=t.pool.request;attempts=[]
            def connect(*args,**kwargs):
                attempts.append(1)
                if len(attempts)==1:raise urllib3.exceptions.NewConnectionError(None,'Not connected')
                return original(*args,**kwargs)
            try:
                with patch.object(t.pool,'request',side_effect=connect):
                    with t.open(self.request(url),3,update=lambda **x:updates.append(x))as stream:
                        self.assertEqual(json.load(stream),{'ok':True})
                self.assertEqual(len(attempts),2);self.assertEqual(len(calls),1)
                self.assertTrue(any(x.get('unsentConnectionReconnects')==1 for x in updates))
            finally:t.close()
    def test_exhausted_unsent_connections_are_proven_unsent_not_unknown_charges(self):
        t=StudyHttpTransport()
        try:
            with patch.object(t.pool,'request',side_effect=urllib3.exceptions.ConnectTimeoutError('Not connected'))as open_request:
                with self.assertRaises(RequestNotSentError)as failure:t.open(self.request('https://api.openai.com/v1/responses'),3)
                self.assertEqual(open_request.call_count,2);self.assertEqual(failure.exception.reason_code,'connection_not_established')
        finally:t.close()
    def test_proxy_read_timeout_before_any_request_write_can_reconnect(self):
        with server('normal')as(url,calls,_,__):
            t=StudyHttpTransport();updates=[];original=t.pool.request;attempts=[]
            def connect(*args,**kwargs):
                attempts.append(1)
                if len(attempts)==1:raise urllib3.exceptions.ReadTimeoutError(None,url,'Proxy tunnel did not respond')
                return original(*args,**kwargs)
            try:
                with patch.object(t.pool,'request',side_effect=connect):
                    with t.open(self.request(url),3,update=lambda **x:updates.append(x))as stream:
                        self.assertEqual(json.load(stream),{'ok':True})
                self.assertEqual(len(attempts),2);self.assertEqual(len(calls),1)
                self.assertTrue(any(x.get('reconnectSafety')=='connection_not_established'for x in updates))
            finally:t.close()
    def test_exhausted_proxy_setup_timeouts_are_proven_unsent(self):
        t=StudyHttpTransport()
        try:
            failure=urllib3.exceptions.ReadTimeoutError(None,'https://api.openai.com/v1/responses','Proxy tunnel did not respond')
            with patch.object(t.pool,'request',side_effect=failure)as open_request:
                with self.assertRaises(RequestNotSentError)as caught:t.open(self.request('https://api.openai.com/v1/responses'),3)
                self.assertEqual(open_request.call_count,2)
                self.assertEqual(caught.exception.reason_code,'connection_not_established')
        finally:t.close()
    def test_header_read_timeout_after_writing_never_repeats_the_post(self):
        import pdf_study_upload as upload
        t=StudyHttpTransport();attempts=[]
        def sent(*args,**kwargs):
            attempts.append(1);policy=upload._POLICY.value
            policy.phase='waiting_headers';policy.write_attempted=True
            policy.body_sent=policy.body_size;policy.body_attempted_upper=policy.body_size
            raise urllib3.exceptions.ReadTimeoutError(None,args[1],'Response headers did not arrive')
        try:
            with patch.object(t.pool,'request',side_effect=sent):
                with self.assertRaises(urllib.error.URLError)as caught:t.open(self.request('https://api.openai.com/v1/responses'),3)
                self.assertFalse(getattr(caught.exception,'request_not_sent',False));self.assertEqual(len(attempts),1)
        finally:t.close()
    def test_cancellation_between_unsent_connection_attempts_stops_before_post(self):
        t=StudyHttpTransport();checks=[]
        def check():
            checks.append(1)
            if len(checks)==2:raise InterruptedError('Cancelled')
        try:
            with patch.object(t.pool,'request',side_effect=urllib3.exceptions.NewConnectionError(None,'Not connected'))as open_request:
                with self.assertRaises(RequestNotSentError)as failure:t.open(self.request('https://api.openai.com/v1/responses'),3,check=check)
                self.assertEqual(open_request.call_count,1);self.assertTrue(failure.exception.cancelled)
        finally:t.close()
    def test_recovery_connection_failure_never_marks_the_original_post_unsent(self):
        for url in ('https://api.openai.com/v1/responses/resp_fixture',
                    'https://api.openai.com/v1/responses/resp_fixture?stream=true&starting_after=3'):
            with self.subTest(url=url):
                t=StudyHttpTransport()
                try:
                    pool=t.pool if 'stream=true'in url else t.control_pool
                    with patch.object(pool,'request',side_effect=urllib3.exceptions.ConnectTimeoutError('Not connected')):
                        with self.assertRaises(urllib.error.URLError)as failure:t.open(urllib.request.Request(url,method='GET'),3)
                        self.assertFalse(getattr(failure.exception,'request_not_sent',False))
                finally:t.close()
    def test_server_cancellation_remains_available_after_desktop_cancel_flag(self):
        with server('normal')as(url,calls,_,__):
            t=StudyHttpTransport()
            def cancelled():raise InterruptedError('Desktop closed')
            try:
                with t.open(self.request(url+'/cancel'),3,check=cancelled)as stream:
                    self.assertEqual(json.load(stream),{'ok':True})
                self.assertEqual(len(calls),1)
            finally:t.close()

if __name__=='__main__':unittest.main()
