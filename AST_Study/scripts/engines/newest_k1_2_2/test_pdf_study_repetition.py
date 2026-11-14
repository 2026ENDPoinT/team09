"""Offline short-field loops, source exceptions, and native receipt handling."""
import io
import json
import unittest
import urllib.error

import pdf_study_connection as net
from pdf_study_repetition import ShortFieldRepetition, source_spellings
from test_pdf_k120_foreground_transport import request, missing
from test_pdf_responses_transport import native
from test_pdf_study_connection import sse, created
from test_pdf_study_idle_watch import LiveStream


def text_native(text, status='completed'):
    value = native()
    value['status'] = status
    value['output'][1]['content'][0]['text'] = text
    return value


class ShortFieldRepetitionTests(unittest.TestCase):
    def replay(self, text, size=2, sources=()):
        meter = ShortFieldRepetition(sources)
        for start in range(0, len(text), size):
            meter.feed(text[start:start+size])
        return meter

    def test_both_observed_escape_loops_match_across_arbitrary_chunks(self):
        for pattern in (r'\raud1', r'\u000a0'):
            text = '{"concepts":[{"title":"' + pattern * 2000
            expected = self.replay(text).match
            self.assertIsNotNone(expected)
            self.assertGreaterEqual(expected['repeatedChars'], 1024)
            self.assertGreaterEqual(expected['minimumCycles'], 64)
            for size in (1, 7, 64, 4096):
                self.assertEqual(self.replay(text, size).match, expected)

    def test_only_short_fields_and_single_string_values_are_scanned(self):
        values = [
            {'title': '보통 제목', 'text': '0' * 4096},
            {'name': '합의 표기', 'formula': 'x+' * 2048},
            {'sourceCoverage': [{'title': '반복되는 짧은 제목'}] * 2000},
            {'text': 'literal "title":"' + 'a' * 4096},
            {'title': 'x' * 1023},
            {'name': 'abcdefghijklmnopqrstuvwxyz1234567' * 200},
        ]
        for value in values:
            self.assertFalse(self.replay(json.dumps(value, ensure_ascii=False)).detected)
        self.assertTrue(self.replay(json.dumps({'name': 'x' * 1024})).detected)
        self.assertTrue(self.replay('{"ti\\u0074le":"' + 'x' * 1024).detected)

    def test_longer_period_requires_sixty_four_cycles(self):
        pattern = 'abcdefghijklmnopqrstuvwxyz123456'
        self.assertEqual(len(pattern), 32)
        self.assertFalse(self.replay(json.dumps({'title': pattern * 63})).detected)
        self.assertTrue(self.replay(json.dumps({'title': pattern * 64})).detected)

    def test_exact_source_copy_is_exempt_but_overrun_or_new_prefix_is_not(self):
        source = 'x' * 1500
        body = {'input': [{'role': 'user', 'content': [{'type': 'input_text',
            'text': json.dumps({'blocks': [{'text': 'before ' + source + ' after'}]})}]}]}
        sources = source_spellings(body)
        meter = self.replay(json.dumps({'title': source}), sources=sources)
        self.assertFalse(meter.detected)
        self.assertGreater(meter.source_exempt_checks, 0)
        self.assertTrue(self.replay(json.dumps({'title': source * 2}), sources=sources).detected)
        self.assertTrue(self.replay(json.dumps({'title': 'new ' + source}), sources=sources).detected)

    def test_source_escape_spellings_and_unicode_are_preserved(self):
        for source in ('반복' * 1024, '\n0' * 1024, '"\\' * 1024):
            body = {'input': [{'role': 'user', 'content': [{'type': 'input_text',
                'text': json.dumps({'blocks': [{'text': source}]})}]}]}
            for ascii_only in (False, True):
                self.assertFalse(self.replay(json.dumps({'title': source}, ensure_ascii=ascii_only),
                                            sources=source_spellings(body)).detected)

    def test_developer_prompt_and_image_data_cannot_exempt_a_loop(self):
        source = 'x' * 2048
        body = {'input': [
            {'role': 'developer', 'content': [{'type': 'input_text', 'text': source}]},
            {'role': 'user', 'content': [{'type': 'input_image', 'image_url': source}]}]}
        self.assertFalse(source_spellings(body))


