"""Opt-in continuous STT lanes. Both consume the SAME 16 kHz PCM blocks.

No retries: a failed stream stops its lane and preserves the local recording.
Connections are opened only after the first post-gate audio block arrives.
"""
import json
import queue
import re
import threading
import time
import uuid

from asr_compare import api_key


def _safe_diagnostic(value, limit=80):
    """Show provider identifiers, never free-form text that may echo credentials."""
    value = str(value)
    return value[:limit] if re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', value) else 'invalid'


def _soniox_server_error(event):
    parts = ['Soniox 서버 오류', 'error_code=' + _safe_diagnostic(event['error_code'])]
    for field in ('error_type', 'request_id'):
        if event.get(field) is not None:
            parts.append(field + '=' + _safe_diagnostic(event[field]))
    return ' · '.join(parts)


class SonioxServerError(RuntimeError):
    def __init__(self, event, progress):
        self.code = event.get('error_code')
        super().__init__(_soniox_server_error(event) + ' · ' + progress)


def _retryable_soniox_error(error, websocket):
    if isinstance(error, SonioxServerError):
        return type(error.code) is int and (error.code == 429 or error.code >= 500)
    if isinstance(error, websocket.WebSocketBadStatusException):
        code = getattr(error, 'status_code', None)
        return type(code) is int and (code == 429 or code >= 500)
    if isinstance(error, (OSError, websocket.WebSocketException)):
        return True
    return type(error) is RuntimeError and str(error).startswith((
        'Soniox 음성 전송 실패', 'Soniox 최종 응답 시간 초과',
        'Soniox 연결 끊김', 'Soniox 연결 종료', 'Soniox 연결 조기 종료',
        'Soniox 입력 적체 재연결'))


def _soniox_close_code(payload):
    return int.from_bytes(payload[:2], 'big') if len(payload) >= 2 else '없음'


def daglo_messages():
    """Build the small public Daglo protobuf schema without generated files."""
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    file = descriptor_pb2.FileDescriptorProto(name='daglo_speech.proto', package='dagloapis.speech.v1', syntax='proto3')

    def message(name):
        return file.message_type.add(name=name)

    def field(msg, name, number, typ, type_name='', oneof=None):
        item = msg.field.add(name=name, number=number, label=1, type=typ)
        if type_name:
            item.type_name = type_name
        if oneof is not None:
            item.oneof_index = oneof

    config = message('RecognitionConfig')
    field(config, 'language_code', 1, 9)
    field(config, 'interim_results', 2, 8)
    request = message('StreamingRecognizeRequest')
    request.oneof_decl.add(name='streaming_request')
    field(request, 'config', 1, 11, '.dagloapis.speech.v1.RecognitionConfig', 0)
    field(request, 'audio_content', 2, 12, oneof=0)
    result = message('StreamingRecognitionResult')
    field(result, 'transcript', 1, 9)
    field(result, 'is_final', 2, 8)
    field(result, 'language_code', 3, 9)
    response = message('StreamingRecognizeResponse')
    field(response, 'result', 1, 11, '.dagloapis.speech.v1.StreamingRecognitionResult')
    field(response, 'total_duration', 2, 2)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return tuple(message_factory.GetMessageClass(pool.FindMessageTypeByName('dagloapis.speech.v1.' + name))
                 for name in ('RecognitionConfig', 'StreamingRecognizeRequest', 'StreamingRecognizeResponse'))


