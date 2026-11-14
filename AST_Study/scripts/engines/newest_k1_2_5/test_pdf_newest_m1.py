import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import pdf_newest_m1 as engine
from pdf_pipeline import write_json

class NewestTest(unittest.TestCase):
    def test_twenty_workers_prompt_stream_order_and_resume(self):
        document={'documentId':'doc','fingerprint':'fp','pages':[{'page':1,'label':'1','nativeText':'내용'}]}
        class Provider:
            model='gpt-6-luna'
            context={}
        provider=Provider()
        lock=threading.Lock();barrier=threading.Barrier(20);active=0;peak=0;calls=[];events=[]
        def complete(provider,payload,**options):
            nonlocal active,peak
            self.assertEqual(options['system_prompt'],engine.PROMPT)
            self.assertEqual(options['response_format'],engine.FORMAT)
            with lock:
                active+=1;peak=max(peak,active);calls.append(payload['unitId']);count=len(calls)
            if count<=20:barrier.wait(timeout=5)
            time.sleep(.002)
            with lock:active-=1
            return {'answer':payload['unitId']+'의 설명 $x^2$'}
        with tempfile.TemporaryDirectory() as folder:
            root=engine.root_path(folder,document,'newest-m1',provider.model,'document',0)
            jobs=[{'id':f'u{i}','title':f'단위{i}','blocks':[{'id':f'b{i}','page':1,'bbox':[0,0,1,1]}]} for i in range(23)]
            write_json(root/'manifest.json',{'jobs':jobs})
            with patch.object(engine,'selection',return_value=(0,[1],[])),patch.object(engine.units,'render_crops',return_value=([],[])),patch.object(engine,'emit',side_effect=lambda *a,**kw:events.append((a,kw))),patch('pdf_ai.complete_study_delivery',side_effect=complete),patch('pdf_ai.run_usage',return_value={'requests':0}):
                result=engine.generate(folder,document,provider)
                self.assertEqual(peak,20)
                self.assertEqual(len(calls),23)
                self.assertTrue(result['processingComplete'])
                self.assertEqual(result['concepts'],[])
                self.assertEqual([s['title'] for s in result['sections']],[j['title'] for j in jobs])
                self.assertEqual(sum(a[0]=='summary_unit_ready' for a,k in events),23)
                engine.generate(folder,document,provider)
                self.assertEqual(len(calls),23)
    def test_empty_answer_rejected(self):
        with self.assertRaises(ValueError):engine.summary({'answer':' '},{}, {})
    def test_namespace_independent(self):
        doc={'fingerprint':'fp'}
        self.assertIn('/newest-m1/',str(engine.root_path('/tmp',doc,'newest-m1','gpt-6-luna','document',0)))

if __name__=='__main__':unittest.main()
