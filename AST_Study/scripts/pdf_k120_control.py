"""K1.2.0 foreground cancellation and exact original-receipt accounting.

Closing the creation socket cancels foreground generation. GETs only recover
stored receipts; missing/partial replies never release a possibly paid hold.
"""
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

TERMINAL={'completed','incomplete','cancelled','failed'}
READS=3
TIMEOUT=6.0
WINDOW=20.0


def _shutdown(connection):
    if connection is None:return
    try:connection.shutdown(socket.SHUT_RDWR)
    except (AttributeError,OSError):pass


class ForegroundControl:
    def __init__(self,provider,entry,response_cache,*,schema=None):
        self.provider,self.entry=provider,entry
        self.response_cache=Path(response_cache)
        self.schema=schema
        self.lock=threading.Lock()
        self.connection=None
        self.stream=None
        self.response_id=None
        self.stopped=False
        self.receipt_started=False

    def bind_socket(self,connection):
        with self.lock:
            self.connection=connection
            stop=self.stopped
        if stop:_shutdown(connection)

    def bind_stream(self,stream):
        with self.lock:
            self.stream=stream
            stop=self.stopped
        if stop:self._shutdown_stream(stream)

    @staticmethod
    def _shutdown_stream(stream):
        try:connection=stream.fp.raw._sock
        except AttributeError:return
        _shutdown(connection)

    def acknowledge(self,response_id):
        from pdf_study_connection import RESPONSE_ID
        if not isinstance(response_id,str)or not RESPONSE_ID.fullmatch(response_id):return
        with self.lock:
            if self.response_id not in (None,response_id):return
            self.response_id=response_id
            # A late response ID may arrive just after socket shutdown. Do not
            # block the stream callback (which may hold Provider's ledger lock).
            recover=self.stopped and not self.receipt_started
            if recover:self.receipt_started=True
        if recover:
            threading.Thread(target=self._recover,args=(response_id,),
                name='study-foreground-late-receipt',daemon=False).start()

    def stop(self):
        with self.lock:
            self.stopped=True
            connection,stream=self.connection,self.stream
            response_id=self.response_id
            recover=response_id is not None and not self.receipt_started
            if recover:self.receipt_started=True
        # Never hold either lock while shutting down or performing network I/O.
        _shutdown(connection)
        self._shutdown_stream(stream)
        if recover:self._recover(response_id)

    def _update(self,**fields):
        from pdf_pipeline import write_json
        with self.provider._lock:
            self.entry.update(fields)
            write_json(self.provider.ledger_path,self.provider.ledger)

    def _recover(self,response_id):
        provider=self.provider
        transport=getattr(provider,'study_http_transport',None)
        open_url=(lambda req,timeout:transport.open(req,timeout))if transport is not None else urllib.request.urlopen
        request=urllib.request.Request('https://api.openai.com/v1/responses/'+response_id,
            headers={'Authorization':'Bearer '+provider.key,'Cache-Control':'no-cache'},method='GET')
        deadline=time.monotonic()+WINDOW
        for attempt in range(READS):
            remaining=deadline-time.monotonic()
            if remaining<=0:return
            self._update(foregroundStopReceiptReads=attempt+1)
            try:
                with open_url(request,timeout=min(TIMEOUT,remaining))as reply:native=json.load(reply)
                if not isinstance(native,dict)or native.get('id')!=response_id:
                    raise ValueError('Receipt identity mismatch')
                if native.get('status')in TERMINAL:
                    if self._preserve(native):return
                else:
                    self._update(foregroundStopReceiptPending=True)
            except (OSError,ValueError,TypeError) as error:
                fields={'foregroundStopReceiptError':type(error).__name__}
                if isinstance(error,urllib.error.HTTPError):fields['foregroundStopReceiptHttpStatus']=error.code
                self._update(**fields)
            if attempt+1<READS:time.sleep(min(1,max(0,deadline-time.monotonic())))

    def _preserve(self,native):
        from pdf_pipeline import write_json
        from pdf_responses_transport import response_body
        from pdf_study_receipts import strict_object,receipt_cost
        from pdf_study_tail import native_timings
        from pdf_study_rejection import is_rejected,rejected_entry,mark_rejected
        provider,entry=self.provider,self.entry
        normalized=response_body(native)
        usage=normalized.get('usage')
        valid_usage=isinstance(usage,dict)and all(type(usage.get(k))is int and usage[k]>=0
            for k in ('prompt_tokens','completion_tokens'))
        # Only an attempt's private cache can become reusable here. A loser
        # must never overwrite the logical winner, even when its text is valid.
        private=(entry.get('responseCacheKey')==self.response_cache.stem
                 and isinstance(entry.get('logicalResponseCacheKey'),str)
                 and entry['logicalResponseCacheKey']!=self.response_cache.stem)
        receipt=self.response_cache.with_suffix('.stop.receipt.json')
        with provider._lock:
            if rejected_entry(entry):mark_rejected(self.response_cache,entry)
            unusable=is_rejected(self.response_cache,entry)
            write_json(receipt,native)
            entry.update(serverTerminalStatus=native['status'],foregroundStopReceiptRecovered=True,
                         **native_timings(native))
            if private:write_json(self.response_cache.with_suffix('.responses.raw.json'),native)
            if native['status']=='completed' and not unusable:
                try:
                    choice=normalized['choices'][0]
                    if choice.get('finish_reason')!='stop'or choice.get('message',{}).get('refusal'):
                        raise ValueError('Incomplete or refused original')
                    value=strict_object(choice['message']['content'])
                    if self.schema is not None:
                        from pdf_study_batch_transport import _validate
                        _validate(value,self.schema,self.schema)
                    if private:
                        write_json(self.response_cache.with_suffix('.raw.json'),normalized)
                        write_json(self.response_cache,value)
                        entry['foregroundStopPrivateResultRecovered']=True
                except (ValueError,KeyError,IndexError,TypeError):
                    entry['foregroundStopResultInvalid']=True
            elif unusable:
                entry['foregroundStopResultRejected']=True
            if valid_usage and entry.get('state')!='settled':
                if 'requestedServiceTier'in entry:
                    tier=normalized.get('service_tier')
                    entry['returnedServiceTier']=tier
                    entry['billedServiceTier']='default'if tier=='default'else'fast'if tier in ('fast','priority')else entry['requestedServiceTier']
                actual,premium=receipt_cost(provider.model,usage,entry)
                # Provider's normal foreground settlement checks this same
                # settled state under the same lock, so exactly one path wins.
                provider.spent+=actual-entry['reservedUsd']
                entry.update(state='settled',usage=usage,estimatedUsd=actual,
                             cacheWritePremiumUsd=premium,foregroundStopUsageRecovered=True)
            elif not valid_usage and entry.get('state')=='reserved':
                entry['state']='usage_unknown'
            write_json(provider.ledger_path,provider.ledger)
            try:
                provider.settle_credits(entry)
                write_json(provider.ledger_path,provider.ledger)
            except Exception as error:
                entry['recoveryBillingPending']=True
                entry['recoveryBillingError']=type(error).__name__
                write_json(provider.ledger_path,provider.ledger)
        return valid_usage
