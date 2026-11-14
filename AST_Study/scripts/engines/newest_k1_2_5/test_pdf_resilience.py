"""Offline fault injection across reading, linking, writing, finalization and resume."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_semantic as sem
import pdf_outline as outline
import pdf_page_analysis as vision
from pdf_pipeline import write_json
from test_pdf_semantic import FakeProvider, block, decision
from test_pdf_page_analysis import document


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()

    def tearDown(self):
        self.quiet.__exit__(None, None, None)
        self.temp.cleanup()

    def test_bad_first_reading_preserves_later_pages_and_repairs_only_first(self):
        doc = document(self.folder, 4)
        class Provider(FakeProvider):
            def complete(inner, payload, **kw):
                result = super().complete(payload, **kw)
                if len(payload['pages']) > 1:
                    result['pages'][0]['analysis'] = None
                    result['pages'].reverse()
                else:
                    self.assertTrue(all(sem.reading_cache_path(self.folder, doc, n).exists()
                                        for n in (2, 3, 4)))
                return result
        provider = Provider()
        result = sem.read_pages(self.folder, doc, provider, [1, 2, 3, 4])
        self.assertEqual(set(result), {1, 2, 3, 4})
        self.assertEqual([[p['page'] for p in c['pages']] for c in provider.calls], [[1, 2, 3, 4], [1]])

    def test_duplicate_and_missing_readings_repair_exact_pages(self):
        doc = document(self.folder, 3)
        class Provider(FakeProvider):
            def complete(inner, payload, **kw):
                raw = super().complete(payload, **kw)
                if len(payload['pages']) > 1:
                    raw['pages'] = [raw['pages'][0], raw['pages'][0], raw['pages'][2]]
                return raw
        provider = Provider()
        result = sem.read_pages(self.folder, doc, provider, [1, 2, 3])
        self.assertEqual(set(result), {1, 2, 3})
        self.assertEqual([[p['page'] for p in c['pages']] for c in provider.calls], [[1, 2, 3], [1], [2]])

    def test_unrecoverable_reading_drains_and_retains_successes(self):
        doc = document(self.folder, 3)
        class Provider(FakeProvider):
            def complete(inner, payload, **kw):
                raw = super().complete(payload, **kw)
                for entry in raw['pages']:
                    if entry['page'] in (1, 2):
                        entry['analysis'] = None
                return raw
        provider = Provider()
        with self.assertRaises(ValueError):
            sem.read_pages(self.folder, doc, provider, [1, 2, 3])
        self.assertTrue(sem.reading_cache_path(self.folder, doc, 3).exists())
        self.assertFalse(sem.reading_cache_path(self.folder, doc, 1).exists())
        fresh = FakeProvider()
        sem.read_pages(self.folder, doc, fresh, [1, 2, 3])
        self.assertEqual([p['page'] for c in fresh.calls for p in c['pages']], [1, 2])

    def test_render_failure_does_not_discard_other_pages(self):
        doc = document(self.folder, 2)
        real = vision.render_page
        def render(folder, number):
            if number == 1:
                raise ValueError('damaged page')
            return real(folder, number)
        with patch.object(vision, 'render_page', side_effect=render), self.assertRaises(ValueError):
            sem.read_pages(self.folder, doc, FakeProvider(), [1, 2])
        self.assertTrue(sem.reading_cache_path(self.folder, doc, 2).exists())

    def test_transport_failure_is_not_retried_as_malformed_reading(self):
        doc = document(self.folder, 2)
        provider = FakeProvider()
        with patch.object(provider, 'complete', side_effect=ai.AiResponseError('transport')) as remote:
            with self.assertRaises(ai.AiResponseError):
                sem.read_pages(self.folder, doc, provider, [1, 2])
        self.assertEqual(remote.call_count, 1)

    def test_corrupted_reading_cache_is_reconstructed(self):
        doc = document(self.folder, 2)
        write_json(sem.reading_cache_path(self.folder, doc, 1), [])
        write_json(vision.cache_path(self.folder, doc, 2), [])
        result = sem.read_pages(self.folder, doc, FakeProvider(), [1, 2])
        self.assertEqual(set(result), {1, 2})

    def job(self):
        blocks = [block(0), block(1)]
        units, _ = sem.make_units(blocks, [decision(b) for b in blocks], {1, 2})
        return sem.study_jobs(units)[0]

    def test_malformed_study_shapes_are_repaired_without_losing_good_unit(self):
        doc = document(self.folder, 2)
        for corrupt in (lambda u: u.update(parts=[None]),
                        lambda u: u.update(concepts=None),
                        lambda u: u['parts'][0].update(blockIds=[{}]),
                        lambda u: u.update(resolvedBoundaries=[None])):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as td:
                folder = Path(td)
                class Provider(FakeProvider):
                    def complete(inner, payload, **kw):
                        raw = super().complete(payload, **kw)
                        if len(payload['units']) > 1:
                            corrupt(raw['units'][0])
                        return raw
                provider = Provider()
                results = sem.complete_study_job(folder, folder, self.job(), doc, provider)
                self.assertEqual(len(results), 2)
                self.assertEqual([len(c['units']) for c in provider.calls], [2, 1])

    def test_end_to_end_terminal_failures_repaired_then_zero_call_resume(self):
        doc = document(self.folder, 2)
        class Provider(FakeProvider):
            def complete(inner, payload, **kw):
                if payload['task'] in ('semantic_reading', 'semantic_links', 'semantic_study') and not payload.get('repair'):
                    inner.calls.append(copy.deepcopy(payload))
                    raise ai.IncompleteResponseError('terminal truncated response')
                return super().complete(payload, **kw)
        provider = Provider()
        result = sem.generate(self.folder, doc, provider)
        self.assertTrue(result['processingComplete'])
        self.assertEqual(result['coverageCounts']['summarized'], 2)
        count = len(provider.calls)
        self.assertEqual(sem.generate(self.folder, doc, provider), result)
        self.assertEqual(len(provider.calls), count)

    def test_truncated_single_unit_repair_has_bounded_second_attempt(self):
        doc = document(self.folder, 2)
        class Provider(FakeProvider):
            def complete(inner, payload, **kw):
                if payload.get('repair', {}).get('attempt', 0) < 2:
                    inner.calls.append(copy.deepcopy(payload))
                    raise ai.IncompleteResponseError('terminal length')
                return super().complete(payload, **kw)
        provider = Provider()
        result = sem.complete_study_job(self.folder, self.folder, self.job(), doc, provider)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(provider.calls), 5)

    def test_study_transport_failure_stops_without_automatic_paid_retry(self):
        doc = document(self.folder, 2)
        provider = FakeProvider()
        with patch.object(provider, 'complete', side_effect=ai.AiResponseError('timeout')) as remote:
            with self.assertRaises(ai.AiResponseError):
                sem.complete_study_job(self.folder, self.folder, self.job(), doc, provider)
        self.assertEqual(remote.call_count, 1)

    def test_cancelled_audit_propagates_without_marking_complete(self):
        blocks = [block(0, '1. 압축적 산업화'), block(1, '압축적 산업화에 따른 사회 변화예요.')]
        blocks[0]['title'] = '단원 제목'
        manifest = {'jobs': [[{'unitId': 'u', 'blocks': blocks}]]}
        completed = [{'unitId': 'u', 'summary': {'body': '설명이에요.'}}]
        provider = FakeProvider()
        result = {'concepts': []}
        with patch.object(provider, 'complete', side_effect=InterruptedError('cancel')):
            with self.assertRaises(InterruptedError):
                sem.audit_missing_concepts(provider, self.folder, {}, manifest, completed, result)
        self.assertNotIn('conceptAuditVersion', result)

    def test_optional_audit_failure_retains_successful_groups(self):
        blocks = [block(0, '별도 개념 A'), block(1, '별도 개념 B')]
        units = [{'unitId': f'u{i}', 'blocks': [b]} for i, b in enumerate(blocks)]
        completed = [{'unitId': u['unitId'], 'summary': {'body': '원래 설명이에요.', 'parts': [
            {'blockIds': [str(i)], 'evidence': [{'sourceId': str(i), 'page': i+1}]}]}}
            for i, u in enumerate(units)]
        class Provider:
            def complete(inner, payload, **kw):
                cue = payload['candidates'][0]
                if cue['term'] == '별도 개념 A':
                    raise ai.AiResponseError('transport')
                return {'decisions': [{'cueId': cue['cueId'], 'action': 'add', 'name': cue['term'],
                    'definition': '별도 조건을 설명하는 개념이에요.', 'explanation': '조건에 따른 변화를 설명해요.',
                    'easyExplanation': '주어진 조건을 먼저 살펴봐요.', 'reason': '별도 개념이에요.'}]}
        with patch.object(sem, 'concept_cues', side_effect=lambda bs: [bs[0]['text']]):
            result = sem.audit_missing_concepts(Provider(), self.folder, {}, {'jobs': [units]},
                completed, {'concepts': [], 'sections': [{'body': '원래 설명이에요.'}]})
        self.assertEqual(result['conceptAuditAdded'], ['별도 개념 B'])
        self.assertEqual(result['conceptAuditStatus'], 'partial')
        self.assertEqual(result['sections'][0]['body'], '원래 설명이에요.')

    def test_outline_corrupt_cache_empty_topics_and_long_titles_never_abort(self):
        provider = FakeProvider()
        sections = [{'title': '아주 긴 개념 제목 ' * 80, 'parts': [], 'evidence': []}]
        result = outline.overview(provider, self.folder, sections, local_only=True)
        self.assertIn('아주 긴', result['body'])
        path = next(self.folder.glob('outline-*.json'))
        for content in ('{broken', '[]'):
            path.write_text(content)
            result = outline.overview(provider, self.folder, sections, local_only=True)
            self.assertIn('아주 긴', result['body'])
        self.assertEqual(outline.overview(provider, self.folder, [], local_only=True)['sourceSectionIds'], [])
        self.assertEqual(provider.calls, [])

    def test_paid_response_corruption_recovers_raw_without_network(self):
        calls = []
        def transport(body):
            calls.append(body)
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}
        provider = ai.Provider(self.folder, True, .1, transport=transport)
        self.assertEqual(provider.complete({'test': 1}), {'ok': True})
        path = next(p for p in (self.folder/'generated/paid-responses').glob('*.json') if '.raw.' not in p.name)
        path.write_text('{broken')
        self.assertEqual(provider.complete({'test': 1}), {'ok': True})
        self.assertEqual(len(calls), 1)

    def test_terminal_response_errors_have_same_type_live_and_cached(self):
        for reason, content in [('length', '{'), ('stop', '{'), ('stop', '[]')]:
            with self.subTest(reason=reason, content=content), tempfile.TemporaryDirectory() as td:
                calls = []
                def transport(body):
                    calls.append(body)
                    return {'choices': [{'finish_reason': reason, 'message': {'content': content}}],
                            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}
                provider = ai.Provider(Path(td), True, .1, transport=transport)
                for _ in range(2):
                    with self.assertRaises(ai.IncompleteResponseError):
                        provider.complete({'test': 1})
                self.assertEqual(len(calls), 1)

    def test_refusal_is_never_classified_as_retryable_malformed_response(self):
        provider = ai.Provider(self.folder, True, .1, transport=lambda body: {
            'choices': [{'finish_reason': 'stop', 'message': {'content': None, 'refusal': 'refused'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
        for _ in range(2):
            with self.assertRaises(ai.AiResponseError) as error:
                provider.complete({'test': 1})
            self.assertNotIsInstance(error.exception, ai.IncompleteResponseError)

    def test_app_cli_uses_same_provider_class_as_imported_helpers(self):
        code = """
