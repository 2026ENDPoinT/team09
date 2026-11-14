"""Durable, offline recovery never silently repays an already-sent child."""
import copy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from pdf_ai import MissingPaidResponseError
from pdf_study_batch_recovery import BatchRecoveryError, BatchRecoveryIndex
from pdf_study_batch_transport import encode
from test_pdf_study_batch_transport import alias_reply, fixture, reply


class BatchRecoveryTests(unittest.TestCase):
    def test_desktop_cancelled_batch_can_resume_without_erasing_known_cost(self):
        self.entry.update(state='usage_unknown', cancellationDisposition='server_stopped', reservedUsd=.02)
        self.save();self.response_path.unlink()
        before=self.ledger_path.read_bytes()
        self.assertIsNone(self.index().recover(self.jobs[0]))
        self.assertEqual(before,self.ledger_path.read_bytes())

    def test_desktop_cancelled_batch_still_reuses_completed_peer(self):
        self.entry.update(state='usage_unknown', cancellationDisposition='server_stopped')
        self.save()
        raw,_=self.index().recover(self.jobs[0])
        self.assertEqual(raw,self.raw['u0'])

    def test_explicit_unresolved_retry_requires_lookup_and_valid_contract_preserves_original(self):
        self.entry['state']='reserved';self.save();self.response_path.unlink()
        before=self.ledger_path.read_bytes()
        index=self.index()
        with self.assertRaises(MissingPaidResponseError):
            index.recover(self.jobs[0],retry_missing_responses=True,retry_unresolved_request_ids={'other'})
        self.assertIsNone(index.recover(self.jobs[0],retry_missing_responses=True,
                                      retry_unresolved_request_ids={self.entry['requestId']}))
        self.assertEqual(before,self.ledger_path.read_bytes())
        Path(self.entry['studyBatchContract']).unlink()
        with self.assertRaises(MissingPaidResponseError):
            self.index().recover(self.jobs[0],retry_missing_responses=True,
                                 retry_unresolved_request_ids={self.entry['requestId']})

    def test_approved_unresolved_retry_still_reuses_completed_peer(self):
        self.entry['state']='reserved';self.save()
        raw,_=self.index().recover(self.jobs[0],retry_missing_responses=True,
                                  retry_unresolved_request_ids={self.entry['requestId']})
        self.assertEqual(raw,self.raw['u0'])

    def test_retry_flag_cannot_repack_or_repay_a_batch_with_unconfirmed_usage(self):
        self.entry['state']='failed_or_uncertain';self.save();self.response_path.unlink()
        with self.assertRaises(MissingPaidResponseError):
            self.index().recover(self.jobs[0],retry_missing_responses=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)/'document';self.folder.mkdir()
        self.units = [fixture(0, 0), fixture(1, 0)]
        self.jobs = [unit['job'] for unit in self.units]
        _, _, _, self.contract = encode(self.units, flat_defs=True)
        self.contract_path = self.folder/'generated'/'study'/'transport-contract.json'
        self.contract_path.parent.mkdir(parents=True)
        self.response_key = 'a'*64
        self.response_path = self.folder/'generated'/'paid-responses'/(self.response_key+'.json')
        self.response_path.parent.mkdir()
        self.ledger_path = self.folder/'usage'/'operation.json';self.ledger_path.parent.mkdir()
        self.entry = {'requestId': 'paid-once', 'state': 'settled', 'sentAtMs': 123,
            'kind': 'region_study', 'strategy': 'new-concept-v99', 'studyTeachingIdentity': 'same-teacher',
            'unitIds': [job['id'] for job in self.jobs], 'responseCacheKey': self.response_key,
            'studyBatchContract': str(self.contract_path)}
        self.raw = {f'u{i}': reply(unit) for i, unit in enumerate(self.units)}
        self.save()
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Recovery must stay offline'))
        self.network.start();self.addCleanup(self.network.stop)

    def save(self):
        self.contract_path.write_text(json.dumps(self.contract, ensure_ascii=False))
        self.response_path.write_text(json.dumps(self.raw, ensure_ascii=False))
        self.ledger_path.write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [self.entry]}))

    def index(self, **kwargs):
        return BatchRecoveryIndex(self.folder, self.jobs, 'gpt-6-luna', 'new-concept-v99', 'same-teacher', **kwargs)

    def test_valid_durable_peer_recovery_is_exact_and_reads_ledger_once(self):
        protected = {path: path.read_bytes() for path in (self.ledger_path, self.contract_path, self.response_path)}
        index = self.index()
        # Repeated per-job lookups must never reopen the usage ledger.
        original = Path.read_bytes;read_paths = []
        def observe(path): read_paths.append(path);return original(path)
        with patch.object(Path, 'read_bytes', observe):
            first, diagnostic = index.recover(self.jobs[0])
            second, _ = index.recover(self.jobs[1])
            first['concepts'][0]['title'] = 'returned copy only'
            again, _ = index.recover(self.jobs[0])
        self.assertEqual(again, self.raw['u0'])
        self.assertEqual(second, self.raw['u1'])
        self.assertEqual(diagnostic['additionalApiRequests'], 0)
        self.assertEqual(diagnostic['requestId'], 'paid-once')
        self.assertEqual(index.stats, {'ledgerFilesRead': 1, 'matchedPaidBatchRequests': 1,
            'matchedPaidSingleRequests': 0,
            'contractFilesRead': 1, 'responseFilesRead': 1})
        self.assertNotIn(self.ledger_path, read_paths)
        self.assertEqual(len(read_paths), 2)
        self.assertTrue(all(path.read_bytes() == data for path, data in protected.items()))

    def test_partial_response_preserves_good_peer_blocks_bad_child_and_allows_explicit_retry(self):
        self.raw['u1']['concepts'][0]['segments'][0]['blockIds'] = [self.jobs[0]['blocks'][0]['id']]
        self.save();index = self.index()
        first, diagnostic = index.recover(self.jobs[0])
        self.assertEqual(first, self.raw['u0'])
        self.assertTrue(diagnostic['transportErrors'])
        with self.assertRaises(MissingPaidResponseError) as caught:
            index.recover(self.jobs[1])
        self.assertEqual(caught.exception.batch_recovery_diagnostic['additionalApiRequests'], 0)
        self.assertIsNone(index.recover(self.jobs[1], retry_missing_responses=True))
        # A truthy string is not the existing explicit boolean retry approval.
        with self.assertRaises(MissingPaidResponseError):
            index.recover(self.jobs[1], retry_missing_responses='yes')
        self.assertEqual(index.recover(self.jobs[0], retry_missing_responses=True)[0], self.raw['u0'])

    def test_unknown_paid_hold_and_raw_or_incomplete_only_never_count_as_free(self):
        for state in ('reserved', 'usage_unknown', 'failed_or_uncertain'):
            with self.subTest(state=state):
                self.entry['state'] = state;self.save();self.response_path.unlink()
                self.response_path.with_suffix('.raw.json').write_text(json.dumps({'choices': []}))
                self.response_path.with_suffix('.incomplete.json').write_text(json.dumps({'finishReason': 'length'}))
                index = self.index()
                with self.assertRaises(MissingPaidResponseError): index.recover(self.jobs[0])
                with self.assertRaises(MissingPaidResponseError):
                    index.recover(self.jobs[0], retry_missing_responses=True)

    def test_not_sent_and_reserved_without_transmission_do_not_block(self):
        self.entry['state'] = 'not_sent';self.save()
        self.assertIsNone(self.index().recover(self.jobs[0]))
        self.entry['state'] = 'reserved';del self.entry['sentAtMs'];self.save()
        self.assertIsNone(self.index().recover(self.jobs[0]))

    def test_sent_legacy_singleton_is_indexed_once_without_reading_any_response(self):
        entry = {'requestId': 'old-single', 'state': 'failed_or_uncertain', 'sentAtMs': 123,
                 'kind': 'region_study', 'unitIds': [self.jobs[0]['id']]}
        self.ledger_path.write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [entry]}))
        index = self.index()
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('The ledger is already indexed')):
            for _ in range(5):
                self.assertTrue(index.single_history(self.jobs[0]))
                self.assertFalse(index.single_history(self.jobs[1]))
                self.assertIsNone(index.recover(self.jobs[0]))
        self.assertEqual(index.stats['ledgerFilesRead'], 1)
        self.assertEqual(index.stats['matchedPaidSingleRequests'], 1)
        self.assertEqual(index.stats['contractFilesRead'], 0)
        self.assertEqual(index.stats['responseFilesRead'], 0)
        changed = copy.deepcopy(self.jobs[0]);changed['blocks'][0]['text'] += 'different'
        with self.assertRaises(BatchRecoveryError):index.single_history(changed)

    def test_singleton_not_sent_unsent_reserved_and_explicit_different_contracts_are_excluded(self):
        original = {**self.entry, 'requestId': 'single', 'unitIds': [self.jobs[0]['id']]}
        for mutation in ('not_sent', 'unsent_reserved', 'other_identity', 'other_strategy', 'other_kind', 'other_model'):
            with self.subTest(mutation=mutation):
                entry = copy.deepcopy(original);model = 'gpt-6-luna'
                if mutation == 'not_sent':entry['state'] = 'not_sent'
                if mutation == 'unsent_reserved':entry['state'] = 'reserved';del entry['sentAtMs']
                if mutation == 'other_identity':entry['studyTeachingIdentity'] = 'new-teacher'
                if mutation == 'other_strategy':entry['strategy'] = 'other-strategy'
                if mutation == 'other_kind':entry['kind'] = 'summary_reduce'
                if mutation == 'other_model':model = 'other-model'
                self.ledger_path.write_text(json.dumps({'model': model, 'requests': [entry]}))
                self.assertFalse(self.index().single_history(self.jobs[0]))
        for state in ('reserved', 'settled', 'usage_unknown', 'failed_or_uncertain'):
            entry = {**original, 'state': state}
            self.ledger_path.write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [entry]}))
            self.assertTrue(self.index().single_history(self.jobs[0]))

    def test_valid_batch_recovery_remains_available_when_a_unit_also_has_single_history(self):
        single = {**self.entry, 'requestId': 'older-single', 'unitIds': [self.jobs[0]['id']],
                  'sentAtMs': 100, 'state': 'usage_unknown'}
        single.pop('studyTeachingIdentity')
        self.ledger_path.write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [single, self.entry]}))
        index = self.index()
        self.assertTrue(index.single_history(self.jobs[0]))
        self.assertFalse(index.single_history(self.jobs[1]))
        for i, job in enumerate(self.jobs):
            recovered, diagnostic = index.recover(job)
            self.assertEqual(recovered, self.raw[f'u{i}'])
            self.assertEqual(diagnostic['requestId'], 'paid-once')
        self.assertEqual(index.stats['ledgerFilesRead'], 1)
        self.assertEqual(index.stats['matchedPaidSingleRequests'], 1)
        self.assertEqual(index.stats['matchedPaidBatchRequests'], 1)

    def test_new_explicit_identity_model_or_strategy_is_not_same_paid_work(self):
        for field, value in (('studyTeachingIdentity', 'new-teacher'), ('strategy', 'different-strategy')):
            with self.subTest(field=field):
                old = self.entry[field];self.entry[field] = value;self.save()
                self.assertIsNone(self.index().recover(self.jobs[0]))
                self.entry[field] = old
        self.save()
        self.ledger_path.write_text(json.dumps({'model': 'other-model', 'requests': [self.entry]}))
        self.assertIsNone(self.index().recover(self.jobs[0]))

    def test_missing_legacy_contract_identity_or_key_blocks_until_explicit_retry(self):
        original = copy.deepcopy(self.entry)
        for field in ('studyBatchContract', 'studyTeachingIdentity', 'responseCacheKey'):
            with self.subTest(field=field):
                self.entry = copy.deepcopy(original);del self.entry[field];self.save()
                index = self.index()
                with self.assertRaises(MissingPaidResponseError): index.recover(self.jobs[0])
                self.assertIsNone(index.recover(self.jobs[0], retry_missing_responses=True))

    def test_path_escape_relative_contract_and_response_key_are_rejected_without_outside_read(self):
        original = copy.deepcopy(self.entry)
        outside = Path(self.tmp.name)/'outside.json';outside.write_text(json.dumps(self.contract))
        candidates = [('studyBatchContract', str(outside)), ('studyBatchContract', 'generated/relative.json'),
                      ('responseCacheKey', '../outside'), ('responseCacheKey', 'A'*64),
                      ('responseCacheKey', 'a'*63)]
        for field, value in candidates:
            with self.subTest(field=field, value=value):
                self.entry = copy.deepcopy(original);self.entry[field] = value;self.save();index = self.index()
                read_paths = [];read_bytes = Path.read_bytes
                def observe(path): read_paths.append(path);return read_bytes(path)
                with patch.object(Path, 'read_bytes', observe), self.assertRaises(MissingPaidResponseError):
                    index.recover(self.jobs[0])
                self.assertNotIn(outside, read_paths)
        self.entry = copy.deepcopy(original);self.save()
        self.contract_path.unlink();self.contract_path.symlink_to(outside)
        with self.assertRaises(MissingPaidResponseError): self.index().recover(self.jobs[0])
        self.contract_path.unlink();self.save()
        self.response_path.unlink();self.response_path.symlink_to(outside)
        with self.assertRaises(MissingPaidResponseError): self.index().recover(self.jobs[0])

    def test_canonical_enum_full_schema_and_ledger_unit_order_must_match_exactly(self):
        original = copy.deepcopy(self.contract)
        original_entry = copy.deepcopy(self.entry)
        for mutation in ('enum', 'source_order', 'schema_relaxed', 'job_id', 'ledger_order'):
            with self.subTest(mutation=mutation):
                self.contract = copy.deepcopy(original);self.entry = copy.deepcopy(original_entry)
                unit = self.contract['units'][0]
                if mutation == 'enum':unit['schema']['$defs']['studySourceId']['enum'] = ['other-source']
                if mutation == 'source_order':unit['sourceIds'].reverse()
                if mutation == 'schema_relaxed':unit['schema']['additionalProperties'] = True
                if mutation == 'job_id':unit['jobId'] = 'other-job'
                if mutation == 'ledger_order':self.entry['unitIds'].reverse()
                self.save()
                with self.assertRaises(MissingPaidResponseError): self.index().recover(self.jobs[0])

    def test_mutating_current_job_or_using_unknown_peer_cannot_rebind_saved_sources(self):
        index = self.index();changed = copy.deepcopy(self.jobs[0]);changed['blocks'][0]['text'] += 'different'
        with self.assertRaises(BatchRecoveryError): index.recover(changed)
        index = BatchRecoveryIndex(self.folder, self.jobs[:1], 'gpt-6-luna', 'new-concept-v99', 'same-teacher')
        with self.assertRaises(MissingPaidResponseError): index.recover(self.jobs[0])

    def test_ambiguous_duplicate_paid_request_binding_cannot_choose_favorable_history(self):
        other = copy.deepcopy(self.entry);other['responseCacheKey'] = 'b'*64
        (self.folder/'usage'/'ambiguous.json').write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [other]}))
        with self.assertRaises(MissingPaidResponseError): self.index().recover(self.jobs[0])
        # Restoring the first binding in a third snapshot cannot erase ambiguity.
        self.ledger_path.write_text(json.dumps({'model': 'gpt-6-luna',
            'requests': [self.entry, other, {**self.entry, 'sentAtMs': 999}]}))
        with self.assertRaises(MissingPaidResponseError): self.index().recover(self.jobs[0])

    def test_later_failed_attempt_does_not_erase_a_previous_good_paid_reply(self):
        later = {**self.entry, 'requestId': 'explicit-later-attempt', 'state': 'failed_or_uncertain',
                 'sentAtMs': 456, 'responseCacheKey': 'b'*64}
        (self.folder/'usage'/'later.json').write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [later]}))
        index = self.index()
        value, diagnostic = index.recover(self.jobs[0])
        self.assertEqual(value, self.raw['u0'])
        self.assertEqual(diagnostic['requestId'], 'paid-once')
        self.assertEqual(diagnostic['additionalApiRequests'], 0)

    def test_current_schema_variant_requires_its_exact_original_saved_contract(self):
        variant = copy.deepcopy(self.units[0]['response_format'])
        variant['json_schema']['schema']['properties']['uncertainBlocks']['maxItems'] = 0
        index = self.index(response_format=variant)
        with self.assertRaises(MissingPaidResponseError): index.recover(self.jobs[0])
        for unit in self.units:unit['response_format'] = variant
        self.contract = encode(self.units, flat_defs=True)[3]
        self.save()
        self.assertEqual(self.index(response_format=variant).recover(self.jobs[0])[0], self.raw['u0'])

    def test_saved_alias_wire_restores_exact_canonical_peer_before_normal_validation(self):
        canonical = copy.deepcopy(self.raw)
        self.contract = encode(self.units, alias_pool_size=32, flat_defs=True)[3]
        self.raw = {f'u{i}': alias_reply(canonical[f'u{i}'], owner['aliases'])
                    for i, owner in enumerate(self.contract['units'])}
        self.save();index = self.index()
        self.assertEqual(index.recover(self.jobs[0])[0], canonical['u0'])
        self.assertEqual(index.recover(self.jobs[1])[0], canonical['u1'])
        self.raw['u1']['concepts'][0]['segments'][0]['blockIds'] = ['ubaaf']
        self.save();index = self.index()
        self.assertEqual(index.recover(self.jobs[0])[0], canonical['u0'])
        with self.assertRaises(MissingPaidResponseError):index.recover(self.jobs[1])

    def test_exact_alias_contract_recovers_without_introducing_any_unused_source(self):
        canonical = copy.deepcopy(self.raw)
        self.contract = encode(self.units, alias_pool_size='exact', flat_defs=True)[3]
        self.raw = {f'u{i}': alias_reply(canonical[f'u{i}'], owner['aliases'])
                    for i, owner in enumerate(self.contract['units'])}
        self.save();index = self.index()
        for i, job in enumerate(self.jobs):
            self.assertEqual(index.recover(job)[0], canonical[f'u{i}'])
            owner = self.contract['units'][i]
            self.assertEqual(owner['wireSchema']['$defs']['studySourceId']['enum'], list(owner['aliases']))

    def test_native_commentary_then_final_recovers_two_strict_peers_before_bad_parsed_cache(self):
        from test_pdf_responses_transport import native
        value = native()
        value['output'] = [
            {'type': 'message', 'role': 'assistant', 'phase': 'commentary',
             'content': [{'type': 'output_text', 'text': '{"u0": "unfinished'}]},
            {'type': 'message', 'role': 'assistant', 'phase': 'final_answer',
             'content': [{'type': 'output_text', 'text': json.dumps(self.raw, ensure_ascii=False)}]}]
        native_path = self.response_path.with_suffix('.responses.raw.json')
        native_path.write_text(json.dumps(value, ensure_ascii=False))
        self.response_path.write_text('{"u0": "old broken concatenation"')
        protected = {path: path.read_bytes() for path in (self.response_path, native_path, self.contract_path, self.ledger_path)}
        index = self.index()
        for i, job in enumerate(self.jobs):
            recovered, diagnostic = index.recover(job)
            self.assertEqual(recovered, self.raw[f'u{i}'])
            self.assertEqual(diagnostic['paidResponseSource'], 'responses_native')
            self.assertEqual(diagnostic['additionalApiRequests'], 0)
        self.assertEqual(index.stats['responseFilesRead'], 1)
        self.assertTrue(all(path.read_bytes() == original for path, original in protected.items()))

    def test_ambiguous_native_final_blocks_favorable_parsed_cache_and_native_path_escape(self):
        from test_pdf_responses_transport import native
        value = native();final = {'type': 'message', 'role': 'assistant', 'phase': 'final_answer',
            'content': [{'type': 'output_text', 'text': json.dumps(self.raw)}]}
        value['output'] = [final, copy.deepcopy(final)]
        native_path = self.response_path.with_suffix('.responses.raw.json')
        native_path.write_text(json.dumps(value))
        with self.assertRaises(MissingPaidResponseError):self.index().recover(self.jobs[0])
        outside = Path(self.tmp.name)/'native-outside.json';outside.write_text(json.dumps(value))
        native_path.unlink();native_path.symlink_to(outside)
        with self.assertRaises(MissingPaidResponseError):self.index().recover(self.jobs[0])

    def test_duplicate_json_keys_in_contract_fail_while_other_response_peer_survives(self):
        self.contract_path.write_text('{"version":"bad","version":"other","units":[]}')
        with self.assertRaises(MissingPaidResponseError): self.index().recover(self.jobs[0])
        self.save()
        first = json.dumps(self.raw['u0']);second = json.dumps(self.raw['u1'])
        self.response_path.write_text('{"u0":'+first+',"u1":'+second+',"u1":'+second+'}')
        index = self.index()
        self.assertEqual(index.recover(self.jobs[0])[0], self.raw['u0'])
        with self.assertRaises(MissingPaidResponseError): index.recover(self.jobs[1])


if __name__ == '__main__':
    unittest.main()
