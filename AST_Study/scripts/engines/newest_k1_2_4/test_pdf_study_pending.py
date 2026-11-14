import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pdf_study_pending import pending_originals, retry_original_ids


class PendingStudyTests(unittest.TestCase):
    def test_terminal_truncated_pairs_split_to_singles_and_finish(self):
        import pdf_ai as ai
        import test_pdf_speed_pipeline as fixture
        f=fixture.CropPipelineTests('test_first_request_starts_before_all_local_crops_finish')
        f.setUp();self.addCleanup(f.doCleanups);f.set_unit_count(6)
        calls=[]
        def complete(payload,**kwargs):
            calls.append(payload['task'])
            if payload['task']=='region_teaching_batch':
                raise ai.IncompleteResponseError('fixture: terminal output limit')
            return f.reply(payload['blocks'][0]['id'])
        result,_=f.run_pipeline(lambda _:None,complete=complete,
            crop_result=lambda blocks:([],[]),
            wire_options={'TRANSPORT_BATCH_UNITS':2,'TRANSPORT_BATCH_IMAGES':8})
        self.assertTrue(result['processingComplete'])
        self.assertEqual(calls.count('region_teaching_batch'),2)
        self.assertEqual(calls.count('region_teaching'),6)

    def test_scope_count_preserves_unknown_cost_and_never_changes_ledgers(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'usage').mkdir()
            entries=[{'requestId':str(i),'kind':'region_study','state':state,
                      'sentAtMs':1,'unitIds':units,'reservedUsd':.02}
                     for i,(state,units) in enumerate([
                         ('reserved',['a','b']),('settled',['b']),
                         ('usage_unknown',['b']),('reserved',['outside']),('not_sent',['a'])])]
            path=folder/'usage/old.json'
            path.write_text(json.dumps({'model':'gpt-6-luna','requests':entries}))
            before=path.read_bytes()
            value=pending_originals(folder,'gpt-6-luna',['a','b'])
            self.assertEqual(value['requests'],2)
            self.assertAlmostEqual(value['reservedUsd'],.04)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(pending_originals(folder,'other',['a'])['requests'],0)

    def test_replacement_links_only_its_own_originals(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'usage').mkdir()
            (folder/'usage/old.json').write_text(json.dumps({'model':'gpt-6-luna','requests':[
                {'requestId':'pair','unitIds':['a','b']},
                {'requestId':'outside','unitIds':['z']},
                {'requestId':'replacement','unitIds':['a'],'unresolvedRetryApproved':True}]}))
            provider=SimpleNamespace(folder=folder,model='gpt-6-luna',context={'unitIds':['a']},
                unavailable_study_request_ids={'pair','outside','replacement'})
            self.assertEqual(retry_original_ids(provider,{'hash'}),['pair'])

    def test_corrupt_ledger_is_reported_without_treating_it_as_no_cost(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'usage').mkdir()
            (folder/'usage/broken.json').write_text('{')
            self.assertEqual(pending_originals(folder,'gpt-6-luna',['a'])['unreadableLedgers'],1)


if __name__=='__main__':unittest.main()
