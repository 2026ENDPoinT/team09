"""Prove repeated empty tiled ornament strips; retain semantic raster sources."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from pdf_tiled_margins import mark_tiled_margins


class Document:
    def __init__(self,pages):self.pages=pages
    def __enter__(self):return self
    def __exit__(self,*args):pass


def fixture():
    blocks=[];pages=[]
    for n in range(3):
        blocks.append({'id':str(n),'page':n+1,'kind':'visual','text':'','wordIds':[],
                       'visualKinds':['raster'],'bbox':[.1,.04,.9,.06]})
        stream=SimpleNamespace(objid=n,get_data=lambda:b'identical small motif')
        images=[{'x0':100+i*100,'x1':200+i*100,'top':40,'bottom':60,
                 'srcsize':(16,16),'stream':stream}for i in range(8)]
        pages.append(SimpleNamespace(width=1000,height=1000,images=images,chars=[],close=lambda:None))
    return blocks,pages


class TiledMarginTests(unittest.TestCase):
    def run_guard(self,blocks,pages):
        with TemporaryDirectory()as folder:
            (Path(folder)/'source.pdf').touch()
            with patch('pdfplumber.open',return_value=Document(pages)):
                return mark_tiled_margins(folder,blocks)

    def test_only_role_metadata_changes_after_three_page_tiled_proof(self):
        blocks,pages=fixture();before=copy.deepcopy(blocks)
        self.assertEqual(self.run_guard(blocks,pages),['0','1','2'])
        self.assertTrue(all(b['planRole']=='decoration'for b in blocks))
        for b,old in zip(blocks,before):
            self.assertEqual({k:v for k,v in b.items()if k!='planRole'},old)

    def test_paid_partition_remains_reusable_against_fresh_extraction(self):
        from pdf_group_partition import validate_partition
        blocks,pages=fixture();fresh=copy.deepcopy(blocks)
        self.run_guard(blocks,pages)
        groups=[{'title':'구조 정보','blocks':blocks}]
        self.assertTrue(validate_partition(fresh,groups)['complete'])

    def test_native_glyphs_or_large_rasters_are_preserved(self):
        for kind in ['glyph','table','different_cells']:
            with self.subTest(kind=kind):
                blocks,pages=fixture()
                for page in pages:
                    if kind=='glyph':page.chars=[{'x0':100,'x1':120,'top':40,'bottom':50}]
                    elif kind=='table':page.images[0]['srcsize']=(320,32)
                    else:
                        for i,image in enumerate(page.images):image['stream']=SimpleNamespace(objid=i,get_data=lambda i=i:bytes([i]))
                before=copy.deepcopy(blocks)
                self.assertEqual(self.run_guard(blocks,pages),[]);self.assertEqual(blocks,before)

    def test_nonmargin_figures_and_text_labels_are_never_candidates(self):
        blocks,pages=fixture()
        blocks[0]['bbox']=[.1,.4,.9,.42];blocks[1]['text']='표의 중요한 범례';blocks[2]['wordIds']=['word']
        before=copy.deepcopy(blocks)
        self.assertEqual(self.run_guard(blocks,pages),[]);self.assertEqual(blocks,before)

    def test_sparse_chart_marks_are_preserved_despite_repeating_counts(self):
        blocks,pages=fixture()
        for page in pages:
            for image in page.images:image['x1']=image['x0']+10
        before=copy.deepcopy(blocks)
        self.assertEqual(self.run_guard(blocks,pages),[]);self.assertEqual(blocks,before)

    def test_missing_or_unsupported_pdf_keeps_all_source_blocks(self):
        blocks,pages=fixture();before=copy.deepcopy(blocks)
        with TemporaryDirectory()as folder:
            (Path(folder)/'source.pdf').touch()
            with patch('pdfplumber.open',side_effect=ValueError('unsupported')):
                self.assertEqual(mark_tiled_margins(folder,blocks),[])
        self.assertEqual(blocks,before)


if __name__=='__main__':unittest.main()
