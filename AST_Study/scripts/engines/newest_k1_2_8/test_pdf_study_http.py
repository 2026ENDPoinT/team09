"""Loopback HTTP/SSE fault injection; no external data or paid calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io,json,threading,time,unittest,urllib.request
from unittest.mock import patch
import pdf_study_connection as net
from test_pdf_responses_transport import native


@contextmanager
def server(mode):
    calls=[];guard=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            with guard:calls.append('POST')
            try:
                if mode=='silent_headers':time.sleep(.2)
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                self.event({'type':'response.created','response':{'id':'resp_fixture','status':'in_progress'}})
                if mode=='lost':return
                if mode=='silent_body':time.sleep(.2)
                else:
                    for i in range(6):
                        time.sleep(.012);self.event({'type':'response.output_text.delta','delta':'x'})
                self.event({'type':'response.completed','response':native()})
            except (BrokenPipeError,ConnectionResetError):pass
        def event(self,value):self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode());self.wfile.flush()
        def do_GET(self):
            with guard:calls.append('GET')
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(native()).encode())
    class Server(ThreadingHTTPServer):request_queue_size=64;daemon_threads=True
    http=Server(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    root='http://127.0.0.1:'+str(http.server_port)
    def opener(req,timeout):
        local=urllib.request.Request(root+urllib.parse.urlsplit(req.full_url).path,data=req.data,headers=dict(req.header_items()),method=req.method)
        return urllib.request.urlopen(local,timeout=timeout)
    try:yield opener,calls
    finally:http.shutdown();http.server_close();thread.join()


def request():return urllib.request.Request('https://api.openai.com/v1/responses',data=b'{}',method='POST')


class StudyHttpTests(unittest.TestCase):
    def test_real_socket_idle_recovers_original_before_long_body_wait(self):
        with server('silent_body') as (opener,calls),patch.object(net,'IDLE_TIMEOUT',.04):
            start=time.monotonic();result=net.request_once(request(),open_url=opener,update=lambda **x:None)
            self.assertEqual(result,native());self.assertLess(time.monotonic()-start,.18);self.assertEqual(calls,['POST','GET'])

    def test_silent_headers_cut_off_without_a_second_generation(self):
        with server('silent_headers') as (opener,calls),patch.object(net,'HEADERS_TIMEOUT',.04):
            start=time.monotonic()
            with self.assertRaises(net.StudyConnectionError):net.request_once(request(),open_url=opener,update=lambda **x:None)
            self.assertLess(time.monotonic()-start,.18);self.assertEqual(calls,['POST'])

    def test_broken_stream_retrieves_original(self):
        with server('lost') as (opener,calls):
            self.assertEqual(net.request_once(request(),open_url=opener,update=lambda **x:None),native());self.assertEqual(calls,['POST','GET'])

    def test_sixteen_active_streams_keep_complete_outputs_and_parallelism(self):
        with server('active') as (opener,calls),patch.object(net,'HEADERS_TIMEOUT',2),patch.object(net,'IDLE_TIMEOUT',1):
            with ThreadPoolExecutor(max_workers=16) as pool:
                results=list(pool.map(lambda _:net.request_once(request(),open_url=opener,update=lambda **x:None),range(16)))
            self.assertEqual(results,[native()]*16);self.assertEqual(calls,['POST']*16)

if __name__=='__main__':unittest.main()
