"""Offline K1.2.0 delivery: stored receipts, real socket closure, no cancel POST."""
import io
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import pdf_study_connection as net
import pdf_study_idle_watch as idle
from test_pdf_study_connection import sse, created
from test_pdf_study_idle_watch import LiveStream
from test_pdf_responses_transport import native


def request():
    schema={'type':'object','properties':{'ok':{'type':'boolean'}},
            'required':['ok'],'additionalProperties':False}
    return urllib.request.Request('https://api.openai.com/v1/responses',
        data=json.dumps({'stream':True,'background':False,'store':True,
                         'text':{'format':{'schema':schema}}}).encode(),
        headers={'Authorization':'Bearer fixture'},method='POST')


def missing(req):
    return urllib.error.HTTPError(req.full_url,404,'Not stored yet',{},None)


class ForegroundTransportTests(unittest.TestCase):
    def test_broken_stream_recovers_late_stored_receipt_without_resume_or_new_post(self):
        calls=[];updates=[]
        def open_url(req,timeout):
            calls.append((req,timeout))
            if req.method=='POST':return sse([created()])
            if len(calls)==2:raise missing(req)
            return io.StringIO(json.dumps(native()))
        result=net.request_once(request(),open_url=open_url,update=lambda **x:updates.append(x),
            foreground=True,resume_stream=True,recovery_reads=100,recovery_window=600,
            recovery_timeout=120,sleep=lambda _:None)
        self.assertEqual(result,native())
        self.assertEqual([r.method for r,_ in calls],['POST','GET','GET'])
        self.assertTrue(all('?'not in r.full_url and not r.full_url.endswith('/cancel')for r,_ in calls))
        self.assertTrue(all(t<=6 for _,t in calls[1:]))
        self.assertTrue(any(x.get('foregroundReceiptHttpStatus')==404 for x in updates))

    def test_unavailable_receipt_is_bounded_and_cannot_be_free_or_complete(self):
        calls=[]
        def open_url(req,timeout):
            calls.append(req)
            if req.method=='POST':return sse([created()])
            raise missing(req)
        with self.assertRaises(net.StudyConnectionError)as failure:
            net.request_once(request(),open_url=open_url,update=lambda **x:None,foreground=True,
                recovery_reads=100,recovery_window=600,recovery_timeout=120,sleep=lambda _:None)
        self.assertEqual(failure.exception.phase,'recovery_pending')
        self.assertEqual([r.method for r in calls],['POST','GET','GET','GET'])

    def test_foreground_rejects_background_wire_configuration(self):
        req=request();body=json.loads(req.data);body['background']=True;req.data=json.dumps(body).encode()
        with self.assertRaises(ValueError):
            net.request_once(req,open_url=lambda *a,**k:self.fail('must not send'),
                update=lambda **x:None,foreground=True)

    def test_json_guard_closes_connection_and_uses_only_native_receipt(self):
        stream=LiveStream();calls=[];updates=[]
        self.addCleanup(stream.writer.close);self.addCleanup(stream.__exit__)
        stream.send({'type':'response.output_text.delta','item_id':'msg',
                     'delta':'{"ok":true}'+(' '*300)})
        value=native();value['output'][1]['content'][0]['text']='{"ok":false}'
        def open_url(req,timeout):
            calls.append(req)
            if req.method=='POST':return stream
            # The generation socket must be shut down before receipt retrieval.
            self.assertEqual(stream.writer.recv(1),b'')
            return io.StringIO(json.dumps(value))
        got=net.request_once(request(),open_url=open_url,update=lambda **x:updates.append(x),foreground=True)
        self.assertEqual(got,value)
        self.assertEqual([r.method for r in calls],['POST','GET'])
        self.assertTrue(any(x.get('clientStopReason')=='padding_after_complete'for x in updates))
        self.assertTrue(stream.closed)

    def test_guard_never_accepts_complete_delta_without_terminal_receipt(self):
        calls=[]
        def open_url(req,timeout):
            calls.append(req)
            if req.method=='POST':return sse([created(),{'type':'response.output_text.delta','item_id':'msg',
                'delta':'{"ok":true}'+(' '*300)}])
            raise missing(req)
        with self.assertRaises(net.StudyConnectionError):
            net.request_once(request(),open_url=open_url,update=lambda **x:None,foreground=True,sleep=lambda _:None)
        self.assertEqual(sum(r.method=='POST'for r in calls),1)
        self.assertFalse(any(r.full_url.endswith('/cancel')for r in calls))

    def test_commentary_guard_remains_active_without_cancel_api(self):
        calls=[];updates=[]
        def open_url(req,timeout):
            calls.append(req)
            if req.method=='POST':return sse([created(),{'type':'response.output_item.added',
                'item':{'id':'comment','phase':'commentary'}}])
            return io.StringIO(json.dumps(native()))
        self.assertEqual(net.request_once(request(),open_url=open_url,
            update=lambda **x:updates.append(x),foreground=True,reject_commentary=True),native())
        self.assertEqual([r.method for r in calls],['POST','GET'])
        self.assertTrue(any(x.get('clientStopReason')=='unexpected_commentary'for x in updates))

    def test_control_loop_guard_does_not_depend_on_background_setting(self):
        calls=[];updates=[]
        def open_url(req,timeout):
            calls.append(req)
            if req.method=='POST':return sse([created(),{'type':'response.output_text.delta','item_id':'msg',
                'delta':'{"ok":"'+('\\u001b[0m'*18)}])
            return io.StringIO(json.dumps(native()))
        self.assertEqual(net.request_once(request(),open_url=open_url,
            update=lambda **x:updates.append(x),foreground=True),native())
        self.assertEqual([r.method for r in calls],['POST','GET'])
        self.assertTrue(any(x.get('clientStopReason')=='repeated_terminal_controls'for x in updates))


