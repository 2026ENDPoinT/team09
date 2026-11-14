"""Single-POST study streaming with bounded silence and read-only recovery.

No model, source or output-limit truncation. Native status and usage remain
authoritative. A complete final JSON frame may survive a cancelled malformed
suffix; commentary is never promoted to a final answer. No generation retries.
"""
from __future__ import annotations
import json
from contextlib import ExitStack
from dataclasses import dataclass
import re
import socket
import time
import urllib.error
import urllib.request

HEADERS_TIMEOUT = 45
IDLE_TIMEOUT = 30
# Legacy non-observed parsing thresholds. Durable requests use the independent
# ten-second status observer after acknowledgement, with no SSE idle deadline.
STARTUP_TIMEOUT = 20
DURABLE_IDLE_TIMEOUT = 20
# Without an acknowledged ID there is nothing to retrieve. Preserve the prior
# receipt allowance rather than turning the status-check threshold into failure.
RECEIPT_TIMEOUT = 90
RECOVERY_TIMEOUT = 6
RECOVERY_READS = 3
RECOVERY_WINDOW = 20
MAX_EVENT_BYTES = 16 * 1024 * 1024
TERMINAL = {'response.completed', 'response.incomplete', 'response.failed', 'response.cancelled'}
RESPONSE_ID = re.compile(r'resp_[A-Za-z0-9_-]{1,240}\Z')


@dataclass
class GuardedStudyResponse:
    native: dict
    value: dict | None
    reason: str


def _stop_original(request,response_id,guard,reason,open_url,update,check,clock,sleep,*,allow_value=True):
    # Only background requests can be explicitly cancelled at the server. No
    # new generation is created. Native cancellation and usage stay authoritative.
    auth=request.get_header('Authorization');headers={'Authorization':auth} if isinstance(auth,str)else {}
    headers['Content-Type']='application/json'
    headers['Cache-Control']='no-cache'
    update(networkPhase='stopping_cancelled'if reason=='user_cancelled'else'stopping_output_anomaly',clientStopReason=reason,
           completeJsonChars=getattr(guard,'end',0),discardedTailChars=getattr(guard,'tail_chars',0))
    cancel=urllib.request.Request('https://api.openai.com/v1/responses/'+response_id+'/cancel',
        data=b'{}',headers=headers,method='POST')
    with open_url(cancel,timeout=RECOVERY_TIMEOUT)as stream:native=json.load(stream)
    if not isinstance(native,dict)or native.get('id')!=response_id:raise StudyConnectionError('cancel_id_mismatch')
    deadline=clock()+RECOVERY_WINDOW
    for attempt in range(RECOVERY_READS):
        check();remaining=deadline-clock()
        if remaining<=0:break
        get=urllib.request.Request('https://api.openai.com/v1/responses/'+response_id,headers=headers,method='GET')
        try:
            with open_url(get,timeout=min(RECOVERY_TIMEOUT,remaining))as stream:value=json.load(stream)
            if isinstance(value,dict)and value.get('id')==response_id:
                terminal=('completed','incomplete','cancelled','failed')
                # A replica can briefly return an older in-progress state after
                # cancellation. Never regress a confirmed terminal response.
                if value.get('status')in terminal or native.get('status')not in terminal:
                    native=value
                if native.get('status')in terminal and isinstance(native.get('usage'),dict):break
        except (OSError,ValueError):pass
        if attempt+1<RECOVERY_READS:sleep(min(1,max(0,deadline-clock())))
    if native.get('status')not in ('completed','incomplete','cancelled','failed'):
        raise StudyConnectionError('cancel_unconfirmed')
    update(networkPhase='output_anomaly_stopped',clientStopReason=reason)
    return GuardedStudyResponse(native,guard.value if allow_value and guard is not None and guard.finished else None,reason)


class StudyConnectionError(TimeoutError):
    def __init__(self, phase, reason=None):
        super().__init__('Study response connection stopped during '+phase)
        self.phase, self.reason = phase, reason