class StreamWorker:
    def __init__(self, name, args, events):
        self.name, self.args, self.events = name, args, events
        self.queue = queue.Queue(maxsize=100)  # 10 s of 100 ms capture blocks.
        self.ready = threading.Event()
        self.failed = threading.Event()
        self.finished = threading.Event()
        self.restart_requested = threading.Event()
        self.offered_bytes = 0
        self.sent_bytes = 0
        self.send_started_at = None
        self.last_response_at = None
        self.confirmed_ms = 0
        self.gap_start_ms = None
        self.had_gap = False
        self.reconnect_attempt = 0
        self.last_backpressure_diag_at = 0
        self.thread = threading.Thread(target=self.run, name='stream-' + name, daemon=True)
        self.thread.start()

    def offer(self, pcm):
        if self.failed.is_set() or self.finished.is_set():
            return
        limit = getattr(self.args, 'max_stream_seconds', 120)
        if self.offered_bytes + len(pcm) > limit * 16000 * 2:
            self.finished.set()
            self.events.emit('ERROR', self.name, text=f'실시간 전송 {limit}초 제한 도달 · 이 스트림 종료, 녹음은 계속')
            return
        try:
            self.queue.put_nowait((self.offered_bytes // 32, pcm))
            self.offered_bytes += len(pcm)
        except queue.Full:
            if self.name == 'soniox':
                self.restart_requested.set()
                if self.gap_start_ms is None:
                    self.gap_start_ms = self.confirmed_ms
                now = time.monotonic()
                if (getattr(self.args, 'structured', False)
                        and now - self.last_backpressure_diag_at >= 5):
                    self.last_backpressure_diag_at = now
                    send_started_at = self.send_started_at
                    last_response_at = self.last_response_at
                    self.events.emit('DIAGNOSTIC', self.name, stage='soniox.backpressure',
                                     queuedBlocks=self.queue.qsize(),
                                     offeredMs=self.offered_bytes // 32,
                                     sentMs=self.sent_bytes // 32,
                                     sendInFlightMs=(int((now - send_started_at) * 1000)
                                                     if send_started_at is not None else 0),
                                     responseAgeMs=(int((now - last_response_at) * 1000)
                                                    if last_response_at is not None else -1))
                self.queue.get_nowait()
                self.queue.put_nowait((self.offered_bytes // 32, pcm))
                self.offered_bytes += len(pcm)
            else:
                self.failed.set()
                self.events.emit('ERROR', self.name, text='실시간 전송 10초 적체 · 이 모델 중단, 녹음 유지')

    def blocks(self):
        while not self.failed.is_set():
            try:
                yield self.queue.get(timeout=.1)
            except queue.Empty:
                if self.finished.is_set():
                    return

    def finish_gap(self, end_ms):
        start = self.gap_start_ms
        if start is not None and end_ms > start:
            self.events.emit('GAP', self.name, startMs=start, endMs=end_ms,
                             reason='soniox_connection_unconfirmed')
            self.had_gap = True
        self.gap_start_ms = None

    def report(self, final, provisional):
        self.events.emit('STREAM', self.name, text=final + provisional,
                         final=final, provisional=provisional, accuracy_verified=False)

    def run(self):
        try:
            if not self.args.allow_upload:
                raise RuntimeError('클라우드 전송 동의 없음')
            variable = 'SONIOX_API_KEY' if self.name == 'soniox' else 'DAGLO_API_TOKEN'
            key = api_key(variable)
            if not key:
                raise RuntimeError('.env의 ' + variable + '가 없음')
            if self.name == 'soniox':
                import websocket
            else:
                import grpc
                daglo_messages()
                if self.args.language == 'es':
                    raise RuntimeError('다글로 실시간 STT는 스페인어 미지원')
            self.events.emit('STATUS', self.name, text='키/라이브러리 준비 · 녹음 시작 대기 (서버 권한은 연결 시 확인)')
            self.ready.set()
            if self.name == 'soniox':
                import websocket
                while not self.failed.is_set():
                    blocks = self.blocks()
                    first = next(blocks, None)
                    if first is None:
                        break
                    if self.reconnect_attempt:
                        while True:
                            try:
                                first = self.queue.get_nowait()
                            except queue.Empty:
                                break
                    self.events.emit('STATUS', self.name, text='Soniox 서버 연결 중 · 이때부터 사용량 발생 가능')
                    try:
                        self.restart_requested.clear()
                        self.soniox(key, first, blocks)
                        if not self.finished.is_set() or not self.queue.empty():
                            raise RuntimeError('Soniox 연결 조기 종료')
                        break
                    except Exception as error:
                        if not _retryable_soniox_error(error, websocket):
                            raise
                        self.diagnostic('soniox.reconnect', error)
                        if self.gap_start_ms is None:
                            self.gap_start_ms = self.confirmed_ms
                        self.reconnect_attempt += 1
                        if self.finished.is_set() and self.queue.empty():
                            break
                        delay = min(2 ** min(self.reconnect_attempt - 1, 3), 8)
                        self.events.emit('RECONNECTING', self.name, attempt=self.reconnect_attempt,
                                         delaySeconds=delay, text='Soniox 연결 복구 중 · 녹음 유지')
                        self.finished.wait(delay)
                self.finish_gap(self.offered_bytes // 32)
            else:
                blocks = self.blocks()
                first = next(blocks, None)
                if first is None:
                    self.events.emit('DONE', self.name, text='음성 전송 없음')
                    return
                self.events.emit('STATUS', self.name, text='서버 연결 중 · 이때부터 사용량 발생 가능')
                self.daglo(key, first[1], (pcm for _, pcm in blocks))
            if not self.failed.is_set():
                self.events.emit('DONE', self.name, text='실시간 처리 종료 · 누락 구간 재인식 필요'
                                 if self.had_gap else '실시간 처리 종료 · 녹음과 대조 필요')
        except Exception as error:
            self.failed.set()
            if self.name == 'soniox':
                if self.gap_start_ms is None:
                    self.gap_start_ms = self.confirmed_ms
                self.finish_gap(self.offered_bytes // 32)
            self.diagnostic('stream.run', error)
            # Never print provider details; these may echo authentication metadata.
            if isinstance(error, RuntimeError):
                message = str(error)
            elif self.name == 'soniox' and type(error).__name__ == 'WebSocketBadStatusException':
                message = 'Soniox 연결 거부 · HTTP status=' + _safe_diagnostic(getattr(error, 'status_code', '없음'))
            else:
                message = type(error).__name__
                if self.name == 'soniox' and isinstance(getattr(error, 'winerror', None), int):
                    message += ' · WinError=' + str(error.winerror)
            self.events.emit('ERROR', self.name, text=message + ' · 자동 재시도 없음')
        finally:
            self.ready.set()

    def diagnostic(self, stage, error):
        # No exception messages, source lines, locals, keys or provider payloads.
        if not getattr(self.args, 'structured', False):
            return
        import os
        frames = []
        tb = error.__traceback__
        while tb is not None and len(frames) < 32:
            frames.append({'file': os.path.basename(tb.tb_frame.f_code.co_filename),
                           'function': tb.tb_frame.f_code.co_name, 'line': tb.tb_lineno})
            tb = tb.tb_next
        self.events.emit('DIAGNOSTIC', self.name, stage=stage,
                         errorType=type(error).__name__, frames=frames)

    def soniox(self, key, first, blocks):
        import websocket
        base_ms, first_pcm = first
        # Raw PCM: no WAV header. Soniox's token stream carries partial and final text.
        from soniox_billing import request_started, request_state
        ledger = getattr(self.args, 'billing_ledger', None)
        reference_id = 'synesis-rt-' + uuid.uuid4().hex
        request_started(ledger, reference_id, 'stt-rt-v5')
        socket = None
        submitted = False
        try:
            socket = websocket.create_connection('wss://stt-rt.soniox.com/transcribe-websocket',
                                                 header=['Authorization: Bearer ' + key], timeout=5)
            opened_at = time.monotonic()
            stats = {'sent_bytes': 0, 'server_ms': 0}

            def progress():
                return (f'전송={stats["sent_bytes"] / 32000:.1f}초 · '
                        f'서버 처리={stats["server_ms"] / 1000:.1f}초 · '
                        f'연결={time.monotonic() - opened_at:.1f}초 · '
                        f'대기={self.queue.qsize() / 10:.1f}초 · 참조 ID={reference_id}')

            config = {'api_key': key, 'model': 'stt-rt-v5', 'audio_format': 'pcm_s16le',
                      'sample_rate': 16000, 'num_channels': 1,
                      'enable_endpoint_detection': True, 'client_reference_id': reference_id}
            if getattr(self.args, 'diarization', False):
                config['enable_speaker_diarization'] = True
                # Premature endpoint finalization reduces speaker attribution accuracy.
                config['enable_endpoint_detection'] = False
            if self.args.language != 'auto':
                config['language_hints'] = [self.args.language]
            if self.args.prompt:
                config['context'] = {'text': self.args.prompt}
            request_state(ledger, reference_id, 'submitted')
            submitted = True
            socket.send(json.dumps(config))
            # Deliver the first live block before starting the receive loop. This
            # also keeps initial transport failures on the calling thread.
            socket.send_binary(first_pcm)
            stats['sent_bytes'] += len(first_pcm)
            self.sent_bytes = base_ms * 32 + stats['sent_bytes']
            next_send_at = time.monotonic() + len(first_pcm) / 32000
            self.events.emit('STATUS', self.name, text='Soniox 연결됨 · 참조 ID=' + reference_id)
            sender_error = []
            sender_stop = threading.Event()

            def send():
                try:
                    # The microphone already supplies real-time blocks. Pace only if
                    # buffered input arrives faster; never sleep an extra block after it.
                    due = next_send_at
                    for at_ms, pcm in blocks:
                        if sender_stop.is_set() or self.restart_requested.is_set():
                            break
                        now = time.monotonic()
                        if due > now:
                            time.sleep(due - now)
                        else:
                            due = now
                        self.send_started_at = time.monotonic()
                        try:
                            socket.send_binary(pcm)
                            stats['sent_bytes'] += len(pcm)
                            self.sent_bytes = at_ms * 32 + len(pcm)
                        finally:
                            self.send_started_at = None
                        due += len(pcm) / 32000
                    if not sender_stop.is_set():
                        socket.send('')
                        self.events.emit('STATUS', self.name, text='Soniox 종료 프레임 전송 · 최종 응답 대기')
                except Exception as error:
                    sender_error.append(type(error).__name__)
                    self.diagnostic('soniox.sender', error)
                    socket.close()

            thread = threading.Thread(target=send, daemon=True)
            thread.start()
            final = ''
            socket.settimeout(5)
            while not self.failed.is_set():
                if self.restart_requested.is_set():
                    raise RuntimeError('Soniox 입력 적체 재연결 · ' + progress())
                try:
                    opcode, payload = socket.recv_data(control_frame=True)
                    self.last_response_at = time.monotonic()
                    if self.restart_requested.is_set():
                        raise RuntimeError('Soniox 입력 적체 재연결 · ' + progress())
                except websocket.WebSocketTimeoutException:
                    if not thread.is_alive():
                        if sender_error:
                            raise RuntimeError('Soniox 음성 전송 실패 · ' + sender_error[0] + ' · ' + progress()) from None
                        raise RuntimeError('Soniox 최종 응답 시간 초과 · ' + progress()) from None
                    continue
                except websocket.WebSocketConnectionClosedException:
                    if sender_error:
                        raise RuntimeError('Soniox 음성 전송 실패 · ' + sender_error[0] + ' · ' + progress()) from None
                    raise RuntimeError('Soniox 연결 끊김 · close_code=수신 못함 (서버 오류 응답/종료 프레임 없음) · '
                                       + progress()) from None
                if opcode == websocket.ABNF.OPCODE_CLOSE:
                    if sender_error:
                        raise RuntimeError('Soniox 음성 전송 실패 · ' + sender_error[0] + ' · ' + progress())
                    raise RuntimeError('Soniox 연결 종료 · close_code=' + str(_soniox_close_code(payload))
                                       + ' · finished 응답 없음 · ' + progress())
                if opcode not in (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY):
                    continue
                try:
                    event = json.loads(payload)
                except (ValueError, TypeError):
                    raise RuntimeError('Soniox 응답 JSON 파싱 실패') from None
                if not isinstance(event, dict):
                    raise RuntimeError('Soniox 응답 형식 오류')
                if 'error_code' in event:
                    raise SonioxServerError(event, progress())
                server_ms = event.get('total_audio_proc_ms')
                if type(server_ms) in (int, float) and 0 <= server_ms < 120 * 60 * 1000:
                    stats['server_ms'] = max(stats['server_ms'], int(server_ms))
                    self.confirmed_ms = max(self.confirmed_ms, base_ms + int(server_ms))
                for token in event.get('tokens', []):
                    if type(token.get('end_ms')) in (int, float):
                        self.confirmed_ms = max(self.confirmed_ms, base_ms + int(token['end_ms']))
                if self.gap_start_ms is not None:
                    self.finish_gap(base_ms)
                    self.reconnect_attempt = 0
                    self.events.emit('RECONNECTED', self.name, atMs=base_ms,
                                     text='Soniox 연결 복구 · 실시간 자막 재개')
                if getattr(self.args, 'structured', False):
                    self.events.emit('TOKENS', self.name, tokens=event.get('tokens', []),
                                     finished=bool(event.get('finished')),
                                     offsetMs=base_ms, connectionId=reference_id)
                else:
                    provisional = ''
                    for token in event.get('tokens', []):
                        if token.get('is_final'):
                            final += token.get('text', '')
                        else:
                            provisional += token.get('text', '')
                    if event.get('tokens'):
                        self.report(final, provisional)
                if event.get('finished'):
                    request_state(ledger, reference_id, 'completed')
                    break
            thread.join(2)
            if sender_error:
                raise RuntimeError('Soniox 음성 전송 실패 · ' + sender_error[0] + ' · ' + progress())
            if thread.is_alive() and not self.finished.is_set():
                raise RuntimeError('Soniox 연결 조기 종료 · ' + progress())
        finally:
            if not submitted:
                request_state(ledger, reference_id, 'no_charge')
            if 'sender_stop' in locals():
                sender_stop.set()
            if socket is not None:
                socket.close()
            if 'thread' in locals():
                thread.join(6)

    def daglo(self, key, first, blocks):
        import grpc
        Config, Request, Response = daglo_messages()
        language = {'ko': 'ko-KR', 'en': 'en-US', 'auto': 'mixed'}[self.args.language]

        def requests():
            yield Request(config=Config(language_code=language, interim_results=True))
            yield Request(audio_content=first)
            due = time.monotonic() + len(first) / 32000
            for pcm in blocks:
                now = time.monotonic()
                if due > now:
                    time.sleep(due - now)
                else:
                    due = now
                yield Request(audio_content=pcm)
                due += len(pcm) / 32000
            yield Request()  # EOS documented by Daglo.

        channel = grpc.secure_channel('apis.daglo.ai:443', grpc.ssl_channel_credentials())
        try:
            rpc = channel.stream_stream('/dagloapis.speech.v1.Speech/StreamingRecognize',
                                        request_serializer=lambda request: request.SerializeToString(),
                                        response_deserializer=Response.FromString)
            final = ''
            for response in rpc(requests(), metadata=(('authorization', 'Bearer ' + key),)):
                if response.HasField('result'):
                    if getattr(self.args, 'structured', False):
                        self.events.emit('DAGLO_RESULT', self.name, text=response.result.transcript,
                                         is_final=response.result.is_final,
                                         processed_ms=round(response.total_duration * 1000))
                    elif response.result.is_final:
                        final += response.result.transcript
                        self.report(final, '')
                    else:
                        self.report(final, response.result.transcript)
        except grpc.RpcError as error:
            raise RuntimeError('다글로 gRPC ' + error.code().name + ' (실시간 권한·잔액·네트워크 확인)') from None
        finally:
            channel.close()
