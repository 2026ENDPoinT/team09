"""Offline measured-prefix bounds; no model/tokenizer or paid requests."""
import copy
import unittest

from pdf_k120_token_admission import FixedPrefixAdmission, prefix_metadata


class FixedPrefixAdmissionTest(unittest.TestCase):
    def estimator(self, rows, **options):
        values = dict(model='gpt-6-luna', instructions='한' * 10000,
                      final_delivery='Final delivery contract', input_bound=50000,
                      records=lambda: rows)
        values.update(options)
        return FixedPrefixAdmission(**values)

    def sample(self, total=9000, **overrides):
        row = dict(prefix_metadata(model='gpt-6-luna', instructions='한' * 10000,
                                   final_delivery='Final delivery contract'),
                   requestId='confirmed', state='settled', strategy='newest-k1-2-5',
                   kind='region_study', inputApi='responses',
                   studyForegroundResponses=True, serverTerminalStatus='completed',
                   finishReason='stop', usage={'prompt_tokens': total,
                       'prompt_tokens_details': {'cached_tokens': 8900}})
        row.update(overrides)
        return row

    def test_cold_request_keeps_original_bound(self):
        estimate = self.estimator([])
        self.assertEqual(estimate.input_tokens(), 50000)
        self.assertEqual(estimate.metadata['tokenAdmissionConfirmedSamples'], 0)

    def test_only_fixed_bytes_replaced_and_cached_input_not_subtracted(self):
        row = self.sample(); before = copy.deepcopy(row)
        estimate = self.estimator([row])
        self.assertEqual(estimate.input_tokens(), 50000 - 30000 + 11250 + 256)
        self.assertEqual(estimate.metadata['tokenAdmissionEvidenceRequestId'], 'confirmed')
        self.assertEqual(row, before)
        # Every byte added to source/schema/image bounds survives calibration.
        self.assertEqual(self.estimator([row], input_bound=70000).input_tokens()
                         - estimate.input_tokens(), 20000)

    def test_late_completed_receipt_updates_waiting_estimate(self):
        rows = [self.sample(state='reserved', usage=None)]
        estimate = self.estimator(rows)
        self.assertEqual(estimate.input_tokens(), 50000)
        rows[0].update(state='settled', usage={'input_tokens': 9001})
        self.assertEqual(estimate.input_tokens(), 20000 + 11252 + 256)
        rows.append(self.sample(8000, requestId='smaller-confirmed'))
        self.assertEqual(estimate.input_tokens(), 30256)
        self.assertEqual(estimate.metadata['tokenAdmissionConfirmedSamples'], 2)

    def test_incomplete_unknown_other_version_and_other_transport_cannot_calibrate(self):
        overrides = [dict(state='unknown'), dict(state='reserved'), dict(usage=None),
            dict(strategy='newest-k1-1-3'), dict(kind='region_plan'),
            dict(inputApi='chat'), dict(studyForegroundResponses=False),
            dict(serverTerminalStatus='incomplete'), dict(serverTerminalStatus=None),
            dict(finishReason='length'), dict(responseStatus='cancelled')]
        for override in overrides:
            with self.subTest(override=override):
                self.assertEqual(self.estimator([self.sample(**override)]).input_tokens(), 50000)

    def test_exact_model_all_instruction_text_and_delivery_contract_are_required(self):
        row = self.sample()
        for options in [dict(model='gpt-6-luna-snapshot'), dict(instructions='한' * 9999),
                        dict(final_delivery='Other final contract')]:
            with self.subTest(options=options):
                self.assertEqual(self.estimator([row], **options).input_tokens(), 50000)

    def test_invalid_usage_and_untrusted_schema_values_are_ignored(self):
        for value in (True, 0, -1, 9000.0, '9000', None):
            with self.subTest(value=value):
                self.assertEqual(self.estimator([self.sample(value)]).input_tokens(), 50000)
        for key in ('tokenAdmissionPolicy', 'tokenAdmissionFixedBytes', 'tokenAdmissionPrefixSha'):
            row = self.sample(); row[key] = 'changed'
            self.assertEqual(self.estimator([row]).input_tokens(), 50000)

    def test_larger_receipt_never_increases_or_reduces_variable_bound(self):
        self.assertEqual(self.estimator([self.sample(50000)]).input_tokens(), 50000)
        self.assertEqual(self.estimator([self.sample()], input_bound=100).input_tokens(), 100)

    def test_failed_local_snapshot_falls_back_without_network(self):
        def broken():
            raise OSError('local read unavailable')
        self.assertEqual(self.estimator([], records=broken).input_tokens(), 50000)


if __name__ == '__main__':
    unittest.main()