def _stop_foreground(request, response_id, stream, reason, open_url, update):
    """Close the generation connection; a stored terminal receipt is optional.

    A foreground ID can return 404 until it has been stored. Never translate
    that response into a free request or manufacture a completed response from
    deltas. The outer bounded recovery can retrieve a late terminal receipt.
    """
    update(networkPhase='stopping_foreground', clientStopReason=reason)
    try:stream.fp.raw._sock.shutdown(socket.SHUT_RDWR)
    except (AttributeError,OSError):pass
    auth=request.get_header('Authorization')
    get=urllib.request.Request('https://api.openai.com/v1/responses/'+response_id,
        headers={**({'Authorization':auth} if isinstance(auth,str) else {}),
                 'Cache-Control':'no-cache'},method='GET')
    try:
        with open_url(get,timeout=RECOVERY_TIMEOUT)as reply:native=json.load(reply)
        if isinstance(native,dict) and native.get('id')==response_id and native.get('status')in ('completed','incomplete','cancelled','failed'):
            update(networkPhase='recovered_original',recoveredOriginalResponse=True,
                   foregroundStoppedReceiptRecovered=True)
            return native
    except (OSError,ValueError) as error:
        fields={'foregroundReceiptReadError':type(error).__name__}
        if isinstance(error,urllib.error.HTTPError):fields['foregroundReceiptHttpStatus']=error.code
        update(**fields)
    raise StudyConnectionError('foreground_output_anomaly',reason)


def _read_timeout(stream, seconds):
    # urllib's HTTPResponse owns this socket on both Windows and macOS. The
    # fallback still has the timeout used by urlopen (also covered by tests).
    try:
        stream.fp.raw._sock.settimeout(None if seconds is None else max(.001, seconds))
    except AttributeError:
        pass


def _events(stream, check, clock, *, startup_timeout=None, idle_timeout=IDLE_TIMEOUT, receipt_pending=lambda:False,
            live_status=False):
    data, size = [], 0
    last_progress = clock();started=last_progress;lifecycle=set();output_started=False
    while True:
        check()
        starting=startup_timeout is not None and not output_started
        remaining = ((RECEIPT_TIMEOUT if receipt_pending() else startup_timeout)-(clock()-started) if starting
                     else idle_timeout-(clock()-last_progress))
        # The independent status observer owns acknowledged silence. A socket
        # timeout would poison the buffered SSE and defeat concurrent retrieval.
        if live_status and not receipt_pending():remaining=None
        if remaining is not None and remaining <= 0:
            raise StudyConnectionError('waiting_first_output' if starting else 'stream_idle')
        _read_timeout(stream, remaining)
        try:line = stream.readline(MAX_EVENT_BYTES+1)
        except OSError as error:
            raise StudyConnectionError('waiting_first_output' if starting else 'stream_idle',error) from error
        if not line:
            raise StudyConnectionError('stream_eof')
        if isinstance(line, bytes):line=line.decode('utf-8')
        size += len(line.encode('utf-8'))
        if size > MAX_EVENT_BYTES:
            raise StudyConnectionError('oversized_event')
        line=line.rstrip('\r\n')
        if line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
        elif not line and data:
            raw='\n'.join(data);data=[];size=0
            if raw == '[DONE]':raise StudyConnectionError('missing_terminal')
            event=json.loads(raw)
            if not isinstance(event, dict):raise StudyConnectionError('invalid_event')
            # Comments/keepalives cannot keep a stalled generation alive forever.
            kind=event.get('type','')
            if not isinstance(kind,str):raise StudyConnectionError('invalid_event_type')
            new_state=kind in ('response.created','response.in_progress') and kind not in lifecycle
            if kind.endswith('.delta') and bool(event.get('delta')):output_started=True
            if new_state or kind.endswith('.delta') and bool(event.get('delta')) or kind in TERMINAL:
                last_progress=clock()
            lifecycle.add(kind)
            yield event
        elif not line:
            size=0


