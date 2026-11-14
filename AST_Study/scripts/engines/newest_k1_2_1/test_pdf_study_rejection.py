"""Offline rejected-attempt receipts preserve billing without reviving bad prose."""
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from pdf_study_rejection import mark_rejected,is_rejected,rejected_entry
from pdf_k120_control import ForegroundControl
from pdf_study_receipts import reconcile
from pdf_study_hedge import recover_cached
from test_pdf_responses_transport import native,FORMAT


class RejectedAttemptTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.folder=Path(temp.name)
        self.cache=self.folder/'generated/paid-responses'/('a'*64+'.json')
        self.cache.parent.mkdir(parents=True)
        self.logical=self.cache.with_name('b'*64+'.json')
        self.sibling=self.cache.with_name('c'*64+'.json')
        self.entry={'requestId':'d'*32,'responseId':'resp_fixture','state':'usage_unknown',
            'responseCacheKey':self.cache.stem,'logicalResponseCacheKey':self.logical.stem,
            'reservedUsd':.1,'sentAtMs':1,'kind':'region_study','inputApi':'responses',
            'unitIds':['unit'],'streamOutputAnomaly':'repeated_short_field'}
        self.ledger_path=self.folder/'usage/current.json';self.ledger_path.parent.mkdir()
        self.provider=SimpleNamespace(folder=self.folder,_lock=threading.RLock(),spent=.1,key='fixture',
            model='gpt-6-luna',ledger={'operationId':'current','model':'gpt-6-luna','requests':[self.entry]},
            ledger_path=self.ledger_path,settle_credits=Mock(),billing=None,transport=None,study_recovery_window=3)
        self.save()

    def save(self):self.ledger_path.write_text(json.dumps(self.provider.ledger))

    def test_marker_binds_only_its_private_attempt_and_survives_restart(self):
        marker=mark_rejected(self.cache,self.entry)
        self.assertEqual(set(marker),{'version','cacheKey','requestId','responseId','reason'})
        self.assertTrue(is_rejected(self.cache))
        self.assertFalse(is_rejected(self.logical,self.entry))
        self.assertFalse(is_rejected(self.sibling,self.entry))
        with self.assertRaises(ValueError):mark_rejected(self.sibling,self.entry)
        with self.assertRaises(ValueError):mark_rejected(self.cache,self.entry,'timeout')
        self.assertFalse(rejected_entry({'errorType':'StudyConnectionError'}))

    def test_mismatched_or_damaged_marker_never_rejects_another_key(self):
        mark_rejected(self.cache,self.entry)
        marker=self.cache.with_suffix('.delivery-rejected.json')
        self.sibling.with_suffix('.delivery-rejected.json').write_bytes(marker.read_bytes())
        self.assertFalse(is_rejected(self.sibling))
        marker.write_text('{interrupted write')
        self.assertTrue(is_rejected(self.cache))
        self.assertFalse(is_rejected(self.logical))

    def test_stop_receipt_keeps_native_and_settles_once_without_parsed_success(self):
        self.logical.write_text('{"winner":"unchanged"}')
        control=ForegroundControl(self.provider,self.entry,self.cache,
            schema=FORMAT['json_schema']['schema'])
        self.assertTrue(control._preserve(native()))
        first=self.provider.spent
        self.assertEqual(self.entry['state'],'settled')
        self.assertTrue(self.entry['foregroundStopResultRejected'])
        self.assertTrue(self.cache.with_suffix('.responses.raw.json').exists())
        self.assertFalse(self.cache.exists())
        self.assertEqual(json.loads(self.logical.read_text()),{'winner':'unchanged'})
        self.assertTrue(is_rejected(self.cache))
        control._preserve(native())
        self.assertEqual(self.provider.spent,first)
        self.assertAlmostEqual(self.entry['estimatedUsd'],first)

    def test_receipt_get_settles_usage_but_never_returns_a_reusable_unit(self):
        calls=[]
        def opener(request,timeout):
            calls.append(request.method)
            return io.StringIO(json.dumps(native()))
        results=reconcile(self.provider,open_url=opener)
        self.assertEqual(calls,['GET'])
        self.assertEqual(results[0]['unitIds'],[])
        self.assertEqual(results[0]['additionalGenerations'],0)
        self.assertEqual(self.entry['state'],'settled')
        self.assertTrue(self.entry['recoveredOriginalResultRejected'])
        self.assertTrue(self.cache.with_suffix('.responses.raw.json').exists())
        self.assertTrue(self.cache.with_suffix('.raw.json').exists())
        self.assertFalse(self.cache.exists())
        self.assertAlmostEqual(self.provider.spent,self.entry['estimatedUsd'])
        self.provider.settle_credits.assert_called_once()
        reconcile(self.provider,open_url=Mock(side_effect=AssertionError('Already settled')))
        self.provider.settle_credits.assert_called_once()

    def test_anomaly_arriving_during_receipt_get_cannot_create_parsed_cache(self):
        self.entry.pop('streamOutputAnomaly');self.save()
        def opener(request,timeout):
            # Simulate the original streaming thread while this GET is pending.
            self.entry['streamOutputAnomaly']='repeated_short_field'
            mark_rejected(self.cache,self.entry)
            return io.StringIO(json.dumps(native()))
        results=reconcile(self.provider,open_url=opener)
        self.assertEqual(results[0]['unitIds'],[])
        self.assertFalse(self.cache.exists())
        self.assertEqual(self.entry['state'],'settled')

    def test_normal_receipt_still_restores_the_original_body(self):
        self.entry.pop('streamOutputAnomaly');self.save()
        results=reconcile(self.provider,open_url=lambda request,timeout:io.StringIO(json.dumps(native())))
        self.assertEqual(results[0]['unitIds'],['unit'])
        self.assertEqual(json.loads(self.cache.read_text()),{'ok':True})
        self.assertFalse(is_rejected(self.cache))

    def test_hedge_recovery_skips_bad_private_result_and_uses_valid_sibling(self):
        self.cache.write_text('{"ok":false}')
        self.sibling.write_text('{"ok":true}')
        mark_rejected(self.cache,self.entry)
        good={**self.entry,'requestId':'e'*32,'responseId':'resp_good',
            'responseCacheKey':self.sibling.stem}
        good.pop('streamOutputAnomaly')
        self.provider.ledger['requests'].append(good);self.save()
        value=recover_cached(self.provider,self.logical,FORMAT)
        self.assertEqual(value,{'ok':True})
        self.assertEqual(json.loads(self.logical.read_text()),{'ok':True})
        self.assertEqual(json.loads(self.cache.read_text()),{'ok':False})

    def test_batch_recovery_rejects_bad_native_but_keeps_an_older_valid_reply(self):
        from test_pdf_study_batch_recovery import BatchRecoveryTests
        from pdf_ai import MissingPaidResponseError
        fixture=BatchRecoveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.entry['deliveryViolation']='repeated_short_field';fixture.save()
        mark_rejected(fixture.response_path,fixture.entry)
        server=native();server['output'][1]['content']=[{'type':'output_text','text':json.dumps(fixture.raw)}]
        fixture.response_path.with_suffix('.responses.raw.json').write_text(json.dumps(server))
        with self.assertRaises(MissingPaidResponseError):fixture.index().recover(fixture.jobs[0])
        good=copy.deepcopy(fixture.entry);good.pop('deliveryViolation')
        good.update(requestId='older-valid',sentAtMs=122,responseCacheKey='f'*64)
        fixture.response_path.with_name(good['responseCacheKey']+'.json').write_text(json.dumps(fixture.raw))
        fixture.ledger_path.write_text(json.dumps({'model':'gpt-6-luna','requests':[fixture.entry,good]}))
        raw,diagnostic=fixture.index().recover(fixture.jobs[0])
        self.assertEqual(raw,fixture.raw['u0'])
        self.assertEqual(diagnostic['requestId'],'older-valid')


if __name__=='__main__':unittest.main()
