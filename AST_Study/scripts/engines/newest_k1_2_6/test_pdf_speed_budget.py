"""Incremental experiment budget boundaries; synthetic ledgers only."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from audit_pdf_speed import current_budget

class IncrementalBudgetTests(unittest.TestCase):
    def test_prior_request_stays_excluded_even_if_it_settles_after_reset(self):
        with TemporaryDirectory() as d:
            root=Path(d);checkpoint=root/'checkpoint.json'
            checkpoint.write_text(json.dumps({'preexistingRequestIds':['old']}))
            usage=root/'runs/case/variant/usage';usage.mkdir(parents=True)
            ledger=usage/'ledger.json'
            for state in ('reserved','settled'):
                ledger.write_text(json.dumps({'requests':[
                    {'requestId':'old','state':state,'reservedUsd':.2,'estimatedUsd':.1},
                    {'requestId':'new','state':'settled','estimatedUsd':.03}]}))
                self.assertEqual(current_budget(root,checkpoint),{'actualUsd':.03,
                    'uncertainReservedUsd':0,'committedUsd':.03,'requests':1})

    def test_unknown_cost_is_reserved_not_sent_is_zero_and_copies_are_deduplicated(self):
        with TemporaryDirectory() as d:
            root=Path(d);checkpoint=root/'checkpoint.json'
            checkpoint.write_text(json.dumps({'preexistingRequestIds':[]}))
            values=[{'requestId':'paid','state':'reserved','reservedUsd':.1},
                    {'requestId':'unknown','state':'failed_or_uncertain','reservedUsd':.04},
                    {'requestId':'never','state':'not_sent','reservedUsd':.5}]
            for name,rows in [('a',values),('b',[{'requestId':'paid','state':'settled','estimatedUsd':.02}])]:
                folder=root/name/'usage';folder.mkdir(parents=True)
                (folder/'ledger.json').write_text(json.dumps({'requests':rows}))
            result=current_budget(root,checkpoint)
            self.assertEqual(result['requests'],2)
            self.assertEqual(result['actualUsd'],.02)
            self.assertEqual(result['uncertainReservedUsd'],.04)
            self.assertAlmostEqual(result['committedUsd'],.06)

if __name__=='__main__':unittest.main()
