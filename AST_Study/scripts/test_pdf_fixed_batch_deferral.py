"""Exercise the real scheduler: money becoming available must not repack tasks."""
import copy,json,socket,tempfile,threading,unittest
from pathlib import Path
from contextlib import ExitStack
from collections import Counter
from unittest.mock import patch
import pdf_newest_k11 as baseline
import pdf_newest_k1_1_1 as candidate
from pdf_pipeline import write_json
from pdf_ai import BudgetExceeded
from test_pdf_newest_k11 import block,response

class DeferredWireLifecycleTests(unittest.TestCase):
 def test_real_budget_refill_and_second_round_keep_exact_original_pairs(self):
  for engine,strategy,workers in [(baseline,'newest-k1-1',1),(baseline,'newest-k1-1',20),(candidate,'newest-k1-1-1',1),(candidate,'newest-k1-1-1',20)]:
   with self.subTest(strategy=strategy,workers=workers),tempfile.TemporaryDirectory()as tmp,ExitStack()as stack:
    stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('offline')))
    blocks=[block(i)for i in range(12)];groups=[{'title':f'주제{i}','description':'정의와 조건','blocks':[b]}for i,b in enumerate(blocks)]
    doc={'documentId':'fixed-refill','fingerprint':'fixed-refill','pages':[{'number':b['page'],'label':str(b['page']),'nativeText':b['text']}for b in blocks]}
    class Provider:
     model='gpt-6-luna';billing=None;context={};ledger={'requests':[]};transport=object()
     def complete(self,payload,**kwargs):return {'body':'정의와 조건을 비교해요.','topicIds':['k1']}
    lock=threading.Lock();calls=Counter();rejected=set()
    def complete(provider,payload,**kwargs):
     is_pair=payload['task']=='region_teaching_batch';units=payload['units']if is_pair else {'single':payload}
     refs=tuple(u['blocks'][0]['id']for u in units.values())
     with lock:
      calls[refs]+=1
      if is_pair and refs not in rejected and len(rejected)<2:
       rejected.add(refs);raise BudgetExceeded('temporary test reservation')
     values={name:response(u['blocks'][0]['id'])for name,u in units.items()}
     if engine is candidate:
      for value in values.values():value['concepts'][0]['sourceSetup']['sourceQuotes']=[]
     return values if is_pair else values['single']
    for name,value in {'SOURCE_ID_ALIASES':False,'TRANSPORT_BATCH_ALIASES':False,'TRANSPORT_BATCH_UNITS':2,'WORKERS':workers}.items():stack.enter_context(patch.object(engine,name,value))
    folder=Path(tmp);provider=Provider();root=engine.root_path(folder,doc,strategy,provider.model,'document',0)
    write_json(root/'plan.json',engine.plan_record(groups,[],provider.model,[],blocks=blocks))
    stack.enter_context(patch.object(engine,'extract_layout',return_value=copy.deepcopy(blocks)))
    stack.enter_context(patch.object(engine,'render_crops',return_value=([],[])))
    stack.enter_context(patch.object(engine,'emit'))
    stack.enter_context(patch('pdf_ai.complete_study_delivery',side_effect=complete))
    stack.enter_context(patch('pdf_ai.run_usage',return_value={}))
    result=engine.generate(folder,doc,provider,strategy=strategy)
    self.assertTrue(result['processingComplete'],result.get('failedUnits'))
    plan=json.loads((root/'transport-plan.json').read_text());jobs=json.loads((root/'manifest.json').read_text())['jobs'];byid={j['id']:j for j in jobs}
    expected={tuple(byid[j]['blocks'][0]['id']for j in batch)for batch in plan['batches']}
    self.assertEqual(set(calls),expected)
    self.assertEqual(len(rejected),2)
    self.assertTrue(all(calls[pair]==2 for pair in rejected),calls)

if __name__=='__main__':unittest.main()
