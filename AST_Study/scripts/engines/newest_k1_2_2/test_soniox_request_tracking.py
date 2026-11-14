"""Offline integration: the exact reference sent to each API must be durable before submission."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import queue
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

import websocket
from live_streams import StreamWorker
from recover_lecture import recover_one


class TrackingTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ledger=self.root/'billing.json'
        self.ledger.write_text(json.dumps({'sealed':False,'requests':{}}))

    def worker(self):
        w=StreamWorker.__new__(StreamWorker)
        w.args=SimpleNamespace(language='auto',prompt='',structured=True,diarization=True,billing_ledger=str(self.ledger))
        w.failed=threading.Event();w.restart_requested=threading.Event();w.finished=threading.Event();w.queue=queue.Queue()
        w.name='soniox';w.gap_start_ms=None;w.confirmed_ms=0;w.events=SimpleNamespace(emit=lambda *a,**k:None)
        return w

    def test_realtime_and_reconnect_each_have_unique_durable_reference(self):
        configs=[];ledger=self.ledger
        class Socket:
            def send(self,data):
                if data:
                    config=json.loads(data);configs.append(config)
                    saved=json.loads(ledger.read_text())['requests'][config['client_reference_id']]
                    self_test.assertEqual(saved['state'],'submitted')
                    self_test.assertEqual(saved['model'],config['model'])
            def send_binary(self,data):pass
            def settimeout(self,value):pass
            def close(self):pass
            def recv_data(self,**kwargs):return websocket.ABNF.OPCODE_TEXT,json.dumps({'tokens':[],'finished':True})
        self_test=self
        with patch('websocket.create_connection',side_effect=lambda *a,**k:Socket()):
            self.worker().soniox('fake-key',(0,bytes(3200)),iter(()))
            self.worker().soniox('fake-key',(1000,bytes(3200)),iter(()))
        requests=json.loads(self.ledger.read_text())['requests']
        self.assertEqual(len(requests),2);self.assertEqual(len({c['client_reference_id'] for c in configs}),2)
        self.assertTrue(all(r['state']=='completed' for r in requests.values()))

    def test_transport_failure_before_submission_is_known_no_charge(self):
        with patch('websocket.create_connection',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):self.worker().soniox('fake-key',(0,bytes(3200)),iter(()))
        requests=json.loads(self.ledger.read_text())['requests']
        self.assertEqual(next(iter(requests.values()))['state'],'no_charge')

    def test_recovery_records_reference_before_job_creation(self):
        audio=self.root/'capture.wav'
        with wave.open(str(audio),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(bytes(32000*3))
        references=[]
        def api(session,method,path,**kwargs):
            if path=='/files':return {'id':'file'}
            if path=='/transcriptions':
                ref=kwargs['json']['client_reference_id'];references.append(ref)
                saved=json.loads(self.ledger.read_text())['requests'][ref]
                self.assertEqual(saved['state'],'submitted');self.assertEqual(saved['model'],'stt-async-v5')
                return {'id':'job'}
            if path.endswith('/transcript'):return {'tokens':[]}
            return {'status':'completed'}
        session=SimpleNamespace(delete=lambda *a,**k:None)
        with patch('recover_lecture.api',side_effect=api),redirect_stdout(io.StringIO()):
            recover_one(session,str(audio),1000,2000,0,str(self.ledger))
            recover_one(session,str(audio),1000,2000,0,str(self.ledger))
        self.assertEqual(len(set(references)),2) # No collision for equal intervals across recording sessions.
        self.assertTrue(all(r['state']=='completed' for r in json.loads(self.ledger.read_text())['requests'].values()))

if __name__=='__main__':unittest.main()
