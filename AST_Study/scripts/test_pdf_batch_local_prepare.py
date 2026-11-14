"""Local batch prefetch must never plan, render crops, or invoke a provider."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pdf_new_concept_ver99_study as study

class LocalBatchPreparationTest(unittest.TestCase):
    def test_only_immutable_layout_is_warmed(self):
        document={'documentId':'doc','fingerprint':'fingerprint','pages':[{'number':1,'nativeText':'source'}]}
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with patch.object(study,'extract_layout',return_value=[{'id':'source'}]) as extract, patch.object(study,'plan_groups',side_effect=AssertionError('API grouping')), patch.object(study,'render_crops',side_effect=AssertionError('crop rendering')):
                value=study.prepare_local_sources(folder,document)
            self.assertEqual(value['kind'],'local_prepared')
            self.assertEqual(value['sourceBlocks'],1)
            self.assertEqual(extract.call_args.args[2],[1])
            self.assertFalse(any(folder.rglob('plan.json')))
            self.assertFalse(any(folder.rglob('blocks.json')))

if __name__=='__main__':unittest.main()
