"""CLI routing and legacy opt-in contracts; no network or paid generation."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_new_concept_study as new
import pdf_new_concept_v02_study as v02
import pdf_new_concept_ver99_study as v99
import pdf_newest_k1_1_2 as k112
import pdf_page_analysis as pages
import pdf_pipeline
import pdf_region_study as regions
import pdf_semantic as semantic


class DefaultStrategyTests(unittest.TestCase):
    def run_cli(self, command, request=None, environment=None):
        with tempfile.TemporaryDirectory() as t, contextlib.ExitStack() as stack:
            folder = Path(t)
            (folder/'document.json').write_text(json.dumps({'documentId':'test','pages':[]}))
            target = folder/'request.json'
            target.write_text(json.dumps({'scope':'document', **(request or {})}))
            argv = ['pdf_ai.py', command, '--folder', str(folder), '--request', str(target)]
            if command == 'generate':
                argv += ['--allow-remote', '--max-usd', '.01']
            stack.enter_context(patch.dict(os.environ, environment or {}, clear=True))
            stack.enter_context(patch.object(sys, 'argv', argv))
            stack.enter_context(patch.object(pdf_pipeline, 'enrich_visual_routing'))
            stack.enter_context(patch.object(pages, 'hydrate'))
            stack.enter_context(patch.object(ai, 'Provider', return_value=SimpleNamespace(
                ledger={'operationId':'offline-routing-fixture'},billing=None)))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            ai.main()
            return json.loads(target.with_suffix('.result.json').read_text())

    def test_unspecified_strategy_routes_plan_generate_and_recovery_to_new(self):
        for command, method in [('vision-plan','reading_plan'), ('generate','generate'), ('recover','recover')]:
            with self.subTest(command=command), patch.object(k112, method, return_value={'strategy':'newest-k1-1-2'}) as call:
                self.assertEqual(self.run_cli(command)['strategy'], 'newest-k1-1-2')
                call.assert_called_once()

    def test_all_five_legacy_strategies_remain_explicitly_selectable(self):
        for strategy, engine, method in [('page-v1',pages,'plan'),('semantic-v1',semantic,'reading_plan'),
                ('new-concept-v1',new,'reading_plan'),('new-concept-v02',v02,'reading_plan'),
                *[(s,regions,'reading_plan') for s in regions.STRATEGIES]]:
            with self.subTest(strategy=strategy), patch.object(engine, method, return_value={'strategy':strategy}) as call:
                self.assertEqual(self.run_cli('vision-plan', {'strategy':strategy})['strategy'], strategy)
                call.assert_called_once()

    def test_explicit_selection_overrides_environment_and_environment_allows_rollback(self):
        env = {'SYNESIS_PDF_STRATEGY':'semantic-v1'}
        with patch.object(semantic, 'reading_plan', return_value={'strategy':'semantic-v1'}) as call:
            self.assertEqual(self.run_cli('vision-plan', environment=env)['strategy'], 'semantic-v1')
            call.assert_called_once()
        with patch.object(new, 'reading_plan', return_value={'strategy':'new-concept-v1'}) as call:
            self.assertEqual(self.run_cli('vision-plan', {'strategy':'new-concept-v1'}, env)['strategy'], 'new-concept-v1')
            call.assert_called_once()


if __name__ == '__main__':
    unittest.main()
