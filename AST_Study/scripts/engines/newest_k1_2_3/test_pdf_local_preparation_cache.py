"""Offline cache correctness, invalidation and resource lifetime checks."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import pdf_local_preparation_cache as cache
import pdf_new_concept_v02_regions as regions
import pdf_ver99_cost_estimate as costs


class LocalPreparationCacheTests(unittest.TestCase):
    def test_png_bytes_unchanged_and_repeat_skips_encoder(self):
        with tempfile.TemporaryDirectory() as tmp, Image.new('RGB',(200,100),'white') as image:
            expected=io.BytesIO();image.save(expected,format='PNG')
            self.assertEqual(cache.crop_png(image,tmp),expected.getvalue())
            with patch.object(Image.Image,'save',side_effect=AssertionError('encoded twice')):
                self.assertEqual(cache.crop_png(image,tmp),expected.getvalue())
            image.putpixel((0,0),(1,2,3))
            self.assertNotEqual(cache.crop_png(image,tmp),expected.getvalue())

    def test_corrupt_png_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp, Image.new('RGB',(20,20),'white') as image:
            expected=cache.crop_png(image,tmp)
            next(Path(tmp).glob('*.png')).write_bytes(b'broken')
            self.assertEqual(cache.crop_png(image,tmp),expected)

    def test_history_invalidates_on_edit_deletion_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.json';source.write_text('1')
            calculate=lambda:[{'value':source.read_text() if source.exists() else None}]
            value=cache.history_sample(root,'model','prompt',[source],calculate)
            with patch.object(cache,'_digest',wraps=cache._digest):
                self.assertEqual(cache.history_sample(root,'model','prompt',[source],
                    lambda:self.fail('recomputed unchanged history')),value)
            value[0]['value']='caller mutation'
            self.assertEqual(cache.history_sample(root,'model','prompt',[source],calculate),[{'value':'1'}])
            source.write_text('2')
            self.assertEqual(cache.history_sample(root,'model','prompt',[source],calculate),[{'value':'2'}])
            next((root/'generated/local-cost-history').glob('*.json')).write_text('broken')
            self.assertEqual(cache.history_sample(root,'model','prompt',[source],calculate),[{'value':'2'}])
            source.unlink()
            self.assertEqual(cache.history_sample(root,'model','prompt',[source],calculate),[{'value':None}])

    def test_history_new_run_and_excluded_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'doc';folder.mkdir();(folder/'document.json').write_text('{}')
            def calculate(*args,**kwargs):return [{'runs':len(list(folder.glob('generated/new-concept-v99/*/result.json')))}]
            with patch.object(costs,'_uncached_samples',side_effect=calculate) as compute:
                self.assertEqual(costs.samples(root,'m','v'),[{'runs':0}])
                self.assertEqual(costs.samples(root,'m','v'),[{'runs':0}]);self.assertEqual(compute.call_count,1)
                result=folder/'generated/new-concept-v99/new/result.json';result.parent.mkdir(parents=True);result.write_text('{}')
                self.assertEqual(costs.samples(root,'m','v'),[{'runs':1}]);self.assertEqual(compute.call_count,2)
                self.assertEqual(costs.samples(root,'m','v','doc'),[])

    def test_adjacent_crops_decode_once_and_close_on_error(self):
        blocks=[{'id':str(i),'page':1,'bbox':[.1,.1+i*.3,.4,.2+i*.3],
                 'kind':'heading','text':'heading'} for i in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            def make(*args):return Image.new('RGB',(300,300),'white')
            with patch.object(regions,'page_image',side_effect=make) as decode:
                images,manifest=regions.render_crops(Path(tmp),blocks,Path(tmp)/'cache')
                self.assertEqual(decode.call_count,1);self.assertEqual(len(images),2)
            image=make()
            with patch.object(regions,'page_image',return_value=image), \
                 patch.object(cache,'crop_png',side_effect=OSError('injected')):
                with self.assertRaises(OSError):regions.render_crops(Path(tmp),blocks,Path(tmp)/'failure')
            with self.assertRaises(ValueError):image.getpixel((0,0))


if __name__=='__main__':unittest.main()
