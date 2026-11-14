import unittest
from pdf_study_timings import unit_timings


class UnitTimingsTests(unittest.TestCase):
    def test_shared_latency_failure_retry_and_reuse_are_not_divided_or_fabricated(self):
        jobs=[{'id':str(i),'title':'unit '+str(i),'blocks':[{'page':i+1}]} for i in range(4)]
        requests=[{'requestId':'pair','kind':'region_study','unitIds':['0','1'],'latencySeconds':60.603},
                  {'requestId':'retry','kind':'region_study','unitIds':['0'],'latencySeconds':4},
                  {'requestId':'other','kind':'region_plan','unitIds':['0'],'latencySeconds':200}]
        rows=unit_timings(jobs,{0:{},2:{}},[{'unitId':'1'}],{'requests':requests})
        self.assertEqual(rows[0]['requestSeconds'],64.603)
        self.assertEqual(rows[1]['requestSeconds'],60.603)
        self.assertTrue(rows[0]['sharedRequest']);self.assertEqual(rows[1]['status'],'failed')
        self.assertEqual(rows[2]['status'],'reused');self.assertNotIn('requestSeconds',rows[2])
        self.assertEqual(rows[3]['status'],'pending');self.assertNotIn('requestSeconds',rows[3])
        self.assertEqual(unit_timings(jobs,{2:{}},[],{},local_units={2})[2]['status'],'local')

    def test_invalid_or_missing_measurements_stay_unknown(self):
        job={'id':'a','title':'A','blocks':[{'page':1}]}
        for bad in [None,float('nan'),-1,True]:
            row=unit_timings([job],{},[],{'requests':[{'kind':'region_study','unitIds':['a'],'latencySeconds':bad}]})[0]
            self.assertNotIn('requestSeconds',row)


if __name__=='__main__':unittest.main()
