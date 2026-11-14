"""Offline saved-result display integration, including fresh worker processes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pdf_hierarchy_projection_cache as projection_cache
import pdf_new_concept_ver99_study as study
import pdf_study_hierarchy as hierarchy
from test_pdf_native_heading_structure import make_pdf, block, BODY


class SavedProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.cache=self.folder/'generated/new-concept-v99/fixture';self.cache.mkdir(parents=True)
        make_pdf(self.folder,[[('General Principles',28,54,730,True),*BODY]])
        self.blocks=self.cache/'blocks.json'
        self.blocks.write_text(json.dumps([block(text='General Principles\n'+BODY[0][0])]))
        part={'title':'General Principles','body':'기존에 생성한 설명을 보존해요.',
              'evidence':[{'sourceId':'p1','page':1}]}
        self.raw={'documentId':'doc','sourceFingerprint':'fp','strategy':'new-concept-v99',
                  'scope':'document','page':0,'processingComplete':True,
                  'hierarchy':{'version':'study-hierarchy-5','nodes':[]},
                  'sections':[{'title':'General Principles','parts':[part]}],
                  'runUsage':{'requests':2,'usageBasedUsd':.03}}
        self.document={'documentId':'doc','fingerprint':'fp','pages':[{'label':'8'}]}
        self.raw_path=self.cache/'result.json';self.raw_path.write_text(json.dumps(self.raw))
        self.doc_path=self.folder/'index.json';self.doc_path.write_text(json.dumps(self.document))
        self.original={p:p.read_bytes() for p in [self.folder/'source.pdf',self.blocks,self.raw_path,self.doc_path]}

    def display(self):
        with patch.object(study,'hierarchy',hierarchy),patch('socket.socket.connect',side_effect=AssertionError('No API')):
            return study.display_saved(self.folder,self.document,self.raw,self.cache)

    def assert_originals(self):
        self.assertTrue(all(p.read_bytes()==data for p,data in self.original.items()))

    def test_warm_display_skips_layout_and_pdf_work_and_preserves_paid_prose(self):
        raw=copy.deepcopy(self.raw);first=self.display()
        self.assertTrue((self.cache/projection_cache.FILENAME).is_file())
        with (patch.object(study,'display_source_headings',side_effect=AssertionError('No hierarchy work')),
              patch.object(study,'read_json',side_effect=AssertionError('No blocks parse'))):
            second=self.display()
        self.assertEqual(first,second);self.assertEqual(self.raw,raw)
        self.assertEqual(first['runUsage'],raw['runUsage'])
        self.assertEqual(first['sections'][0]['parts'][0]['body'],raw['sections'][0]['parts'][0]['body'])
        self.assert_originals()

    def test_fresh_worker_reuses_projection_without_reopening_pdf(self):
        first=self.display()
        script='''import hashlib,json,socket,sys
from pathlib import Path
import pdf_new_concept_ver99_study as study
socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(AssertionError('No network'))
study.display_source_headings=lambda *a,**k:(_ for _ in ()).throw(AssertionError('No layout work'))
folder=Path(sys.argv[1]);cache=folder/'generated/new-concept-v99/fixture'
value=study.display_saved(folder,json.loads((folder/'index.json').read_text()),json.loads((cache/'result.json').read_text()),cache)
print(hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest())
'''
        env={**os.environ,'SYNESIS_LOCAL_HIERARCHY':'7','PYTHONPATH':str(Path(__file__).parent)}
        got=subprocess.check_output([sys.executable,'-c',script,str(self.folder)],env=env,text=True).strip()
        expected=hashlib.sha256(json.dumps(first,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        self.assertEqual(got,expected);self.assert_originals()

    def test_native_read_failure_is_not_persistently_cached(self):
        from pdf_native_heading_structure import _clear_cache
        _clear_cache()
        with patch('pdfplumber.open',side_effect=OSError('Transient read failure')):
            failed=self.display()
        self.assertEqual(failed['hierarchy']['version'],hierarchy.VERSION)
        self.assertFalse((self.cache/projection_cache.FILENAME).exists())
        repaired=self.display()
        self.assertTrue((self.cache/projection_cache.FILENAME).is_file())
        self.assertTrue(any(n.get('sourceHeading') for n in repaired['hierarchy']['nodes']))
        self.assert_originals()

    def test_cache_read_corruption_and_write_failure_do_not_hide_saved_output(self):
        first=self.display()
        (self.cache/projection_cache.FILENAME).write_text('{broken')
        with patch.object(projection_cache,'store',return_value=False):second=self.display()
        self.assertEqual(second,first);self.assert_originals()

    def test_derived_hierarchy_export_failure_keeps_the_display_result(self):
        with patch.object(study,'save_hierarchy',side_effect=PermissionError('Read-only cache')):
            first=self.display()
        self.assertEqual(first['hierarchy']['version'],hierarchy.VERSION)
        self.assertTrue(first['sections'][0]['parts'][0]['body'])
        self.assert_originals()

    def test_installed_legacy_selector_does_not_use_new_projection_cache(self):
        import pdf_study_hierarchy_legacy as legacy
        with patch.object(study,'hierarchy',legacy),patch.object(projection_cache,'lookup',side_effect=AssertionError('No h7 cache')):
            result=study.display_saved(self.folder,self.document,self.raw,self.cache)
        self.assertEqual(result['hierarchy']['version'],legacy.VERSION)
        self.assertFalse((self.cache/projection_cache.FILENAME).exists());self.assert_originals()


if __name__=='__main__':unittest.main()
