"""Old identity recovery is exact, local, and display-only."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study
import pdf_study_hierarchy as hierarchy
from test_pdf_hierarchy_layout_relations import layout, paragraph, concept
from test_pdf_native_heading_structure import make_pdf, BODY


class HistoricalRecoverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.old=self.folder/'generated/new-concept-v99/old-paid-identity';self.old.mkdir(parents=True)
        self.document={'documentId':'doc','fingerprint':'fp','pages':[{'label':'8'}]}
        self.current=study.root_path(self.folder,self.document,'new-concept-v99','gpt-6-luna','document',0)
        make_pdf(self.folder,[[('General Principles',28,54,730,True),*BODY]])
        blocks=[layout('root','1. 공통 원리',kind='heading',font=32,top=.05),
                paragraph('a',top=.3),paragraph('b',top=.6)]
        (self.old/'blocks.json').write_text(json.dumps(blocks))
        self.raw={'documentId':'doc','sourceFingerprint':'fp','strategy':'new-concept-v99',
                  'model':'gpt-6-luna','promptVersion':study.VERSION,'scope':'document','page':0,
                  'kind':'partial','processingComplete':False,
                  'hierarchy':{'version':'study-hierarchy-5','nodes':[]},
                  'sections':[{'title':'공통 원리','parts':[concept('첫 개념',['a'],'기존 첫 설명이에요.'),
                                                          concept('둘째 개념',['b'],'기존 두 번째 설명이에요.')]}],
                  'concepts':[{'name':'원래 개념','entries':[{'name':'원래 개념','definition':'저장된 정의예요.',
                               'evidence':[{'sourceId':'a','page':1}]}]}],
                  'runUsage':{'requests':2,'usageBasedUsd':.03}}
        self.saved=self.old/'partial.json';self.saved.write_text(json.dumps(self.raw,ensure_ascii=False))

    def recover(self):
        with (patch.object(study,'hierarchy',hierarchy),
              patch.object(study,'Provider',create=True,side_effect=AssertionError('No provider')),
              patch('socket.socket.connect',side_effect=AssertionError('No network'))):
            return study.recover(self.folder,self.document)

    def test_old_identity_partial_without_latest_preserves_prose_and_reuses_local_projection(self):
        original={p:p.read_bytes() for p in [self.saved,self.old/'blocks.json',self.folder/'source.pdf']}
        first=self.recover()
        self.assertEqual(first['hierarchy']['version'],hierarchy.VERSION)
        self.assertEqual([p['body'] for p in first['sections'][0]['parts']],
                         [p['body'] for p in self.raw['sections'][0]['parts']])
        self.assertEqual(first['concepts'],self.raw['concepts']);self.assertEqual(first['runUsage'],self.raw['runUsage'])
        self.assertTrue((self.old/'display-hierarchy-7.json').is_file())
        self.assertFalse(self.current.exists())
        with patch.object(study,'display_source_headings',side_effect=AssertionError('Use existing local projection')):
            self.assertEqual(self.recover(),first)
        self.assertTrue(all(path.read_bytes()==data for path,data in original.items()))

    def test_history_rejects_mismatched_identity_empty_payload_and_unreadable_json(self):
        for key,value in [('documentId','other'),('sourceFingerprint','stale'),('strategy','new-concept-v02'),
                          ('model','gpt-6-sol'),('scope','page'),('page',1),('page',False),
                          ('promptVersion','old-prompt')]:
            with self.subTest(key=key,value=value):
                invalid=copy.deepcopy(self.raw);invalid[key]=value
                self.saved.write_text(json.dumps(invalid));self.assertIsNone(self.recover())
        for invalid in [[],{'unexpected':'record'}, {**self.raw,'sections':[],'concepts':[]},
                        {**self.raw,'sections':[{}],'concepts':[]}]:
            self.saved.write_text(json.dumps(invalid));self.assertIsNone(self.recover())
        self.saved.write_text('{broken');self.assertIsNone(self.recover())

    def test_current_identity_result_or_partial_wins_over_history(self):
        for complete in (False,True):
            with self.subTest(complete=complete):
                self.current.mkdir(parents=True,exist_ok=True)
                current=copy.deepcopy(self.raw);current['processingComplete']=complete;current['choice']='current'
                target=self.current/('result.json' if complete else 'partial.json')
                target.write_text(json.dumps(current))
                with patch.object(study,'display_saved',side_effect=lambda folder,doc,value,cache:value) as display:
                    self.assertEqual(self.recover()['choice'],'current')
                self.assertEqual(display.call_args.args[3],self.current)
                target.unlink()

    def test_latest_partial_wins_before_historical_timestamp_search(self):
        latest=study.latest_path(self.folder,'new-concept-v99','document',0)
        value=copy.deepcopy(self.raw);value['choice']='latest';latest.write_text(json.dumps(value))
        os.utime(self.saved,ns=(2_000_000_000_000_000_000,2_000_000_000_000_000_000))
        with patch.object(study,'display_saved',side_effect=lambda folder,doc,value,cache:value) as display:
            self.assertEqual(self.recover()['choice'],'latest')
        self.assertEqual(display.call_args.args[3],self.current)

    def test_newest_matching_historical_candidate_wins_and_invalid_newer_is_skipped(self):
        second=self.old.parent/'second-paid-identity';second.mkdir()
        valid=copy.deepcopy(self.raw);valid['choice']='newer';(second/'result.json').write_text(json.dumps(valid))
        os.utime(self.saved,ns=(1_000_000_000,1_000_000_000))
        (second/'partial.json').write_text(json.dumps({**valid,'sourceFingerprint':'stale'}))
        with patch.object(study,'display_saved',side_effect=lambda folder,doc,value,cache:value) as display:
            self.assertEqual(self.recover()['choice'],'newer')
        self.assertEqual(display.call_args.args[3],second)

    def test_installed_legacy_lookup_does_not_scan_historical_identities(self):
        import pdf_study_hierarchy_legacy as legacy
        with patch.object(study,'hierarchy',legacy),patch.object(study,'historical_saved',side_effect=AssertionError('No h7 fallback')):
            self.assertIsNone(study.recover(self.folder,self.document))


if __name__=='__main__':unittest.main()
