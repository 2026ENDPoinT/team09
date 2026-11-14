import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pdf_performance import measure, timed

class PerformanceTest(unittest.TestCase):
    def test_success_and_error(self):
        with tempfile.TemporaryDirectory() as folder:
            @timed('images')
            def work(folder):return 42
            self.assertEqual(work(folder),42)
            with self.assertRaises(ValueError):
                with measure(folder,'failure',page=3):raise ValueError('private text')
            rows=[json.loads(line) for line in (Path(folder)/'performance.jsonl').read_text().splitlines()]
            self.assertEqual([r['outcome'] for r in rows],['ok','error'])
            self.assertTrue(all(r['durationSeconds']>=0 for r in rows))
            self.assertNotIn('private text',json.dumps(rows))
    def test_logging_failure_does_not_change_result(self):
        with patch('builtins.open',side_effect=PermissionError):
            with measure('/missing','images'):pass

if __name__=='__main__':unittest.main()