import runpy, sys
sys.argv = ['pdf_ai.py', '--help']
try:
    runpy.run_path('scripts/pdf_ai.py', run_name='__main__')
except SystemExit as error:
    assert error.code == 0
import pdf_ai, pdf_semantic
assert pdf_ai.Provider.__module__ == '__main__'
from tempfile import TemporaryDirectory
from pathlib import Path
with TemporaryDirectory() as folder:
    accepted = []
    attempts = []
    def work(item):
        attempts.append(item)
        if len(attempts) == 1:
            raise pdf_ai.BudgetExceeded('reservation')
        return item
    pdf_semantic.parallel([1], work, lambda _, value: accepted.append(value), Path(folder))
    assert accepted == [1] and attempts == [1, 1]
"""
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                env={**os.environ, 'PYTHONPATH': 'scripts'}, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_latest_publication_recovers_completed_result_without_remote(self):
        doc = document(self.folder, 2)
        provider = FakeProvider()
        real_write = sem.write_json
        def write(path, value):
            if path == sem.latest_path(self.folder, 'document', 0):
                raise OSError('simulated disk failure')
            return real_write(path, value)
        with patch.object(sem, 'write_json', side_effect=write), self.assertRaises(OSError):
            sem.generate(self.folder, doc, provider)
        recovered = sem.recover(self.folder, doc)
        self.assertTrue(recovered['processingComplete'])
        count = len(provider.calls)
        sem.generate(self.folder, doc, provider)
        self.assertEqual(len(provider.calls), count)
        self.assertTrue(sem.latest_path(self.folder, 'document', 0).exists())

    def test_usage_report_failure_does_not_hide_completed_cli_result(self):
        doc = document(self.folder, 2)
        result = sem.generate(self.folder, doc, FakeProvider())
        write_json(self.folder/'document.json', doc)
        request = self.folder/'request.json'
        write_json(request, {'scope': 'document', 'strategy': 'semantic-v1'})
        provider = ai.Provider(self.folder, True, .1, transport=lambda _: self.fail('unexpected remote'))
        argv = ['pdf_ai.py', 'generate', '--folder', str(self.folder), '--request', str(request),
                '--allow-remote', '--max-usd', '.1']
        with patch.object(sys, 'argv', argv), patch.object(ai, 'Provider', return_value=provider), \
                patch.object(sem, 'generate', return_value=result), \
                patch.object(sem, 'record_usage', side_effect=OSError('report unavailable')):
            ai.main()
        saved = json.loads(request.with_suffix('.result.json').read_text())
        self.assertTrue(saved['processingComplete'])
        self.assertEqual(saved['generationUsage']['status'], 'unavailable')
        original = ai.AiResponseError('original failure')
        with patch.object(sys, 'argv', argv), patch.object(ai, 'Provider', return_value=provider), \
                patch.object(sem, 'generate', side_effect=original), \
                patch.object(sem, 'record_usage', side_effect=OSError('report unavailable')):
            with self.assertRaises(ai.AiResponseError) as error:
                ai.main()
        self.assertIs(error.exception, original)


if __name__ == '__main__':
    unittest.main()
