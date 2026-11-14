"""Pooled verified HTTP/1.1 study transport, without generation retries.

urllib3 preserves an early HTTP response even if the server stops the upload
with BrokenPipe/ECONNRESET. Plain urllib can lose that response. A POST may be
reconnected only before its full JSON body could have been sent; ambiguous last
writes and acknowledged lost streams use read-only GET instead of another POST.
"""
import io
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib3
from pdf_study_upload import CONNECT_TIMEOUT, UploadPolicy, upload_policy, configure_upload_pools


class RequestNotSentError(Exception):
    request_not_sent=True
    def __init__(self,reason,*,cancelled=False):
        super().__init__('Study request stopped before transmission')
        self.reason_code=reason;self.cancelled=cancelled


class StreamFile:
    def __init__(self,response):
        self.response=response;self.headers=response.headers
        class ReadAvailable(io.RawIOBase):
            def readable(self):return True
            def readinto(self,buffer):
                # read1 performs one available socket read, rather than waiting
                # to fill the buffer before showing an early short delta.
                data=response.read1(len(buffer))
                buffer[:len(data)]=data;return len(data)
            def close(self):response.close();super().close()
        self.reader=io.BufferedReader(ReadAvailable());self.finished=False
    @property
    def fp(self):return self.response._fp.fp
    def readline(self,size=-1):
        try:
            line=self.reader.readline(size)
            if line.strip()==b'data: [DONE]':self.finished=True
            return line
        except urllib3.exceptions.HTTPError as error:raise OSError('Study response read failed')from error
    def read(self,*args):
        try:
            value=self.reader.read(*args)
            if not args or args[0]is None or args[0]<0:self.finished=True
            return value
        except urllib3.exceptions.HTTPError as error:raise OSError('Study response read failed')from error
    def close(self):
        try:
            if self.finished:
                # DONE/EOF is already genuine. Only drain a possible final
                # HTTP chunk; an anomalous/incomplete stream closes immediately.
                try:
                    self.fp.raw._sock.settimeout(.5);self.response.drain_conn()
                except (OSError,AttributeError,urllib3.exceptions.HTTPError):pass
        finally:
            try:self.reader.close()
            except (OSError,urllib3.exceptions.HTTPError):pass
            finally:self.response.release_conn()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class StudyHttpTransport:
    def __init__(self, *, max_unsent_attempts=2, max_uploads=3, max_connections=16, allow_overflow=False):
        self.max_unsent_attempts=max(1,int(max_unsent_attempts))
        self.upload_slots=threading.BoundedSemaphore(max_uploads)
        options={'num_pools':2,'maxsize':max_connections,'block':not allow_overflow,'retries':False,
                 'ssl_context':ssl.create_default_context()}
        proxies=urllib.request.getproxies()
        proxy=proxies.get('https')or proxies.get('all')
        if proxy and not urllib.request.proxy_bypass('api.openai.com'):
            auth=urllib.parse.urlsplit(proxy)
            headers=urllib3.make_headers(proxy_basic_auth=urllib.parse.unquote(auth.username)+':'+urllib.parse.unquote(auth.password or''))if auth.username else None
            self.pool=urllib3.ProxyManager(proxy,proxy_headers=headers,**options)
            self.control_pool=urllib3.ProxyManager(proxy,proxy_headers=headers,**{**options,'maxsize':4,'block':True})
        else:
            self.pool=urllib3.PoolManager(**options)
            self.control_pool=urllib3.PoolManager(**{**options,'maxsize':4,'block':True})
        configure_upload_pools(self.pool)
        configure_upload_pools(self.control_pool)
    def open(self,request,timeout,*,update=lambda **x:None,check=lambda:None,open_url=None,
             on_socket=lambda connection:None):
        url=urllib.parse.urlsplit(request.full_url)
        # A resumed generation stream is long-lived; it must not occupy the
        # small lane reserved for status queries and server cancellation.
        resumed=request.method=='GET'and urllib.parse.parse_qs(url.query).get('stream')==['true']
        control=(request.method=='GET'and not resumed)or url.path.endswith('/cancel')
        creation=request.method=='POST'and not url.path.endswith('/cancel')
        # Cleanup/status reads must remain available after the user's cancel.
        # Failure to send a GET/cancel never proves the ORIGINAL POST was unsent.
        if not control:
            try:check()
            except InterruptedError as error:
                if creation:raise RequestNotSentError('cancelled',cancelled=True)from error
                raise
        pool=self.control_pool if control else self.pool
        # This proof is restricted to complete, length-framed JSON API bodies.
        # A failed last send may have transmitted ALL attempted bytes, so use
        # its upper bound, never just the last successful progress count.
        json_body=False
        if creation and request.get_header('Content-type','').split(';')[0]=='application/json':
            try:json_body=isinstance(json.loads(request.data),dict)
            except (ValueError,TypeError):pass
        length=request.get_header('Content-length')
        if request.has_header('Transfer-encoding')or length is not None and str(length)!=str(len(request.data or b'')):
            json_body=False
        policy=None
        update(httpTransport='pooled_http1_no_retries',connectionLane='control'if control else'generation')
        try:
            started=time.monotonic()
            for attempt in range(self.max_unsent_attempts):
                lease=[False]
                def release_upload():
                    if lease[0]:lease[0]=False;self.upload_slots.release()
                if creation:
                    update(networkPhase='waiting_upload_slot')
                    while not self.upload_slots.acquire(timeout=.1):check()
                    lease[0]=True
                policy=UploadPolicy(request,timeout,control=control,update=update,
                    check=(lambda:None)if control else check,on_uploaded=release_upload,
                    on_socket=on_socket)
                try:
                    remaining=max(.001,timeout-(time.monotonic()-started))
                    with upload_policy(policy):
                        response=pool.request(request.method,request.full_url,body=request.data,
                            headers=dict(request.header_items()),preload_content=False,decode_content=True,
                            retries=False,redirect=False,pool_timeout=remaining,
                            # Header waiting starts AFTER the upload. A total
                            # timer would wrongly subtract a healthy slow upload.
                            timeout=urllib3.Timeout(connect=min(CONNECT_TIMEOUT,remaining),
                                                    read=remaining if control else timeout,
                                                    total=remaining if control else None))
                    break
                except (OSError,urllib3.exceptions.HTTPError)as error:
                    # These fail while establishing a connection, before any
                    # model POST exists. One reconnect cannot duplicate/bill
                    # generation. Upload/read/protocol/HTTP failures never enter
                    # this path and are never blindly submitted again.
                    policy.failed()
                    # Proxy CONNECT/TLS setup can surface as a read timeout or
                    # protocol error rather than ConnectTimeoutError. Our send
                    # observer proves that no model request write was attempted.
                    before_connect=(policy.phase=='connecting'and not policy.write_attempted
                        and isinstance(error,(urllib3.exceptions.NewConnectionError,
                            urllib3.exceptions.ConnectTimeoutError,urllib3.exceptions.ReadTimeoutError,
                            urllib3.exceptions.ProtocolError,urllib3.exceptions.ProxyError)))
                    incomplete=(creation and json_body and policy.phase=='uploading_request'
                        and policy.body_size and policy.body_attempted_upper<policy.body_size)
                    safe=before_connect or incomplete
                    if policy.cancelled:raise InterruptedError('Study request cancelled during transmission')from error
                    if not safe:raise
                    if attempt+1>=self.max_unsent_attempts or time.monotonic()-started>=timeout:
                        if creation:raise RequestNotSentError('incomplete_request_body'if incomplete else'connection_not_established')from error
                        raise urllib.error.URLError(error)from error
                    update(unsentConnectionReconnects=attempt+1,
                        reconnectSafety='complete_json_body_never_attempted'if incomplete else'connection_not_established')
                    if not control:
                        try:check()
                        except InterruptedError as error:
                            if creation:raise RequestNotSentError('cancelled',cancelled=True)from error
                            raise
                finally:release_upload()
        except InterruptedError as error:
            if policy is not None:policy.failed()
            incomplete=(json_body and policy is not None and policy.phase=='uploading_request'
                and policy.body_size and policy.body_attempted_upper<policy.body_size)
            if creation and (policy is None or not policy.write_attempted or incomplete):
                raise RequestNotSentError('cancelled',cancelled=True)from error
            raise
        except urllib3.exceptions.EmptyPoolError as error:
            if policy is not None:policy.failed()
            if creation:raise RequestNotSentError('local_connection_queue')from error
            raise urllib.error.URLError(error)from error
        except (OSError,urllib3.exceptions.HTTPError)as error:
            policy.failed()
            if policy.cancelled:
                if creation and not policy.write_attempted:raise RequestNotSentError('cancelled',cancelled=True)from error
                raise InterruptedError('Study request cancelled during transmission')from error
            raise urllib.error.URLError(error)from error
        finally:
            on_socket(None)
        if response.status>=300:
            try:raw=response.read(8192)
            finally:response.close();response.release_conn()
            raise urllib.error.HTTPError(request.full_url,response.status,'AI HTTP error',
                                          response.headers,io.BytesIO(raw))
        return StreamFile(response)
    def close(self):
        try:self.pool.clear()
        finally:self.control_pool.clear()
