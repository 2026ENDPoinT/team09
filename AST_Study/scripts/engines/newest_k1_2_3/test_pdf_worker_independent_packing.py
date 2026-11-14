"""Changing execution capacity must not change any request's source composition."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch
import pdf_newest_k11 as baseline
import pdf_newest_k1_1_1 as candidate
from test_pdf_newest_k11 import block

class WorkerIndependentPackingTests(unittest.TestCase):
 def jobs(self,n):
  return [{'id':str(i),'blocks':[{**block(i),'text':'source '+('x'*(i*23))}]}for i in range(n)]
 def pack(self,engine,jobs,workers,**kwargs):
  with patch.object(engine,'study_workers',side_effect=AssertionError('Packing must not inspect workers')),patch.object(engine,'MAX_STUDY_WORKERS',workers),patch.object(engine,'TRANSPORT_BATCH_UNITS',kwargs.pop('batch_units',2)):
   return engine.transport_batches(list(range(len(jobs))),jobs,**kwargs)
 def test_every_worker_count_keeps_exact_unit_pairs_and_preview_front(self):
  for n in (1,2,3,8,24,25,60,123):
   jobs=self.jobs(n)
   for engine in (baseline,candidate):
    actual=[self.pack(engine,jobs,w,preview_indices=list(range(min(2,n))))for w in (1,4,14,20,40)]
    self.assertTrue(all(v==actual[0]for v in actual))
    self.assertEqual(actual[0][:min(2,n)],[[i]for i in range(min(2,n))])
    self.assertEqual(sorted(i for batch in actual[0]for i in batch),list(range(n)))
    self.assertTrue(all(len(v)<=2 for v in actual[0]))
   self.assertEqual(self.pack(baseline,jobs,14),self.pack(candidate,jobs,20))
 def test_image_caps_and_alternate_modes_remain_intact(self):
  jobs=self.jobs(12)
  for engine in (baseline,candidate):
   with patch.object(engine,'crop_runs',side_effect=lambda blocks:[None]*3),patch.object(engine,'TRANSPORT_BATCH_IMAGES',4):
    self.assertTrue(all(len(v)==1 for v in self.pack(engine,jobs,20,preview=False)))
   self.assertEqual(self.pack(engine,jobs,20,batch_units=1),[[i]for i in range(12)])
   with patch.object(engine,'TRANSPORT_BALANCED',False):
    self.assertEqual(self.pack(engine,jobs,1),self.pack(engine,jobs,20))

if __name__=='__main__':unittest.main()

class FrozenDeferralTests(unittest.TestCase):
 def test_completion_order_and_resume_never_assign_a_new_partner(self):
  for engine in (baseline,candidate):
   original=[[0],[1],[2,15],[3,14],[4,13],[5,12],[6,11],[7,10],[8,9]]
   for deferred in ([14,15,3,2],[3,2,15,14],[15,2,14,3],[14,2],[8,9,1]):
    actual=engine.transport_subset(original,deferred)
    self.assertEqual(sorted(i for b in actual for i in b),sorted(deferred))
    self.assertTrue(all(any(all(i in old for i in b)for old in original)for b in actual))
   self.assertEqual(engine.transport_subset(original,[14,15,3,2]),[[2,15],[3,14]])
   self.assertEqual(engine.transport_subset(original,[14,2]),[[2],[14]])
   with self.assertRaises(ValueError):engine.transport_subset(original,[2,2])
   with self.assertRaises(ValueError):engine.transport_subset(original,[99])
