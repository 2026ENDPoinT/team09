"""Headless request parity and session budget/history isolation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pdf_ai import BudgetExceeded, run_tutor_request, load_tutor_document
from pdf_pipeline import write_json
from pdf_tutor_cli import Session, main
from test_pdf_tutor_intent import document, semantic
from test_pdf_tutor_final_answer import Provider, reply


class HeadlessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'pdf'
        doc = document()
        doc['pages'] = [{'number': n, 'markdown': '', 'nativeText': '', 'textRegions': []}
                        for n in range(1, 18)]
        write_json(self.folder / 'document.json', doc)

    def tearDown(self):
        self.temp.cleanup()

    def test_cli_and_desktop_use_identical_request_adapter(self):
        plan = {**semantic('마티스', page=16), 'scope': 'pdf'}
        cli_provider = Provider([reply('설명해요.')], plan)
        cli_provider.ledger = {'requests': []}
        cli_provider.ledger_path = self.root / 'run/usage/test.json'
        cli_provider.max_usd, cli_provider.spent = .1, 0
        session = Session(self.folder, self.root / 'run', cli_provider)
        row = session.ask('16페이지 내용을 설명해줘', page=16)
        desktop_provider = Provider([reply('설명해요.')], plan)
        desktop_provider.ledger = {'requests': []}
        desktop = run_tutor_request(self.folder, load_tutor_document(self.folder),
            {'question': row['question'], 'page': 16, 'mode': 'quick', 'memory': None,
             'webFallback': True, 'strategy': 'new-concept-v99'}, desktop_provider)
        self.assertEqual(cli_provider.calls, desktop_provider.calls)
        self.assertEqual(row['result']['answer'], desktop['answer'])
        self.assertEqual(row['result']['evidence'], desktop['evidence'])

    def test_page_and_conversation_survive_restart_without_modifying_index(self):
        original = (self.folder / 'document.json').read_bytes()
        session = Session(self.folder, self.root / 'run')
        row = session.ask('16페이지 내용을 찾아줘', page=16)
        resumed = Session(self.folder, self.root / 'run', resume=True)
        self.assertEqual(resumed.state['page'], 16)
        self.assertEqual(resumed.state['memory'], row['result']['memory'])
        self.assertTrue(row['result']['evidence'])
        self.assertEqual((self.folder / 'document.json').read_bytes(), original)

    def test_default_cli_does_not_construct_paid_provider(self):
        with patch('pdf_tutor_cli.Provider', side_effect=AssertionError('network forbidden')), \
                patch('builtins.print'):
            main(['--folder', str(self.folder), '--question', '이 PDF는 몇 페이지야?',
                  '--output', str(self.root / 'run')])
        state = json.loads((self.root / 'run/session.json').read_text())
        self.assertEqual(state['turns'][0]['usage']['requests'], 0)

    def test_uncertain_old_calls_count_towards_resumed_budget(self):
        Session(self.folder, self.root / 'run').ask('이 PDF는 몇 페이지야?')
        output = self.root / 'run'
        write_json(output / 'usage/old.json', {'requests': [
            {'state': 'settled', 'estimatedUsd': .01},
            {'state': 'failed_or_uncertain', 'reservedUsd': .02}]})
        provider = Provider([], semantic('내용'))
        provider.ledger = {'requests': []}
        provider.ledger_path = output / 'usage/new.json'
        provider.max_usd = .025
        with self.assertRaises(BudgetExceeded):
            Session(self.folder, output, provider, resume=True)
        provider.max_usd = .05
        Session(self.folder, output, provider, resume=True)
        self.assertAlmostEqual(provider.max_usd, .02)

    def test_bad_page_and_unrequested_overwrite_stop_before_calling_model(self):
        session = Session(self.folder, self.root / 'run')
        with self.assertRaises(ValueError):
            session.ask('설명해줘', page=999)
        session.ask('이 PDF는 몇 페이지야?')
        with self.assertRaises(ValueError):
            Session(self.folder, self.root / 'run')


if __name__ == '__main__':
    unittest.main()
