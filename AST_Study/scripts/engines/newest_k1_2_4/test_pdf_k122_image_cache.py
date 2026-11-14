"""Binary cache cannot change paid-cache dictionaries or request image bytes."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import pdf_image_transport as image
from pdf_k122_image_cache import write, restore


class ImageCacheTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_pixel_identical_result_and_wire_dictionary_on_cache_hit(self):
        for mode in ('RGB', 'RGBA'):
            picture = Image.new(mode, (480, 320), (100, 20, 30) if mode == 'RGB' else (100,20,30,0))
            folder = self.folder / mode
            first = image.encode_crop(picture, cache_dir=folder)
            with patch.object(image, '_webp_bytes', side_effect=AssertionError('must reuse encoding')), \
                 patch('pdf_k122_image_cache.write', side_effect=AssertionError('must hit stored cache')):
                second = image.encode_crop(picture, cache_dir=folder)
            self.assertEqual(first, second)
            self.assertEqual(json.dumps(first), json.dumps(second))
            metadata = json.loads(next(folder.glob('*.json')).read_text())
            self.assertNotIn('data', metadata['result'])
            self.assertEqual(restore(next(folder.glob('*.json')), metadata), first)

    def test_two_keys_share_identical_blob_and_preserve_both_payload_fields(self):
        raw = bytes(range(256)) * 64
        uri = 'data:image/png;base64,' + base64.b64encode(raw).decode()
        result = {'data': uri, 'wireData': uri, 'bytes': len(raw), 'width': 10, 'height': 10}
        checksum = hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
        for name in ('first.json', 'second.json'):
            cache = self.folder / name
            write(cache, name, result, checksum)
            self.assertEqual(restore(cache,json.loads(cache.read_text())), result)
        self.assertEqual(len(list((self.folder/'.encoded-blobs').glob('*.bin'))), 1)
        stored = sum(p.stat().st_size for p in self.folder.rglob('*') if p.is_file())
        self.assertLess(stored, len(json.dumps({'result': result}).encode()) * 2)

    def test_corrupt_or_missing_blob_reencodes_from_unchanged_source(self):
        picture = Image.new('RGB', (200,150), 'white')
        expected = image.encode_crop(picture, cache_dir=self.folder)
        for remove in (False, True):
            blob = next((self.folder/'.encoded-blobs').glob('*.bin'))
            if remove: blob.unlink()
            else: blob.write_bytes(b'corrupted')
            self.assertEqual(image.encode_crop(picture, cache_dir=self.folder), expected)

    def test_inline_legacy_cache_and_path_escape_fail_closed(self):
        legacy = {'result': {'data':'data:image/png;base64,YQ=='}}
        self.assertEqual(restore(self.folder/'old.json', legacy), legacy['result'])
        cache = self.folder/'new.json';write(cache, 'key', legacy['result'], 'checksum')
        value = json.loads(cache.read_text());value['binaryFields']['data']['sha256']='../../other'
        with self.assertRaises(ValueError): restore(cache, value)


if __name__ == '__main__':
    unittest.main()
