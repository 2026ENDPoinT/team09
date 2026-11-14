"""Actual escaped-newline failure, meaningful output, receipts and quarantine."""
import io
import json
import unittest

import pdf_study_connection as net
from pdf_study_blank_loop import BlankLineRepetition
from pdf_study_repetition import source_spellings
from test_pdf_study_repetition import text_native
from test_pdf_k120_foreground_transport import request, missing
from test_pdf_study_connection import sse, created
from test_pdf_study_rejection import RejectedAttemptTests
from test_pdf_k120_optimization_provider import K120RepetitionProviderTests


class BlankLines(unittest.TestCase):
    def replay(self, text, size=1, sources=()):
        meter = BlankLineRepetition(sources)
        for start in range(0, len(text), size):
            if meter.feed(text[start:start + size]):
                break
        return meter

    def test_escape_spelling_and_chunk_boundaries_cannot_hide_loop(self):
        for pattern in (r'\u000a', r'\n', r'\r', r'\u000A \t'):
            raw = '{"text":"normal learner text' + pattern * 4000
            expected = self.replay(raw).match
            self.assertIsNotNone(expected)
            self.assertEqual(expected['blankLines'], 128)
            for size in (2, 7, 64, 4096):
                self.assertEqual(self.replay(raw, size).match, expected)

    def test_meaningful_code_math_and_literal_backslash_n_are_unbounded(self):
        values = [
            '문장이 길어도 내용이 이어지면 유지해요.\n' * 10000,
            '\n\n'.join('    result += value; // code %d' % n for n in range(5000)),
            ' '.join(r'\n \u000a \frac{x}{y}' for _ in range(4000)),
            ('line\n' * 2000).rstrip() + '\n' * 127 + 'next meaningful line',
        ]
        for text in values:
            self.assertFalse(self.replay(json.dumps({'text': text}), size=7).detected)

    def test_runs_do_not_combine_across_strings_or_keys(self):
        raw = json.dumps({'rows': [{'text': '\n' * 64}] * 300})
        self.assertFalse(self.replay(raw, size=4096).detected)

    def test_source_exact_blank_run_exempt_only_up_to_observed_length(self):
        body = {'input': [{'role': 'user', 'content': [{'type': 'input_text',
            'text': json.dumps({'blocks': [{'text': 'before\n' + '\n' * 255 + 'after'}]})}]}]}
        sources = source_spellings(body, minimum_chars=128)
        self.assertFalse(self.replay(json.dumps({'text': '\n' * 256}), sources=sources).detected)
        self.assertTrue(self.replay(json.dumps({'text': '\n' * 257}), sources=sources).detected)

    def run_stream(self, *, native_only=False, recover=True, enabled=True):
        self.calls = []; self.updates = []
        value = text_native('{"text":"' + r'\u000a' * 4000)
        events = [created(), ({'type': 'response.completed', 'response': value} if native_only else
            {'type': 'response.output_text.delta', 'item_id': 'msg', 'delta': value['output'][1]['content'][0]['text']})]
        def opener(req, timeout):
            self.calls.append(req.method)
            if req.method == 'POST':
                return sse(events)
            if not recover:
                raise missing(req)
            return io.StringIO(json.dumps(value))
        return net.request_once(request(), open_url=opener, foreground=True,
            reject_title_repetition=enabled, update=lambda **x: self.updates.append(x),
            sleep=lambda _: None)

    def test_live_and_terminal_paths_keep_native_usage_but_reject_bad_prose(self):
        for native_only in (False, True):
            result = self.run_stream(native_only=native_only)
            self.assertIsInstance(result, net.GuardedStudyResponse)
            self.assertEqual(result.reason, 'repeated_blank_lines')
            self.assertIsNone(result.value)
            self.assertIsInstance(result.native['usage'], dict)
            self.assertEqual(self.calls.count('POST'), 1)
            self.assertTrue(any(x.get('streamOutputAnomaly') == result.reason for x in self.updates))

    def test_missing_receipt_remains_unknown_and_does_not_become_a_free_result(self):
        with self.assertRaises(net.StudyConnectionError):
            self.run_stream(recover=False)
        self.assertEqual(self.calls.count('POST'), 1)
        self.assertTrue(any(x.get('clientStopReason') == 'repeated_blank_lines' for x in self.updates))

    def test_opt_out_does_not_change_other_delivery(self):
        result = self.run_stream(native_only=True, enabled=False)
        self.assertIsInstance(result, dict)
        self.assertEqual(self.calls, ['POST'])


class BlankLineQuarantine(RejectedAttemptTests):
    def setUp(self):
        super().setUp()
        self.entry['streamOutputAnomaly'] = 'repeated_blank_lines'
        self.save()


class BlankLineProvider(K120RepetitionProviderTests):
    LOOP = '{"text":"' + r'\u000a' * 4000
    REJECTION = 'repeated_blank_lines'


if __name__ == '__main__':
    unittest.main()