class RepetitionTransportTests(unittest.TestCase):
    def run_stream(self, events, *, enabled=True, receipt=None, fail_first_get=False):
        self.calls = []
        self.updates = []
        def opener(req, timeout):
            self.calls.append(req)
            if req.method == 'POST':
                return sse(events)
            if fail_first_get and len(self.calls) == 2 or receipt is None:
                raise missing(req)
            return io.StringIO(json.dumps(receipt))
        return net.request_once(request(), open_url=opener, foreground=True,
            reject_title_repetition=enabled, update=lambda **x: self.updates.append(x),
            sleep=lambda _: None)

    def loop_events(self):
        return [created(), {'type': 'response.output_text.delta', 'item_id': 'msg',
                            'delta': '{"title":"' + r'\raud1' * 300}]

    def test_stops_live_socket_and_preserves_terminal_usage_without_accepting_text(self):
        stream = LiveStream()
        self.addCleanup(stream.writer.close)
        self.addCleanup(stream.__exit__)
        stream.send(self.loop_events()[1])
        calls = []
        def opener(req, timeout):
            calls.append(req)
            if req.method == 'POST':
                return stream
            self.assertEqual(stream.writer.recv(1), b'')
            return io.StringIO(json.dumps(native()))
        result = net.request_once(request(), open_url=opener, update=lambda **x: None,
                                  foreground=True, reject_title_repetition=True)
        self.assertIsInstance(result, net.GuardedStudyResponse)
        self.assertEqual(result.reason, 'repeated_short_field')
        self.assertIsNone(result.value)
        self.assertEqual(result.native, native())
        self.assertEqual([req.method for req in calls], ['POST', 'GET'])
        self.assertFalse(any(req.full_url.endswith('/cancel') for req in calls))

    def test_late_recovery_cannot_promote_bad_attempt_to_valid_result(self):
        result = self.run_stream(self.loop_events(), receipt=native(), fail_first_get=True)
        self.assertIsInstance(result, net.GuardedStudyResponse)
        self.assertEqual(result.reason, 'repeated_short_field')
        self.assertIsNone(result.value)
        self.assertEqual(result.native['usage'], native()['usage'])
        self.assertEqual([req.method for req in self.calls], ['POST', 'GET', 'GET'])

    def test_missing_terminal_receipt_cannot_use_partial_json_or_become_free(self):
        with self.assertRaises(net.StudyConnectionError):
            self.run_stream(self.loop_events())
        self.assertEqual(sum(req.method == 'POST' for req in self.calls), 1)
        self.assertTrue(any(row.get('clientStopReason') == 'repeated_short_field'
                            for row in self.updates))

    def test_opt_out_preserves_existing_native_return(self):
        value = text_native(json.dumps({'title': 'x' * 2048}))
        result = self.run_stream([created(), {'type': 'response.completed', 'response': value}],
                                 enabled=False)
        self.assertEqual(result, value)
        self.assertEqual(len(self.calls), 1)

    def test_native_terminal_loop_is_rejected_even_without_delta(self):
        value = text_native(json.dumps({'title': 'x' * 2048}))
        result = self.run_stream([created(), {'type': 'response.completed', 'response': value}])
        self.assertIsInstance(result, net.GuardedStudyResponse)
        self.assertIsNone(result.value)
        self.assertEqual(result.native, value)
        self.assertEqual(len(self.calls), 1)

    def test_complete_json_reply_uses_same_guard_and_retains_usage(self):
        value = text_native(json.dumps({'title': 'x' * 2048}))
        def opener(req, timeout):
            stream = io.StringIO(json.dumps(value)); stream.headers = {}
            return stream
        result = net.request_once(request(), open_url=opener, update=lambda **x: None,
                                  foreground=True, reject_title_repetition=True)
        self.assertIsInstance(result, net.GuardedStudyResponse)
        self.assertEqual(result.native['usage'], value['usage'])


if __name__ == '__main__':
    unittest.main()
