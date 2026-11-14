"""Wire compression must preserve pixels, dimensions and the original PNG."""
import base64
import io
import random
import tempfile
import json
from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, features

import pdf_image_transport as transport
import pdf_new_concept_v02_regions as layout
import pdf_ai as ai


class ImageTransportTests(unittest.TestCase):
    def setUp(self):
        rng = random.Random(125)
        palette = [(255, 255, 255), (0, 34, 85), (240, 230, 200), (30, 90, 160), (200, 40, 40)]
        rgb = bytes(channel for _ in range(256*160) for channel in palette[rng.randrange(len(palette))])
        self.image = Image.frombytes('RGB', (256, 160), rgb)
        data = io.BytesIO()
        self.image.save(data, format='PNG')
        self.png = data.getvalue()
        self.assertGreater(len(self.png), transport.MIN_WEBP_PNG_BYTES)

    def assert_wire_pixels(self, result, source):
        prefix, encoded = result['data'].split(',', 1)
        raw = base64.b64decode(encoded)
        self.assertEqual(len(raw), result['bytes'])
        self.assertEqual(prefix, f'data:{result["mimeType"]};base64')
        with Image.open(io.BytesIO(raw)) as decoded:
            self.assertEqual(decoded.size, source.size)
            self.assertEqual(decoded.convert('RGBA').tobytes(), source.convert('RGBA').tobytes())
        self.assertEqual((result['width'], result['height']), source.size)

    def test_default_flag_keeps_original_png_without_extra_encoder_work(self):
        with patch.object(transport, 'LOSSLESS_WEBP', False), \
             patch.object(transport, '_webp_bytes', side_effect=AssertionError('Feature is disabled')):
            result = transport.encode_crop(self.image, self.png)
        self.assertEqual(result['ext'], 'png')
        self.assertEqual(base64.b64decode(result['data'].split(',', 1)[1]), self.png)
        self.assert_wire_pixels(result, self.image)

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_lossless_rgb_transport_preserves_every_pixel_and_original_bytes(self):
        original = self.image.tobytes()
        png = self.png[:]
        result = transport.encode_crop(self.image, self.png, enabled=True)
        self.assertEqual(result['ext'], 'webp')
        self.assertLess(result['bytes'], len(self.png))
        self.assert_wire_pixels(result, self.image)
        self.assertEqual(self.image.tobytes(), original)
        self.assertEqual(self.png, png)

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_compact_wire_copy_preserves_pixels_and_legacy_identity(self):
        result = transport.encode_crop(self.image, self.png, enabled=True)
        with patch.object(transport, '_compact_webp_bytes', side_effect=OSError('Unsupported')):
            legacy = transport.encode_crop(self.image, self.png, enabled=True)
        for field in ('data', 'bytes', 'mimeType', 'ext', 'width', 'height'):
            self.assertEqual(result[field], legacy[field])
        raw = transport._compact_webp_bytes(self.image)
        with Image.open(io.BytesIO(raw)) as decoded:
            self.assertEqual(decoded.convert('RGBA').tobytes(), self.image.convert('RGBA').tobytes())
        if 'wireData' in result:
            self.assertLess(result['wireBytes'], result['bytes'])
            self.assertEqual(base64.b64decode(result['wireData'].split(',', 1)[1]), raw)

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_study_wire_compression_reuses_paid_cache_without_another_call(self):
        original = transport.encode_crop(self.image, self.png, enabled=False)
        compact = transport._compact_webp_bytes(self.image)
        wire = {**original, 'wireData': 'data:image/webp;base64,' + base64.b64encode(compact).decode('ascii'),
                'wireBytes': len(compact)}
        observed = []
        def reply(body):
            observed.append(body)
            return {'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 120, 'completion_tokens': 10}}
        with tempfile.TemporaryDirectory() as folder:
            provider = ai.Provider(Path(folder), True, .1, transport=reply)
            provider.context = {'kind': 'region_study'}
            payload = {'task': 'region_teaching'}
            provider.complete(payload, image=[wire], max_output=100)
            provider.complete(payload, image=[original], max_output=100)
            self.assertEqual(len(observed), 1)
            sent = observed[0]['messages'][1]['content'][1]['image_url']['url']
            self.assertEqual(sent, wire['wireData'])
            self.assertEqual(provider.ledger['requests'][0]['wireImageBytes'], len(compact))

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_new_wire_encoding_cannot_bypass_uncertain_paid_request_guard(self):
        original = transport.encode_crop(self.image, self.png, enabled=False)
        wire = {**original, 'wireData': 'data:image/webp;base64,' +
                base64.b64encode(transport._compact_webp_bytes(self.image)).decode('ascii')}
        attempts = []
        def interrupted(body):
            attempts.append(body)
            raise OSError('Synthetic lost connection')
        with tempfile.TemporaryDirectory() as folder:
            provider = ai.Provider(Path(folder), True, .1, transport=interrupted)
            provider.context = {'kind': 'region_study'}
            payload = {'task': 'region_teaching'}
            with self.assertRaises(ai.AiResponseError):
                provider.complete(payload, image=[original], max_output=100)
            with self.assertRaises(ai.MissingPaidResponseError):
                provider.complete(payload, image=[wire], max_output=100)
            self.assertEqual(len(attempts), 1)

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_rgba_including_hidden_rgb_under_transparency_is_exact(self):
        rgba = self.image.convert('RGBA')
        data = bytearray(rgba.tobytes())
        for i in range(3, len(data), 4):
            data[i] = 0 if i % 7 == 0 else (128 if i % 5 == 0 else 255)
        rgba = Image.frombytes('RGBA', rgba.size, bytes(data))
        for method in (0,1):
            with self.subTest(method=method), patch.object(transport,'WEBP_METHOD',method):
                result = transport.encode_crop(rgba, enabled=True)
                self.assert_wire_pixels(result, rgba)

    def test_unsupported_codec_falls_back_to_the_existing_png(self):
        with patch.object(transport.features, 'check', return_value=False), \
             patch.object(transport, '_webp_bytes', side_effect=AssertionError('Encoder unavailable')):
            result = transport.encode_crop(self.image, self.png, enabled=True)
        self.assertEqual(result['ext'], 'png')
        self.assert_wire_pixels(result, self.image)

    def test_codec_error_falls_back_without_losing_the_existing_png(self):
        with patch.object(transport.features, 'check', return_value=True), \
             patch.object(transport, '_webp_bytes', side_effect=OSError('Unavailable platform encoder')):
            result = transport.encode_crop(self.image, self.png, enabled=True)
        self.assertEqual(result['ext'], 'png')
        self.assertEqual(base64.b64decode(result['data'].split(',', 1)[1]), self.png)

    def test_larger_webp_is_not_selected(self):
        with patch.object(transport.features, 'check', return_value=True), \
             patch.object(transport, '_webp_bytes', return_value=self.png+b'larger'):
            result = transport.encode_crop(self.image, self.png, enabled=True)
        self.assertEqual(result['ext'], 'png')
        self.assert_wire_pixels(result, self.image)

    def test_tiny_images_and_high_precision_modes_skip_the_extra_encoder(self):
        with patch.object(transport, '_webp_bytes', side_effect=AssertionError('Unnecessary encoding')):
            tiny = Image.new('RGB', (12, 12), (30, 60, 100))
            self.assertEqual(transport.encode_crop(tiny, enabled=True)['ext'], 'png')
            gray = self.image.convert('L')
            result = transport.encode_crop(gray, enabled=True)
            self.assertEqual(result['ext'], 'png')
            self.assert_wire_pixels(result, gray)

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_large_crops_skip_second_pass_without_changing_paid_identity(self):
        old = transport.encode_crop(self.image,self.png,enabled=True,compact=True)
        with patch.object(transport,'MAX_COMPACT_PNG_BYTES',len(self.png)-1), \
             patch.object(transport,'_compact_webp_bytes',side_effect=AssertionError('Second pass is over budget')):
            fast = transport.encode_crop(self.image,self.png,enabled=True)
        for field in ('data','bytes','mimeType','ext','width','height'):
            self.assertEqual(fast[field],old[field])
        self.assertNotIn('wireData',fast)
        self.assert_wire_pixels(fast,self.image)

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_repeated_crop_uses_disk_cache_and_corruption_reencodes(self):
        with tempfile.TemporaryDirectory() as folder:
            first = transport.encode_crop(self.image,self.png,enabled=True,cache_dir=folder)
            with patch.object(transport,'_webp_bytes',side_effect=AssertionError('Repeated encoding')), \
                 patch.object(transport,'_compact_webp_bytes',side_effect=AssertionError('Repeated wire encoding')):
                again = transport.encode_crop(self.image,self.png,enabled=True,cache_dir=folder)
            self.assertEqual(first,again)
            cached = next(Path(folder).glob('*.json'))
            stored=json.loads(cached.read_text());stored['result']['data']='damaged'
            cached.write_text(json.dumps(stored))
            fixed=transport.encode_crop(self.image,self.png,enabled=True,cache_dir=folder)
            self.assertEqual(fixed,first)

    def test_unwritable_encoding_cache_does_not_block_a_request(self):
        with tempfile.TemporaryDirectory() as folder:
            blocked=Path(folder)/'file';blocked.write_text('not a directory')
            result=transport.encode_crop(self.image,self.png,enabled=False,cache_dir=blocked)
            self.assert_wire_pixels(result,self.image)

    def test_explicit_png_override_wins_over_the_global_feature_flag(self):
        with patch.object(transport, 'LOSSLESS_WEBP', True), \
             patch.object(transport, '_webp_bytes', side_effect=AssertionError('Explicit override')):
            result = transport.encode_crop(self.image, self.png, enabled=False)
        self.assertEqual(result['ext'], 'png')

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_renderer_persists_original_png_before_encoding_only_request_bytes(self):
        @contextmanager
        def page_image(*args, **kwargs):
            with self.image.copy() as page:
                yield page

        original_encoder = transport._webp_bytes
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)/'cache'

            def encoder(crop):
                pngs = list((cache/'crops').glob('*.png'))
                self.assertEqual(len(pngs), 1)
                with Image.open(pngs[0]) as persisted:
                    self.assertEqual(persisted.convert('RGBA').tobytes(), self.image.convert('RGBA').tobytes())
                return original_encoder(crop)

            with patch.object(layout, 'page_image', side_effect=page_image), \
                 patch.object(transport, 'LOSSLESS_WEBP', True), \
                 patch.object(transport, '_webp_bytes', side_effect=encoder):
                images, manifest = layout.render_crops(Path(folder), [
                    {'id': 'source', 'page': 1, 'bbox': [0, 0, 1, 1], 'kind': 'visual'}], cache)
            self.assertEqual(images[0]['ext'], 'webp')
            self.assert_wire_pixels(images[0], self.image)
            self.assertEqual(Path(manifest[0]['path']).suffix, '.png')
            self.assertEqual(Path(manifest[0]['path']).read_bytes(), self.png)
            self.assertEqual((manifest[0]['width'], manifest[0]['height']), self.image.size)
            self.assertEqual(manifest[0]['blockIds'], ['source'])

    @unittest.skipUnless(features.check('webp'), 'This platform has no WebP encoder')
    def test_real_provider_accepts_png_and_lossless_webp_with_equal_dimension_bounds(self):
        observed = []

        def fake_transport(body):
            observed.append(body)
            return {'choices': [{'message': {'content': json.dumps({'answer': 'fixture'})},
                                  'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 120, 'completion_tokens': 10}}

        bounds = []
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(ai.urllib.request, 'urlopen', side_effect=AssertionError('Network forbidden')) as network, \
             patch.object(ai, 'api_key', side_effect=AssertionError('No credentials needed')) as credentials:
            for enabled in [False, True]:
                image = transport.encode_crop(self.image, self.png, enabled=enabled)
                provider = ai.Provider(Path(folder)/str(enabled), True, .1, transport=fake_transport)
                provider.rate_directory = Path(folder)/'private-rate-state'
                provider.context = {'kind': 'region_study'}
                result = provider.complete({'task': 'fixture'}, image=[image], max_output=100,
                                           system_prompt='Offline synthetic image request.')
                self.assertEqual(result, {'answer': 'fixture'})
                self.assertEqual(provider.ledger['requests'][0]['state'], 'settled')
                bounds.append(provider.ledger['requests'][0]['inputTokenBound'])
                content = observed[-1]['messages'][-1]['content']
                sent = next(item['image_url']['url'] for item in content if item['type'] == 'image_url')
                self.assertEqual(sent, image['data'])
                self.assertTrue(sent.startswith('data:image/webp;' if enabled else 'data:image/png;'))
                self.assert_wire_pixels(image, self.image)
            network.assert_not_called()
            credentials.assert_not_called()
        self.assertEqual(len(observed), 2)
        self.assertEqual(bounds[0], bounds[1])

    def test_real_provider_still_rejects_an_unknown_mime_before_sending(self):
        image = transport.encode_crop(self.image, self.png, enabled=False)
        image['data'] = image['data'].replace('data:image/png;', 'data:text/plain;', 1)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(ai.urllib.request, 'urlopen', side_effect=AssertionError('Network forbidden')):
            send = unittest.mock.Mock()
            provider = ai.Provider(Path(folder), True, .1, transport=send)
            provider.context = {'kind': 'region_study'}
            with self.assertRaises(ValueError):
                provider.complete({'task': 'fixture'}, image=[image], max_output=100)
            send.assert_not_called()
            self.assertEqual(provider.ledger['requests'], [])


if __name__ == '__main__':
    unittest.main()
