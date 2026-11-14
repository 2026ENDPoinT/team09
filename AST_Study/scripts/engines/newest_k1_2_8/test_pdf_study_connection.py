"""No paid network: real SSE parsing, silence, read-only recovery, billing guards."""
import copy
import io
import json
import socket
import unittest
import urllib.request
from unittest.mock import patch
import pdf_study_connection as net
from test_pdf_responses_transport import native
from test_pdf_responses_provider import ResponsesProviderTests


def sse(events):
    stream=io.BytesIO(b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events))
    stream.headers={'Content-Type':'text/event-stream','x-request-id':'req_fixture'}
    return stream


def post():
    return urllib.request.Request('https://api.openai.com/v1/responses',data=b'{"stream":true}',
        headers={'Authorization':'Bearer test-only'},method='POST')


def created():return {'type':'response.created','response':{'id':'resp_fixture','status':'in_progress'}}


class StudyConnectionTests(unittest.TestCase):
    def test_keepalive_counter_does_not_skip_response_before_status_first_recovery(self):
        calls=[];updates=[]
        def opener(req,timeout):
            calls.append(req)
            if req.method=='POST':return sse([
                {'type':'keepalive','sequence_number':50},
                {**created(),'sequence_number':0},
                {'type':'response.output_text.delta','delta':'x','sequence_number':1},
                {'type':'keepalive','sequence_number':60}])
            return io.StringIO(json.dumps(native()))
        request=urllib.request.Request('https://api.openai.com/v1/responses',
            data=b'{"stream":true,"background":true}',method='POST')
        self.assertEqual(net.request_once(request,open_url=opener,update=lambda **x:updates.append(x),
                                         resume_stream=True),native())
        self.assertEqual([r.method for r in calls],['POST','GET'])
        self.assertTrue(calls[1].full_url.endswith('/resp_fixture'))
        self.assertNotIn('?',calls[1].full_url)
        self.assertTrue(any(u.get('lastSequenceNumber')==0 and u.get('responseIdReceived') for u in updates))

    def test_durable_startup_waits_for_delayed_id_without_second_post(self):
        now=[0.0];calls=[];timeouts=[];updates=[]
        stream=sse([{'type':'response.queued','sequence_number':0},created(),
                    {'type':'response.completed','response':native()}])
        class Delayed(io.BytesIO):
            def readline(self,*args):
                line=super().readline(*args)
                if b'response.created' in line:
                    self_test.assertGreater(timeouts[-1],35)
                    now[0]+=35
                return line
        self_test=self
        delayed=Delayed(stream.getvalue());delayed.headers=stream.headers
        def opener(req,timeout):
            calls.append(req.method)
            return delayed if req.method=='POST' else io.StringIO(json.dumps(native()))
        with patch.object(net,'_read_timeout',side_effect=lambda _,seconds:timeouts.append(seconds)):
            result=net.request_once(post(),open_url=opener,update=lambda **x:updates.append(x),
                                    clock=lambda:now[0],resume_stream=True)
        self.assertEqual(result,native());self.assertEqual(calls,['POST'])
        self.assertTrue(any(x.get('firstEventType')=='response.queued' for x in updates))
        self.assertTrue(any(x.get('responseIdReceived') is True for x in updates))

    def test_durable_startup_heartbeats_have_absolute_bound_and_correct_phase(self):
        now=[0];calls=[]
        class Heartbeats(io.BytesIO):
            def readline(self,*a):now[0]+=10;return b': keepalive\n\n'
        stream=Heartbeats();stream.headers={'Content-Type':'text/event-stream'}
        def opener(req,timeout):calls.append(req.method);return stream
        with self.assertRaises(net.StudyConnectionError) as failure:
            net.request_once(post(),open_url=opener,update=lambda **x:None,
                clock=lambda:now[0],resume_stream=True)
        self.assertEqual(failure.exception.phase,'waiting_response_id')
        self.assertEqual(calls,['POST']);self.assertLessEqual(now[0],net.RECEIPT_TIMEOUT+10)

    def test_acknowledged_durable_stream_has_no_destructive_socket_idle_timeout(self):
        stream=sse([created(),{'type':'response.output_text.delta','delta':'x'},
                    {'type':'response.completed','response':native()}]);timeouts=[]
        with patch.object(net,'_read_timeout',side_effect=lambda _,seconds:timeouts.append(seconds)):
            net.request_once(post(),open_url=lambda *a,**k:stream,update=lambda **x:None,resume_stream=True)
        self.assertLessEqual(timeouts[0],net.RECEIPT_TIMEOUT)
        self.assertIsNone(timeouts[-1])

    def test_terminal_native_object_remains_exact_not_reconstructed_from_delta(self):
        value=native();updates=[];requests=[]
        def opener(req,timeout):requests.append(req);return sse([created(),{'type':'response.output_text.delta','delta':'wrong partial JSON'}, {'type':'response.completed','response':value}])
        got=net.request_once(post(),open_url=opener,update=lambda **x:updates.append(x))
        self.assertEqual(got,value);self.assertEqual(len(requests),1)
        self.assertTrue(any(x.get('responseId')=='resp_fixture'for x in updates))
        self.assertTrue(any(x.get('serverRequestId')=='req_fixture'for x in updates))

    def test_lost_stream_fetches_same_response_without_second_post(self):
        requests=[];value=native();updates=[]
        def opener(req,timeout):
            requests.append(req)
            return sse([created()]) if req.method=='POST' else io.StringIO(json.dumps(value))
        self.assertEqual(net.request_once(post(),open_url=opener,update=lambda **x:updates.append(x)),value)
        self.assertEqual([x.method for x in requests],['POST','GET'])
        self.assertTrue(requests[1].full_url.endswith('/resp_fixture'))
        self.assertEqual(requests[1].get_header('Authorization'),'Bearer test-only')
        self.assertTrue(any(x.get('recoveredOriginalResponse')for x in updates))

    def test_missing_acknowledgement_never_reposts_or_guesses_id(self):
        calls=[]
        def opener(req,timeout):calls.append((req.method,timeout));raise TimeoutError('silent header')
        with self.assertRaises(net.StudyConnectionError) as error:net.request_once(post(),open_url=opener,update=lambda **x:None)
        self.assertEqual(calls,[('POST',45)]);self.assertEqual(error.exception.phase,'waiting_headers')

    def test_in_progress_retrieval_bounded_and_never_bills_new_generation(self):
        requests=[]
        def opener(req,timeout):
            requests.append(req)
            return sse([created()]) if req.method=='POST' else io.StringIO(json.dumps({'id':'resp_fixture','status':'in_progress'}))
        with self.assertRaises(net.StudyConnectionError):net.request_once(post(),open_url=opener,update=lambda **x:None,sleep=lambda _:None)
        self.assertEqual([x.method for x in requests],['POST']+['GET']*3)

    def test_keepalive_comments_do_not_extend_progress_deadline(self):
        now=[0]
        class Heartbeats(io.BytesIO):
            def readline(self,*a):now[0]+=11;return b': keepalive\n\n'
        stream=Heartbeats();stream.headers={'Content-Type':'text/event-stream'}
        with self.assertRaises(net.StudyConnectionError):net.request_once(post(),open_url=lambda *a,**k:stream,update=lambda **x:None,clock=lambda:now[0])
        self.assertLessEqual(now[0],44)

    def test_slow_active_generation_is_not_cut_off_at_header_timeout(self):
        now=[0];stream=sse([created()]+[{'type':'response.output_text.delta','delta':'x'}]*12+[{'type':'response.completed','response':native()}])
        class Active(io.BytesIO):
            def readline(self,*a):now[0]+=4;return super().readline(*a)
        active=Active(stream.getvalue());active.headers=stream.headers
        self.assertEqual(net.request_once(post(),open_url=lambda *a,**k:active,update=lambda **x:None,clock=lambda:now[0]),native())
        self.assertGreater(now[0],net.HEADERS_TIMEOUT)

    def test_incomplete_terminal_preserves_original_usage(self):
        value=native();value['status']='incomplete';value['incomplete_details']={'reason':'max_output_tokens'}
        stream=sse([created(),{'type':'response.incomplete','response':value}])
        self.assertEqual(net.request_once(post(),open_url=lambda *a,**k:stream,update=lambda **x:None),value)

    def test_wrong_retrieved_response_cannot_become_success(self):
        def opener(req,timeout):return sse([created()])if req.method=='POST' else io.StringIO(json.dumps({**native(),'id':'resp_wrong'}))
        with self.assertRaises(net.StudyConnectionError):net.request_once(post(),open_url=opener,update=lambda **x:None,sleep=lambda _:None)

    def test_silent_background_polls_pending_until_completed_without_reposting(self):
        calls=[];updates=[];now=[0.0];statuses=iter(['queued','in_progress','completed'])
        def opener(req,timeout):
            calls.append(req)
            if req.method=='POST':return sse([{**created(),'sequence_number':0}])
            status=next(statuses)
            return io.StringIO(json.dumps({**native(),'status':status}))
        request=post();request.data=b'{"stream":true,"background":true}'
        def sleep(seconds):now[0]+=seconds
        result=net.request_once(request,open_url=opener,update=lambda **x:updates.append(x),
            clock=lambda:now[0],sleep=sleep,resume_stream=True)
        self.assertEqual(result,native())
        self.assertEqual([r.method for r in calls],['POST','GET','GET','GET'])
        self.assertTrue(all('?' not in r.full_url for r in calls))
        self.assertEqual([u['recoveryStatus'] for u in updates if 'recoveryStatus' in u],
                         ['queued','in_progress','completed'])

    def test_cancellation_during_status_poll_stops_original(self):
        calls=[];polling=[False]
        def opener(req,timeout):
            calls.append(req)
            if req.method=='POST' and not req.full_url.endswith('/cancel'):return sse([created()])
            if req.full_url.endswith('/cancel'):return io.StringIO(json.dumps({**native(),'status':'cancelled'}))
            if not polling[0]:
                polling[0]=True
                return io.StringIO(json.dumps({'id':'resp_fixture','status':'in_progress'}))
            return io.StringIO(json.dumps({**native(),'status':'cancelled'}))
        def check():
            if polling[0]:raise InterruptedError()
        request=post();request.data=b'{"stream":true,"background":true}'
        got=net.request_once(request,open_url=opener,update=lambda **x:None,check=check,
                             resume_stream=True,sleep=lambda _:None)
        self.assertIsInstance(got,net.GuardedStudyResponse)
        self.assertEqual(got.reason,'user_cancelled')
        self.assertIsNone(got.value)
        self.assertEqual(sum(r.method=='POST' and not r.full_url.endswith('/cancel') for r in calls),1)
        self.assertEqual(sum(r.full_url.endswith('/cancel') for r in calls),1)

    def test_background_active_output_can_run_longer_than_twenty_seconds(self):
        now=[0.0]
        original=sse([created()]+[{'type':'response.output_text.delta','delta':'x'}]*15+
                     [{'type':'response.completed','response':native()}])
        class Active(io.BytesIO):
            def readline(self,*args):now[0]+=2;return super().readline(*args)
        active=Active(original.getvalue());active.headers=original.headers
        result=net.request_once(post(),open_url=lambda *a,**k:active,update=lambda **x:None,
                                clock=lambda:now[0],resume_stream=True)
        self.assertEqual(result,native());self.assertGreater(now[0],60)

