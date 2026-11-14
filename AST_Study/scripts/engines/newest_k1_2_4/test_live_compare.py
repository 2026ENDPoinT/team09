import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import live_compare as live


class LiveTests(unittest.TestCase):
    def test_frame_coverage_overlap_and_short_tail(self):
        pcm = b'\x01\x20' * (16000 * 17 + 57)
        segmenter = live.Segmenter()
        chunks = []
        for i in range(0, len(pcm), 3200):
            chunk = segmenter.feed(pcm[i:i+3200])
            if chunk:
                chunks.append(chunk)
        chunks.append(segmenter.flush())
        self.assertEqual([c.end-c.core_start for c in chunks], [64000, 64000, 64000, 64000, 16057])
        reconstructed = b''.join(c.pcm[(c.core_start-c.start)*2:] for c in chunks)
        self.assertEqual(reconstructed, pcm)
        self.assertEqual(chunks[0].start, 0)
        self.assertEqual(chunks[1].core_start-chunks[1].start, 8000)
        self.assertIsNone(segmenter.flush())

    def test_silence_is_not_deleted(self):
        segmenter = live.Segmenter()
        chunks = [segmenter.feed(bytes(3200)) for _ in range(61)]
        chunks.append(segmenter.flush())
        self.assertEqual(sum(c.end-c.core_start for c in chunks if c), 61*1600)
        self.assertEqual([c.end-c.core_start for c in chunks if c], [32000, 32000, 32000, 1600])

    def test_local_groups_short_windows_without_dropping_audio(self):
        pcm = b'\x01\x20' * (16000 * 18 + 57)
        short = live.Segmenter()
        local = live.LocalWindowAggregator()
        short_chunks, local_chunks = [], []
        for i in range(0, len(pcm), 3200):
            piece = short.feed(pcm[i:i+3200])
            if piece:
                short_chunks.append(piece)
                grouped = local.feed(piece)
                if grouped: local_chunks.append(grouped)
        tail = short.flush()
        if tail:
            short_chunks.append(tail)
            grouped = local.feed(tail)
            if grouped: local_chunks.append(grouped)
        local_chunks.append(local.flush())
        self.assertEqual([c.end-c.core_start for c in short_chunks], [64000]*4+[32057])
        self.assertEqual([c.end-c.core_start for c in local_chunks], [128000, 128000, 32057])
        self.assertEqual(b''.join(c.pcm[(c.core_start-c.start)*2:] for c in local_chunks), pcm)
        self.assertIsNone(local.flush())

    def test_run_distributes_same_source_to_short_and_grouped_lanes(self):
        import threading
        offered = {}
        class FakeWorker:
            def __init__(self, name, *args):
                self.name = name
                offered[name] = []
                self.ready = threading.Event(); self.ready.set()
                self.failed = threading.Event()
                self.finished = threading.Event()
                self.thread = threading.Thread(target=self.finished.wait, daemon=True)
                self.thread.start()
            def offer(self, chunk): offered[self.name].append(chunk)
        class FakeBudget:
            def __init__(self, path): pass
            def close(self): pass
        pcm = b'\x01\x20' * (16000*18+57)
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(output=Path(temp)/'run', models='local,mini,full',
                allow_upload=True, silence_db=-42, pause_ms=500, min_seconds=2,
                max_seconds=4, context_seconds=.5, balance_levels=False)
            with patch.object(live, 'Worker', FakeWorker), patch.object(live, 'Budget', FakeBudget), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(live.run(args, io.BytesIO(pcm)), 0)
            self.assertEqual([(c.start, c.core_start, c.end, c.pcm) for c in offered['mini']],
                             [(c.start, c.core_start, c.end, c.pcm) for c in offered['full']])
            for name in offered:
                self.assertEqual(b''.join(c.pcm[(c.core_start-c.start)*2:] for c in offered[name]), pcm)
            self.assertLess(len(offered['local']), len(offered['mini']))
            inputs = [json.loads(line) for line in (args.output/'events.jsonl').read_text('utf-8').splitlines()
                      if json.loads(line)['kind']=='INPUT']
            self.assertEqual(len(inputs), len(offered['mini'])+len(offered['local']))

    def test_budget_persist_fail_closed_no_refund(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            budget = live.Budget(directory)
            with self.assertRaises(RuntimeError):
                live.Budget(directory)
            for _ in range(72):
                budget.reserve('test', 8.5)
            with self.assertRaises(RuntimeError):
                budget.reserve('test', 1)
            budget.close()
            again = live.Budget(directory)
            with self.assertRaises(RuntimeError):
                again.reserve('test', 1)
            again.close()

    def test_two_cloud_lanes_identical_input_tail_usage_no_local_import(self):
        seen = []
        def fake(engine, model, language, prompt, audio, key, usage_sink=None):
            seen.append((model, hashlib.sha256(audio).hexdigest()))
            usage_sink.update(type='tokens', input_tokens=10, output_tokens=20)
            return '앞 문장과 마지막 문장'
        class FakeBudget:
            def __init__(self, path): pass
            def reserve(self, model, seconds, **kwargs): return .06
            def settle(self, *args): return .016
            def close(self): pass
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'run'
            args = argparse.Namespace(output=folder, models='mini,full', allow_upload=True,
                                      local_model=Path('does-not-exist'), language='ko', prompt='',
                                      silence_db=-42, pause_ms=500, min_seconds=3, max_seconds=8,
                                      context_seconds=0.5, balance_levels=False)
            pcm = b'\x01\x20' * (16000*9+57)
            with patch.object(live, 'cloud_transcribe', fake), patch.object(live, 'api_key', return_value='secret'), \
                 patch.object(live, 'Budget', FakeBudget), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(live.run(args, io.BytesIO(pcm)), 0)
            events = [json.loads(line) for line in (folder/'events.jsonl').read_text('utf-8').splitlines()]
            results = [e for e in events if e['kind']=='RESULT']
            self.assertEqual(len(results), 4)
            captions = [e for e in events if e['kind']=='CAPTION']
            self.assertEqual(len(captions), 4)
            self.assertTrue(all(e['transcript'] == '앞 문장과 마지막 문장' for e in captions))
            for index in (1, 2):
                pair = [e for e in results if e['chunk']==index]
                self.assertEqual(pair[0]['input_sha256'], pair[1]['input_sha256'])
            capture = next(e for e in events if e['kind']=='CAPTURE_END')
            self.assertEqual(capture['source_pcm_sha256'], hashlib.sha256(pcm).hexdigest())
            self.assertNotIn('secret', (folder/'events.jsonl').read_text('utf-8'))
            self.assertTrue(all(e['estimated_cost_usd'] > 0 for e in results))

    def test_cloud_failure_no_retry(self):
        class Events:
            def emit(self, *args, **kwargs): pass
        class Budget:
            def reserve(self, *args, **kwargs): return .06
            def settle(self, *args): return .016
        args = argparse.Namespace(allow_upload=True, language='ko', prompt='')
        with patch.object(live, 'api_key', return_value='secret'), \
             patch.object(live, 'cloud_transcribe', side_effect=RuntimeError('test failure')) as request:
            worker = live.Worker('mini', args, Events(), Budget())
            self.assertTrue(worker.ready.wait(2))
            worker.offer(live.Chunk(1, 0, 0, 1600, bytes(3200), time.monotonic()))
            worker.offer(live.Chunk(2, 1600, 1600, 3200, bytes(3200), time.monotonic()))
            worker.finished.set()
            worker.thread.join(2)
            self.assertTrue(worker.failed.is_set())
            self.assertEqual(request.call_count, 1)

    def test_pause_threshold_and_max_duration(self):
        segmenter = live.Segmenter(silence_db=-30, pause_ms=300, min_seconds=1, max_seconds=4)
        for _ in range(7):
            self.assertIsNone(segmenter.feed(b'\x01\x20'*1600))
        for _ in range(2):
            self.assertIsNone(segmenter.feed(bytes(3200)))
        first = segmenter.feed(bytes(3200))
        self.assertEqual(first.end, 16000)
        chunks = [segmenter.feed(b'\x01\x20'*1600) for _ in range(40)]
        self.assertEqual([c.end-c.core_start for c in chunks if c], [64000])

    def test_overloaded_lane_does_not_block_healthy_lane(self):
        import threading
        release = threading.Event()
        entered = threading.Event()
        results = []
        class Events:
            def emit(self, kind, model='all', *args, **kwargs):
                results.append((kind, model))
        class Budget:
            def reserve(self, *args, **kwargs): return .06
            def settle(self, *args): return .016
        def fake(engine, model, *args, **kwargs):
            if model == 'gpt-4o-transcribe':
                entered.set()
                release.wait(3)
            return 'test'
        args = argparse.Namespace(allow_upload=True, language='ko', prompt='')
        with patch.object(live, 'api_key', return_value='secret'), patch.object(live, 'cloud_transcribe', fake):
            slow = live.Worker('full', args, Events(), Budget())
            fast = live.Worker('mini', args, Events(), Budget())
            slow.ready.wait(2); fast.ready.wait(2)
            chunk = live.Chunk(1, 0, 0, 1600, bytes(3200), time.monotonic())
            slow.offer(chunk); self.assertTrue(entered.wait(2))
            for _ in range(4): slow.offer(chunk)
            self.assertTrue(slow.failed.is_set())
            fast.offer(chunk); fast.finished.set(); fast.thread.join(2)
            self.assertFalse(fast.thread.is_alive())
            self.assertIn(('RESULT', 'mini'), results)
            release.set(); slow.finished.set(); slow.thread.join(2)

    def test_balancer_preserves_frames_and_source(self):
        from array import array
        quiet = array('h', [100, -100]*800).tobytes()
        loud = array('h', [29000, -29000]*800).tobytes()
        original = quiet + loud + quiet[:114]
        balance = live.LevelBalancer()
        result = b''.join(balance.process(p) for p in (quiet, loud, quiet[:114]))
        self.assertEqual(len(result), len(original))
        self.assertEqual(original[:3200], quiet)
        self.assertGreater(abs(array('h', result)[0]), 100)
        self.assertLessEqual(max(abs(v) for v in array('h', result)), 29205)

    def test_cap_reservations_concurrent(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as temp:
            budget = live.Budget(Path(temp))
            def attempt(_):
                try: return budget.reserve('test', 8)
                except RuntimeError: return None
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(attempt, range(100)))
            self.assertEqual(sum(r is not None for r in results), 72)
            self.assertLessEqual(max(r for r in results if r is not None), live.DAILY_LIMIT)
            budget.close()

    def test_context_options_preserve_all_core_frames(self):
        pcm = b'\x01\x20' * (16000*10+7)
        for context in (0, 0.5, 1, 2):
            segmenter = live.Segmenter(max_seconds=4, context_seconds=context)
            chunks = []
            for i in range(0, len(pcm), 3200):
                chunk = segmenter.feed(pcm[i:i+3200])
                if chunk: chunks.append(chunk)
            chunks.append(segmenter.flush())
            self.assertEqual(b''.join(c.pcm[(c.core_start-c.start)*2:] for c in chunks), pcm)
            self.assertEqual(chunks[1].core_start-chunks[1].start, context*16000)

    def test_success_settles_once_and_unknown_usage_keeps_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            budget = live.Budget(Path(temp))
            budget.reserve(live.MODELS['mini'], 8, request_id='one')
            budget.reserve(live.MODELS['full'], 8, request_id='two')
            valid = dict(type='tokens', input_tokens=100, output_tokens=20)
            expected = live.PRIOR_ALLOWANCE + live.REQUEST_RESERVATION + .000225
            self.assertAlmostEqual(budget.settle('one', valid), expected)
            self.assertAlmostEqual(budget.settle('one', valid), expected)
            for invalid in ({}, dict(type='tokens', input_tokens=-1, output_tokens=3),
                            dict(type='tokens', input_tokens=0, output_tokens=0),
                            dict(type='tokens', input_tokens=True, output_tokens=2)):
                self.assertAlmostEqual(budget.settle('two', invalid), expected)
            budget.close()
            again = live.Budget(Path(temp))
            self.assertAlmostEqual(again.reserve(live.MODELS['mini'], 8), expected + live.REQUEST_RESERVATION)
            again.close()

    def test_settlement_tracks_original_day_and_overrun(self):
        with tempfile.TemporaryDirectory() as temp:
            budget = live.Budget(Path(temp))
            budget.reserve(live.MODELS['full'], 8, request_id='a')
            original_path = budget.receipts['a']
            # Settlement must use the original receipt path, not today's date.
            with patch.object(live, 'datetime') as clock:
                clock.now.side_effect = AssertionError('Settlement must not read current date')
                self.assertGreater(budget.settle('a', dict(type='tokens', input_tokens=100000, output_tokens=10)), live.DAILY_LIMIT)
            self.assertEqual(json.loads(original_path.read_text())['requests'][0]['status'], 'settled')
            with self.assertRaises(RuntimeError): budget.reserve(live.MODELS['mini'], 1)
            budget.close()

    def test_many_successful_requests_do_not_exhaust_flat_reservations(self):
        with tempfile.TemporaryDirectory() as temp:
            budget = live.Budget(Path(temp))
            for i in range(50):
                budget.reserve(live.MODELS['mini'], 8, request_id=str(i))
                used = budget.settle(str(i), dict(type='tokens', input_tokens=100, output_tokens=20))
            self.assertAlmostEqual(used, .015 + 50*.000225)
            self.assertLess(used, live.DAILY_LIMIT)
            budget.close()

    def test_one_failed_model_blocks_all_audio_and_paid_requests(self):
        import threading
        from unittest.mock import Mock
        class FakeBudget:
            def __init__(self, path): pass
            def close(self): pass
        def worker(name, *args):
            result = Mock()
            result.ready = threading.Event(); result.ready.set()
            result.failed = threading.Event()
            if name == 'full': result.failed.set()
            result.finished = threading.Event()
            return result
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(output=Path(temp)/'run', models='mini,full', allow_upload=True)
            source = Mock()
            source.read.side_effect = AssertionError('Must not read audio after preparation failure')
            with patch.object(live, 'Worker', side_effect=worker), patch.object(live, 'Budget', FakeBudget), \
                 patch.object(live, 'cloud_transcribe') as request, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(live.run(args, source), 1)
                request.assert_not_called()
                source.read.assert_not_called()
            events = [json.loads(line) for line in (args.output/'events.jsonl').read_text('utf-8').splitlines()]
            self.assertFalse(any(e['kind'] == 'READY' for e in events))


if __name__ == '__main__':
    unittest.main()