class ForegroundLiveSocketTests(unittest.TestCase):
    def setUp(self):
        self.stream=LiveStream();self.calls=[];self.updates=[];self.cancel=False
        self.addCleanup(self.stream.writer.close);self.addCleanup(self.stream.__exit__)
        interval=patch.object(idle,'INTERVAL',.1);interval.start();self.addCleanup(interval.stop)

    def run_request(self,handler,**kwargs):
        def opener(req,timeout):
            self.calls.append(req)
            if req.method=='POST':return self.stream
            return handler(req)
        def check():
            if self.cancel:raise InterruptedError()
        return net.request_once(request(),open_url=opener,update=lambda **x:self.updates.append(x),
            check=check,foreground=True,**kwargs)

    def test_live_404_keeps_output_stream_open_and_later_recovers_completion(self):
        def get(req):
            self.assertFalse(self.stream.closed)
            if len(self.calls)==2:raise missing(req)
            return io.StringIO(json.dumps(native()))
        self.assertEqual(self.run_request(get),native())
        self.assertEqual([r.method for r in self.calls],['POST','GET','GET'])
        self.assertTrue(any(x.get('idleStatusReceiptPending')for x in self.updates))

    def test_user_cancel_wakes_blocked_socket_without_cancel_post(self):
        def get(req):
            self.cancel=True
            raise missing(req)
        with self.assertRaises(InterruptedError):self.run_request(get)
        self.assertTrue(self.stream.closed)
        self.assertEqual([r.method for r in self.calls],['POST','GET'])
        self.assertFalse(any(r.full_url.endswith('/cancel')for r in self.calls))

    def test_periodic_status_recovers_done_receipt_even_when_text_keeps_trickling(self):
        stopped=threading.Event()
        def send():
            while not stopped.wait(.02):
                try:self.stream.send({'type':'response.output_text.delta','delta':' '})
                except OSError:return
        thread=threading.Thread(target=send,daemon=True);thread.start()
        try:
            self.assertEqual(self.run_request(lambda req:io.StringIO(json.dumps(native())),
                tail_status_after=.15),native())
            self.assertEqual([r.method for r in self.calls],['POST','GET'])
        finally:
            stopped.set();thread.join(1)


if __name__=='__main__':unittest.main()
