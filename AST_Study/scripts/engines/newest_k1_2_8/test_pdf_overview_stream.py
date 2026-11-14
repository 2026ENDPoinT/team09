import json,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from pdf_overview_stream import OverviewPreview
from pdf_parallel_overview import ParallelOverview
from pdf_pipeline import write_json

class OverviewStreamingTests(unittest.TestCase):
    def test_split_unicode_escape_and_private_fields(self):
        values=[];p=OverviewPreview(lambda body,**kw:values.append(body))
        raw=json.dumps({'sourceSetup':'PRIVATE','body':'먼저 개념을 살펴봐요. 😀','topicIds':['SECRET']},ensure_ascii=True)
        for c in raw:p.feed(c)
        self.assertEqual(values[-1],'먼저 개념을 살펴봐요. 😀')
        self.assertTrue(any(len(x)<len(values[-1])for x in values))
        self.assertFalse(any('SECRET'in x or'PRIVATE'in x or'\\u'in x for x in values))
    def test_retry_is_a_new_document(self):
        events=[];p=OverviewPreview(lambda body,**kw:events.append((body,kw)))
        p.feed('{"body":"이전');p.reset();p.feed('{"body":"새 결과"}')
        self.assertEqual(events[-1][0],'새 결과');self.assertTrue(events[-2][1]['discard'])
    def test_preview_does_not_overwrite_saved_canonical_flow(self):
        events=[]
        with TemporaryDirectory()as tmp,ThreadPoolExecutor(max_workers=1)as pool:
            path=Path(tmp)/'partial.json';write_json(path,{'overview':{'body':'initial'}})
            flow=ParallelOverview({'body':'initial'},path,emit=lambda name,**data:events.append((name,data)),metadata={'strategy':'newest-k1-2-8'})
            def generate():
                flow.preview('일부 내용');self.assertEqual(json.loads(path.read_text())['overview']['body'],'initial')
                return {'body':'검증한 최종 내용'}
            flow.start(pool,generate);self.assertEqual(flow.result()['body'],'검증한 최종 내용')
            self.assertEqual([x[0]for x in events],['summary_overview_delta','summary_overview_ready'])
            flow.preview('늦은 이전 응답');self.assertEqual(len(events),2)
if __name__=='__main__':unittest.main()

class PlannedOverviewWiringTests(unittest.TestCase):
    def test_actual_flow_call_streams_and_keeps_original_final_evidence(self):
        import pdf_newest_k1_2_0 as e
        events=[]
        class Provider:
            model='gpt-6-luna'
            def complete(self,payload,**options):
                self.options=options
                value={'body':'먼저 원리를 살펴보고 적용으로 이어져요.','topicIds':['k1']}
                text=json.dumps(value,ensure_ascii=False)
                for i in range(0,len(text),3):options['on_study_delta'](text[i:i+3])
                return value
        with TemporaryDirectory()as tmp:
            provider=Provider();provider.folder=Path(tmp)
            result=e.planned_overview(provider,Path(tmp),[{'title':'원리와 적용','description':'원리를 적용해요.','blocks':[{'id':'a','page':1,'bbox':[0,0,1,1]}]}],{'documentId':'test','pages':[{'label':'1'}]},on_preview=lambda body,**kw:events.append(body))
            self.assertEqual(result['body'],events[-1]);self.assertGreater(len(events),2)
            self.assertEqual(result['sourceSectionIds'],['k1']);self.assertEqual(result['visualPages'],[1])
            self.assertEqual(provider.options['max_output'],500)
