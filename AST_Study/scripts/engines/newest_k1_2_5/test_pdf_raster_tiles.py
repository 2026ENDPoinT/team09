"""Offline raster coalescing: keep all pixels, words, separate figures and paid caches."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_new_concept_v02_regions as layout
import pdf_new_concept_ver99_study as study


def raster(box):return {'bbox':box,'kind':'raster'}


class RasterTileTests(unittest.TestCase):
    def assert_preserved(self,regions,merged):
        for region in regions:
            self.assertTrue(any(layout.contains(item['bbox'],region['bbox']) for item in merged),region)

    def test_touching_mask_grid_becomes_one_full_crop(self):
        tiles=[raster([.1+x*.01,.05+y*.006,.1+(x+1)*.01,.05+(y+1)*.006])
               for x in range(70) for y in range(2)]
        result=layout.merge_visuals(tiles)
        self.assertEqual(len(result),1);self.assert_preserved(tiles,result)
        self.assertEqual(result[0]['kinds'],['raster'])
        self.assertAlmostEqual(result[0]['bbox'][0],.1);self.assertAlmostEqual(result[0]['bbox'][2],.8)

    def test_scanlines_with_dedup_gaps_keep_full_news_screenshot(self):
        strips=[raster([.2,.01+i*.0048,.8,.0112+i*.0048]) for i in range(160)]
        merged=layout.merge_visuals(strips)
        self.assertEqual(len(merged),1);self.assert_preserved(strips,merged)
        self.assertEqual(merged[0]['bbox'],[.2,.01,.8,.0112+159*.0048])

    def test_whitespace_between_independent_figures_is_not_crossed(self):
        regions=[raster([.1,.2,.4,.5]),raster([.42,.2,.72,.5]),raster([.1,.53,.4,.83])]
        merged=layout.merge_visuals(regions)
        self.assertEqual(len(merged),3);self.assert_preserved(regions,merged)

    def test_corner_contacts_and_vector_or_table_neighbors_stay_separate(self):
        for regions in ([raster([.1,.1,.2,.2]),raster([.2,.2,.3,.3])],
                        [{'bbox':[.1,.1,.2,.2],'kind':'table'},raster([.2,.1,.3,.2])],
                        [{'bbox':[.1,.1,.2,.2],'kind':'vector'},raster([.2,.1,.3,.2])]):
            self.assertEqual(len(layout.merge_visuals(regions)),2)

    def test_existing_overlapping_table_and_raster_are_retained_together(self):
        regions=[raster([.1,.1,.6,.6]),{'bbox':[.4,.4,.9,.8],'kind':'table'}]
        merged=layout.merge_visuals(regions)
        self.assertEqual(merged,[{'bbox':[.1,.1,.9,.8],'kinds':['raster','table']}])

    def test_disjoint_text_words_and_visual_words_survive_real_fragment_ownership(self):
        class Page:
            width=height=1000
        words=[{'text':'밖의 본문','x0':100,'top':700,'x1':300,'bottom':720,'size':12,'fontname':'regular'},
               {'text':'사진 설명','x0':200,'top':220,'x1':300,'bottom':240,'size':12,'fontname':'regular'}]
        tiles=[raster([.1+i*.01,.1,.11+i*.01,.5]) for i in range(60)]
        with patch.object(layout,'repaired_textmap',return_value=(None,[],{})),\
             patch('pdfplumber.utils.extract_words',return_value=copy.deepcopy(words)),\
             patch.object(layout,'page_zones',return_value=[[0,0,1,1]]),\
             patch.object(layout,'image_regions',return_value=tiles),\
             patch.object(layout,'table_regions',return_value=[]),\
             patch.object(layout,'vector_regions',return_value=[]):
            blocks,native=layout.fragment_page(Page(),{'number':1,'nativeText':'본문'},True)
        owned=[wid for block in blocks for wid in block['wordIds']]
        self.assertCountEqual(owned,[w['id'] for w in native]);self.assertEqual(len(owned),len(set(owned)))
        self.assertEqual(sum(b['kind']=='visual' for b in blocks),1)
        self.assertTrue(any('밖의 본문' in b['text'] and not b['hasVisual'] for b in blocks))

    def test_completed_paid_result_is_reused_across_layout_upgrade(self):
        document={'documentId':'doc','fingerprint':'source-fp','pages':[{'number':1,'label':'1'}]}
        saved={'documentId':'doc','sourceFingerprint':'source-fp','strategy':'new-concept-v99',
               'scope':'document','page':0,'processingComplete':True,'sections':[],'concepts':[]}
        class NoRemote:
            model='gpt-6-luna'
            ledger={'requests':[]}
            def complete(self,*args,**kw):raise AssertionError('No paid request may be made')
        with tempfile.TemporaryDirectory() as folder:
            latest=study.latest_path(folder,'new-concept-v99','document',0);latest.parent.mkdir(parents=True)
            latest.write_text(json.dumps(saved))
            with patch.object(study,'display_saved',side_effect=lambda folder,doc,value,cache:value),\
                 patch.object(study,'extract',side_effect=AssertionError('Saved prose must not be re-extracted')):
                result=study.generate(Path(folder),document,NoRemote())
            self.assertTrue(result['cacheHit']);self.assertTrue(result['processingComplete'])


if __name__=='__main__':unittest.main()