def request_once(request, *, open_url, update, check=lambda: None,
                 clock=time.monotonic, sleep=time.sleep, on_headers=lambda h: None, on_delta=None,
                 reject_commentary=False,on_snapshot=lambda value:None,resume_stream=False,
                 recovery_window=RECOVERY_WINDOW,recovery_reads=RECOVERY_READS,
                 recovery_timeout=RECOVERY_TIMEOUT,tail_status_after=None,attempt_watch=None,
                 foreground=False,reject_title_repetition=False):
    """One POST; observe durable silence alongside SSE, recover broken sockets by GET."""
    started=clock();response_id=None;events=0;guard=None;guard_item=None;phases={};commentary_padding={};preview_item=None
    text_counts={'commentary':0,'final_answer':0}
    last_final=None;max_final_gap=0.;final_chunks=0
    from pdf_study_tail import ControlSequenceLoop
    control_loop=ControlSequenceLoop()
    final_parts=[];snapshot_at=started
    def snapshot():
        if not final_parts:return
        try:on_snapshot({'id':response_id,'content':''.join(final_parts),'terminalReceived':False,
            'sourceChannel':'final_answer','completeJsonCandidate':guard.value if guard is not None and guard.finished else None})
        except Exception:pass  # A disk/UI observer must not fail a paid completion.
    body={}
    try:
        body=json.loads(request.data or b'{}')
        schema=body.get('text',{}).get('format',{}).get('schema')
        if (body.get('background') is True or foreground) and isinstance(schema,dict):
            from pdf_json_boundary import JsonBoundary
            guard=JsonBoundary(schema)
    except (ValueError,TypeError):pass
    repetition_meters={};repetition_reason=None
    if reject_title_repetition:
        from pdf_study_repetition import ShortFieldRepetition, source_spellings
        repetition_sources=source_spellings(body)
    def repeated_field(meter):
        nonlocal repetition_reason
        repetition_reason='repeated_short_field'
        match=meter.match
        update(streamOutputAnomaly=repetition_reason,
               repeatedField=match['field'],repeatedFieldPeriod=match['period'],
               repeatedFieldChars=match['stringChars'],
               repeatedFieldOffsetChars=match['offsetChars'])
    def receipt(value):
        # Preserve native terminal status and usage even when this attempt is
        # rejected. A late stored receipt must not bypass the same output guard.
        if reject_title_repetition and repetition_reason is None:
            output=value.get('output')
            for item in output if isinstance(output,list) else ():
                if not isinstance(item,dict) or item.get('phase')=='commentary':continue
                meter=ShortFieldRepetition(repetition_sources)
                content=item.get('content')
                for part in content if isinstance(content,list) else ():
                    if (isinstance(part,dict) and part.get('type')=='output_text'
                            and isinstance(part.get('text'),str) and meter.feed(part['text'])):
                        repeated_field(meter);break
                if repetition_reason:break
        if repetition_reason:
            return GuardedStudyResponse(value,None,repetition_reason)
        return value
    if foreground:
        if body.get('background') is True:
            raise ValueError('Foreground delivery requires background=false')
        # A closed foreground request cannot resume its generation stream.
        # Keep receipt recovery bounded even if the caller has durable limits.
        resume_stream=False
        recovery_window=min(recovery_window,RECOVERY_WINDOW)
        recovery_reads=min(recovery_reads,RECOVERY_READS)
        recovery_timeout=min(recovery_timeout,RECOVERY_TIMEOUT)
        if tail_status_after is None:tail_status_after=60.0
    observe_status=resume_stream or foreground
    sequence=None;headers_received=False;watch=None
    try:
        update(networkPhase='waiting_headers', networkMode='responses_sse_v1')
        with open_url(request,timeout=HEADERS_TIMEOUT) as stream, ExitStack() as observers:
            headers_at=clock();headers=getattr(stream,'headers',{})
            headers_received=True
            on_headers(headers)
            details={'networkPhase':'receiving_events',
                     'connectionAndResponseHeadersSeconds':round(headers_at-started,4)}
            trace=headers.get('x-request-id')
            if isinstance(trace,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}',trace):details['serverRequestId']=trace
            update(**details)
            if 'text/event-stream' not in headers.get('content-type',headers.get('Content-Type','')).lower():
                # Some test transports/compatible servers return a complete JSON
                # body. It still goes through the same strict terminal adapter.
                value=json.load(stream)
                if response_id is not None and value.get('id')!=response_id:
                    raise StudyConnectionError('recovery_id_mismatch')
                if observe_status and value.get('status')not in ('completed','incomplete','cancelled','failed'):
                    raise StudyConnectionError('stream_pending')
                update(networkPhase='response_received',responseBodySeconds=round(clock()-headers_at,4))
                return receipt(value)
            watch=None
            if observe_status:
                from pdf_study_idle_watch import IdleStatusWatch, watched_events
                watch=observers.enter_context(IdleStatusWatch(request,stream,open_url=open_url,
                    update=update,check=check,clock=clock,timeout=min(RECOVERY_TIMEOUT,recovery_timeout),
                    started=started,tail_after=tail_status_after,foreground=foreground))
                if callable(getattr(attempt_watch,'bind_status_probe',None)):
                    attempt_watch.bind_status_probe(watch.recover_now)
            incoming=_events(stream,watch.check_stream if watch is not None else check,clock,
                    startup_timeout=STARTUP_TIMEOUT if observe_status else None,
                    idle_timeout=DURABLE_IDLE_TIMEOUT if observe_status else IDLE_TIMEOUT,
                    receipt_pending=lambda:response_id is None,live_status=watch is not None)
            if watch is not None:incoming=watched_events(incoming,watch)
            def stop_output(reason, *, allow_value=True):
                if foreground:
                    return receipt(_stop_foreground(request,response_id,stream,reason,open_url,update))
                return _stop_original(request,response_id,guard,reason,
                    open_url,update,check,clock,sleep,allow_value=allow_value)
            for event in incoming:
                events+=1;kind=event.get('type');native=event.get('response')
                if isinstance(native,dict):
                    ident=native.get('id')
                    if isinstance(ident,str) and RESPONSE_ID.fullmatch(ident):
                        if response_id is not None and response_id!=ident:
                            raise StudyConnectionError('response_id_changed')
                        response_id=ident
                        if watch is not None:watch.acknowledge(response_id)
                # Transport keepalives use a connection counter, not a
                # stored response cursor. They must neither skip a later
                # response.created event nor change a reconnect position.
                current_sequence=None if kind=='keepalive' else event.get('sequence_number')
                if type(current_sequence)is int and current_sequence>=0:
                    if sequence is not None and current_sequence<=sequence:continue
                    sequence=current_sequence
                fields={'streamEvents':events,'lastNetworkProgressAtMs':int(time.time()*1000)}
                # Protocol diagnostics only; never persist raw source/text events.
                if isinstance(kind,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',kind):
                    fields['lastEventType']=kind
                    if events==1:fields['firstEventType']=kind
                fields['responseIdReceived']=bool(response_id)
                if sequence is not None:fields['lastSequenceNumber']=sequence
                if response_id:fields['responseId']=response_id
                if events==1:fields['firstEventSeconds']=round(clock()-started,4)
                update(**fields)
                item=event.get('item')
                if kind=='response.output_item.added' and isinstance(item,dict):
                    phases[item.get('id')]=item.get('phase')
                    if reject_commentary and item.get('phase')=='commentary'and response_id:
                        # Teaching has no need for an intermediate commentary
                        # channel. Stop before it can echo the schema or consume
                        # thousands of non-learner tokens. A confirmed terminal
                        # receipt is required before any single alternate route.
                        return stop_output('unexpected_commentary')
                if kind=='response.output_text.delta'and isinstance(event.get('delta'),str)and event['delta']:
                    phase='commentary'if phases.get(event.get('item_id'))=='commentary'else'final_answer'
                    if phase=='final_answer':
                        now=clock()
                        if last_final is not None:max_final_gap=max(max_final_gap,now-last_final)
                        last_final=now;final_chunks+=1
                        looping=control_loop.feed(event['delta']) if tail_status_after is not None else False
                        if reject_title_repetition:
                            item_id=event.get('item_id')
                            if item_id not in repetition_meters:
                                repetition_meters[item_id]=ShortFieldRepetition(repetition_sources)
                            meter=repetition_meters[item_id]
                            if meter.feed(event['delta']):repeated_field(meter)
                        if watch is not None:watch.progress(len(event['delta']),output_loop=looping)
                        final_parts.append(event['delta'])
                        if clock()-snapshot_at>=1:
                            snapshot();snapshot_at=clock()
                    first=text_counts[phase]==0;text_counts[phase]+=len(event['delta'])
                    fields={('commentaryTextChars'if phase=='commentary'else'finalTextChars'):text_counts[phase]}
                    if phase=='final_answer':
                        fields.update(lastFinalTextSeconds=round(last_final-started,4),
                                      maxFinalTextGapSeconds=round(max_final_gap,4),finalTextChunks=final_chunks)
                        if control_loop.detected:fields['streamOutputAnomaly']='repeated_terminal_controls'
                    if first:fields['firstCommentaryTextSeconds'if phase=='commentary'else'firstFinalTextSeconds']=round(clock()-started,4)
                    update(**fields)
                    if repetition_reason:
                        if response_id:return stop_output(repetition_reason,allow_value=False)
                        raise StudyConnectionError('stream_output_anomaly',repetition_reason)
                    if foreground and control_loop.detected and response_id:
                        return stop_output('repeated_terminal_controls',allow_value=False)
                if guard is not None:
                    if kind=='response.output_text.delta' and isinstance(event.get('delta'),str):
                        item_id=event.get('item_id')
                        if phases.get(item_id)=='commentary':
                            # Structured-output models can also degenerate before
                            # the final channel. Detect only uninterrupted padding
                            # outside quoted strings; never accept commentary as a
                            # completed learner answer or clip a long explanation.
                            quoted,escaped,spaces=commentary_padding.get(item_id,(False,False,0))
                            for char in event['delta']:
                                if quoted:
                                    if escaped:escaped=False
                                    elif char=='\\':escaped=True
                                    elif char=='"':quoted=False
                                elif char=='"':quoted=True;spaces=0
                                elif char.isspace():
                                    spaces+=1
                                    if spaces>256 and response_id:
                                        return stop_output('padding_in_commentary',allow_value=False)
                                else:spaces=0
                            commentary_padding[item_id]=(quoted,escaped,spaces)
                        elif phases.get(item_id)in (None,'final_answer'):
                            if guard_item is None:guard_item=item_id
                            if guard_item!=item_id:guard=None
                            else:
                                reason=guard.feed(event['delta'])
                                if reason and response_id:
                                    return stop_output(reason)
                if on_delta is not None and kind=='response.output_text.delta' and isinstance(event.get('delta'),str):
                    item_id=event.get('item_id')
                    if phases.get(item_id)in (None,'final_answer'):
                        if preview_item is None:preview_item=item_id
                        if preview_item==item_id:
                            # A display failure must never restart/retrieve a paid
                            # generation. Cancellation still propagates normally.
                            try:on_delta(event['delta'])
                            except InterruptedError:raise
                            except Exception:pass
                if kind in TERMINAL and isinstance(native,dict):
                    update(networkPhase='response_received',responseBodySeconds=round(clock()-headers_at,4))
                    return receipt(native)
                if kind=='error':raise StudyConnectionError('stream_error')
    except InterruptedError:
        if response_id and body.get('background')is True:
            try:
                # A user cancellation must stop the acknowledged server job,
                # not merely abandon its socket while paid generation runs.
                return _stop_original(request,response_id,guard,'user_cancelled',open_url,
                    update,lambda:None,clock,sleep,allow_value=False)
            except Exception as error:
                fields={'cancelFailureType':type(error).__name__}
                if isinstance(error,urllib.error.HTTPError):fields['cancelHttpStatus']=error.code
                update(**fields)  # Keep reason types, never credentials/response bodies.
        raise
    except (OSError, ValueError) as failure:
        if isinstance(failure,urllib.error.HTTPError):
            raise  # An explicit creation error must retain its original meaning.
        phase=failure.phase if isinstance(failure,StudyConnectionError) else ('stream_idle' if headers_received else 'waiting_headers')
        if phase=='waiting_first_output' and not response_id:phase='waiting_response_id'
        update(networkPhase=phase,connectionFailureType=type(failure).__name__)
        if not response_id:
            raise StudyConnectionError(phase,failure) from failure
        # Lost stream after acknowledgement: retrieve the original generation;
        # never repeat its paid POST or invent output/usage from partial deltas.
        try:
            recovery_started=clock();deadline=recovery_started+recovery_window
            update(recoveryStartedSeconds=round(recovery_started-started,4),streamReconnects=0)
            for attempt in range(recovery_reads):
                check()
                if watch is not None and watch.native is not None:
                    return receipt(watch.native)
                remaining=deadline-clock()
                if remaining<=0:break
                auth=request.get_header('Authorization')
                get=urllib.request.Request('https://api.openai.com/v1/responses/'+response_id,
                    headers={**({'Authorization':auth} if isinstance(auth,str) else {}),'Cache-Control':'no-cache'},method='GET')
                update(networkPhase='recovering_original',recoveryReads=attempt+1)
                try:
                    with open_url(get,timeout=min(recovery_timeout,remaining)) as stream:
                        value=json.load(stream)
                    if not isinstance(value,dict) or value.get('id')!=response_id:
                        raise StudyConnectionError('recovery_id_mismatch')
                    status=value.get('status')
                    if status in ('queued','in_progress','completed','incomplete','failed','cancelled'):
                        update(recoveryStatus=status,recoveryStatusSeconds=round(clock()-started,4))
                    if status in ('completed','incomplete','failed','cancelled'):
                        update(networkPhase='recovered_original',recoveredOriginalResponse=True,
                               recoverySeconds=round(clock()-recovery_started,4))
                        return receipt(value)
                except InterruptedError:
                    raise
                except urllib.error.HTTPError as error:
                    if foreground:update(foregroundReceiptHttpStatus=error.code)
                    if error.code in (401,403):raise
                except (OSError,ValueError):
                    pass
                remaining=deadline-clock()
                if attempt+1<recovery_reads and remaining>0:
                    left=min(15,1.7**attempt,remaining)
                    while left>0:
                        if watch is not None and watch.native is not None:
                            return receipt(watch.native)
                        check();delay=min(.25,left);sleep(delay);left-=delay
        except InterruptedError:
            if body.get('background') is True:
                try:
                    return _stop_original(request,response_id,guard,'user_cancelled',open_url,
                        update,lambda:None,clock,sleep,allow_value=False)
                except Exception as error:
                    fields={'cancelFailureType':type(error).__name__}
                    if isinstance(error,urllib.error.HTTPError):fields['cancelHttpStatus']=error.code
                    update(**fields)
            raise
        if watch is not None and watch.native is not None:
            return receipt(watch.native)
        raise StudyConnectionError('recovery_pending',failure) from failure
    finally:snapshot()
