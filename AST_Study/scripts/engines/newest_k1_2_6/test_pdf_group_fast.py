"""Offline checks: grouping-only tier selection, settlement and hard cap."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
import pdf_ai as ai
from audit_pdf_cost_metrics import request_metrics

class GroupFastTests(unittest.TestCase):
    def test_only_grouping_body_changes_and_body_tokens_stay_identical(self):
        with TemporaryDirectory() as tmp:
            for kind in ('region_plan', 'region_study', 'summary_reduce', 'tutor'):
                bodies=[]
                for tier in ('default','fast'):
                    send=Mock(return_value={'service_tier': tier if kind=='region_plan' else 'default',
                        'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],
                        'usage':{'prompt_tokens':1000,'completion_tokens':100,
                        'prompt_tokens_details':{'cached_tokens':200,'cache_write_tokens':300}}})
                    p=ai.Provider(Path(tmp)/f'{kind}-{tier}',True,1,transport=send,group_service_tier=tier)
                    p.context={'kind':kind}
                    p.complete({'task':'fixture'},max_output=100,system_prompt='fixture',cache_stable_prefix=True)
                    bodies.append(send.call_args.args[0])
                    e=p.ledger['requests'][0]
                    factor=2 if kind=='region_plan' and tier=='fast' else 1
                    expected=(800*.1+200*.01+100*.5+300*.025)/1e6*factor
                    self.assertAlmostEqual(e['estimatedUsd'],expected)
                    self.assertAlmostEqual(request_metrics(e)['usageBasedUsd'],expected)
                if kind=='region_plan':
                    self.assertEqual(bodies[0].pop('service_tier'),'default')
                    self.assertEqual(bodies[1].pop('service_tier'),'fast')
                else:
                    self.assertNotIn('service_tier',bodies[1])
                self.assertEqual(bodies[0],bodies[1])

    def test_downgrade_charges_standard_but_reserves_fast(self):
        with TemporaryDirectory() as tmp:
            send=Mock(return_value={'service_tier':'default',
                'choices':[{'finish_reason':'stop','message':{'content':'{}'}}],
                'usage':{'prompt_tokens':1000,'completion_tokens':100}})
            p=ai.Provider(Path(tmp),True,1,transport=send)
            p.context={'kind':'region_plan'}
            p.complete({'task':'fixture'},max_output=100)
            e=p.ledger['requests'][0]
            self.assertAlmostEqual(e['estimatedUsd'],.00015)
            self.assertEqual(e['billedServiceTier'],'default')
            self.assertAlmostEqual(e['reservedUsd'],(e['inputTokenBound']*.1+100*.5)*2/1e6)

    def test_fast_reservation_stops_before_network(self):
        with TemporaryDirectory() as tmp:
            send=Mock(side_effect=AssertionError('must not send'))
            p=ai.Provider(Path(tmp),True,.0005,transport=send)
            p.context={'kind':'region_plan'}
            with self.assertRaises(ai.BudgetExceeded):
                p.complete({'task':'fixture'},max_output=1000)
            send.assert_not_called()

if __name__=='__main__':unittest.main()