class StudyProviderConnectionTests(ResponsesProviderTests):
    def test_proven_unsent_setup_failure_releases_hold_without_blocking_the_input(self):
        import pdf_ai as ai
        from pdf_study_http import RequestNotSentError
        p=self.provider(mode='responses')
        self.opener.side_effect=RequestNotSentError('connection_not_established')
        with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
        entry=p.ledger['requests'][0]
        self.assertEqual(entry['state'],'not_sent');self.assertNotIn('sentAtMs',entry)
        self.assertEqual(entry['estimatedUsd'],0);self.assertEqual(p.spent,0)
        p.billing.settle.assert_called_once_with(entry['requestId'],0)
        self.opener.side_effect=lambda *a,**k:sse([created(),{'type':'response.completed','response':native()}])
        self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})

    def test_unsent_wrapper_preserves_dns_cause_without_logging_error_text(self):
        import pdf_ai as ai
        import urllib3
        from pdf_study_http import RequestNotSentError
        p=self.provider(mode='responses')
        cause=urllib3.exceptions.NewConnectionError(None,'private-host fixture-secret')
        cause.__cause__=socket.gaierror(socket.EAI_AGAIN,'private-host fixture-secret')
        error=RequestNotSentError('connection_not_established');error.__cause__=cause
        self.opener.side_effect=error
        with self.assertRaises(ai.AiResponseError)as failure:p.complete(self.payload,**self.options)
        entry=p.ledger['requests'][0]
        self.assertIn('AI 서버에 연결하지 못해',str(failure.exception))
        self.assertNotIn('파일 전송이 지연',str(failure.exception))
        self.assertEqual(entry['transportCauseType'],'NewConnectionError')
        self.assertEqual(entry['transportCauseChain'],[
            {'type':'NewConnectionError'},{'type':'gaierror','errno':socket.EAI_AGAIN}])
        self.assertNotIn('private-host',json.dumps(entry));self.assertNotIn('fixture-secret',json.dumps(entry))
        self.assertEqual(entry['state'],'not_sent');self.assertEqual(entry['estimatedUsd'],0)
        self.assertNotIn('sentAtMs',entry);self.assertEqual(self.opener.call_count,1)
        p.billing.settle.assert_called_once_with(entry['requestId'],0)

    def test_unsent_reasons_distinguish_connection_queue_and_incomplete_upload(self):
        import pdf_ai as ai
        from pathlib import Path
        from pdf_study_http import RequestNotSentError
        for reason,expected in [('connection_not_established','AI 서버에 연결하지 못해'),
                                ('local_connection_queue','AI 서버 연결을 기다리다'),
                                ('incomplete_request_body','요청 본문을 끝까지 전송하지 못해')]:
            with self.subTest(reason=reason):
                self.folder=Path(self.temp.name)/reason
                p=self.provider(mode='responses');self.opener.reset_mock()
                self.opener.side_effect=RequestNotSentError(reason)
                with self.assertRaises(ai.AiResponseError)as failure:p.complete(self.payload,**self.options)
                self.assertIn(expected,str(failure.exception))
                self.assertIn('이 구간의 API 비용은 발생하지 않았어요',str(failure.exception))
                self.assertIn('완료한 내용은 보관했어요',str(failure.exception))
                entry=p.ledger['requests'][0]
                self.assertEqual(entry['localStopReason'],reason);self.assertEqual(entry['state'],'not_sent')
                self.assertEqual(entry['estimatedUsd'],0);self.assertEqual(self.opener.call_count,1)
                p.billing.settle.assert_called_once_with(entry['requestId'],0)

    def test_connection_reset_is_not_reported_as_a_startup_timeout(self):
        import pdf_ai as ai
        import urllib.error
        import urllib3
        p=self.provider(mode='responses')
        self.opener.side_effect=urllib.error.URLError(urllib3.exceptions.ProtocolError('Connection reset',ConnectionResetError(54,'reset')))
        with self.assertRaises(ai.AiResponseError)as failure:p.complete(self.payload,**self.options)
        self.assertIn('응답 연결이 끊겼어요',str(failure.exception))
        self.assertNotIn('대기를 종료',str(failure.exception))
        self.assertNotIn('API 비용은 발생하지 않았어요',str(failure.exception))
        self.assertEqual(self.opener.call_count,1)
        self.assertEqual(p.ledger['requests'][0]['state'],'failed_or_uncertain')
        p.billing.settle.assert_called_once_with(p.ledger['requests'][0]['requestId'],None)

    def test_stream_receipt_and_usage_are_durable_and_cache_is_reused(self):
        p=self.provider(mode='responses');value=native()
        self.opener.side_effect=lambda *a,**k:sse([created(),{'type':'response.completed','response':value}])
        self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})
        entry=self.assert_settled_native(p,value)
        self.assertTrue(json.loads(self.opener.call_args.args[0].data)['stream'])
        self.assertEqual(entry['responseId'],'resp_fixture')
        self.assertEqual(json.loads(self.paths(entry)[0].with_suffix('.receipt.json').read_text())['responseId'],'resp_fixture')
        other=self.provider(mode='responses');self.assertEqual(other.complete(self.payload,**self.options),{'ok':True});self.assertEqual(self.opener.call_count,1)

    def test_timeout_preserves_unknown_money_without_abandoning_a_distinct_unit(self):
        import pdf_ai as ai
        p=self.provider(mode='responses');self.opener.side_effect=TimeoutError('silent response')
        with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
        self.assertEqual(p.ledger['requests'][0]['state'],'failed_or_uncertain')
        self.assertEqual(p.ledger['requests'][0]['timeoutSeconds'],45)
        p.billing.settle.assert_called_once_with(p.ledger['requests'][0]['requestId'],None)
        self.opener.side_effect=lambda *a,**k:sse([created(),{'type':'response.completed','response':native()}])
        self.assertEqual(p.complete({**self.payload,'other':'healthy'},**self.options),{'ok':True})
        self.assertEqual(self.opener.call_count,2);self.assertEqual(len(p.ledger['requests']),2)
        with self.assertRaises(ai.AiResponseError):p.complete(self.payload,**self.options)
        self.assertEqual(self.opener.call_count,2)  # The ambiguous original is never repaid.

    def test_an_older_sibling_circuit_cannot_abandon_new_unsent_work(self):
        import pdf_ai as ai
        from contextlib import contextmanager
        p=self.provider(mode='responses')
        @contextmanager
        def gate(**kwargs):
            p._study_connection_failed.set()
            yield None
        self.opener.side_effect=lambda *a,**k:sse([created(),{'type':'response.completed','response':native()}])
        with patch.object(ai,'api_slot',gate):self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})
        self.opener.assert_called_once()
        entry=p.ledger['requests'][0]
        self.assertEqual(entry['state'],'settled');self.assertGreater(entry['estimatedUsd'],0)
        p.billing.settle.assert_called_once_with(entry['requestId'],entry['estimatedUsd'])

    def test_isolated_failure_does_not_stop_other_healthy_work(self):
        import pdf_ai as ai
        p=self.provider(mode='responses')
        self.opener.side_effect=lambda *a,**k:sse([created(),{'type':'response.completed','response':native()}])
        p.complete(self.payload,**self.options)
        self.opener.side_effect=TimeoutError('only this connection lost')
        with self.assertRaises(ai.AiResponseError):p.complete({**self.payload,'unit':2},**self.options)
        self.assertFalse(p._study_connection_failed.is_set())
        self.opener.side_effect=lambda *a,**k:sse([created(),{'type':'response.completed','response':native()}])
        self.assertEqual(p.complete({**self.payload,'unit':3},**self.options),{'ok':True})
        self.assertEqual(self.opener.call_count,3)

    def test_retrieval_charges_original_usage_exactly_once(self):
        p=self.provider(mode='responses');calls=[]
        def opener(req,timeout):
            calls.append(req.method)
            return sse([created()]) if req.method=='POST'else io.StringIO(json.dumps(native()))
        self.opener.side_effect=opener
        self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})
        self.assert_settled_native(p,native());self.assertEqual(calls,['POST','GET'])
        self.assertEqual(len(p.ledger['requests']),1)


if __name__=='__main__':unittest.main()
