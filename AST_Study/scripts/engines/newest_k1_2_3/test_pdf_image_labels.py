"""Synthetic image/source-label transport checks; no network, credentials or user PDFs."""
import copy
import json
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pdf_ai as ai
import pdf_new_concept_ver99_study as study
import test_pdf_speed_pipeline as pipeline_fixtures


def response():
    return {'choices': [{'message': {'content': '{"answer":"fixture"}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 120, 'completion_tokens': 30,
                      'prompt_tokens_details': {'cached_tokens': 0}}}


def image(index, label=None):
    value = {'width': 320, 'height': 240, 'bytes': 3,
             'data': 'data:image/png;base64,' + ('QUJD' if index == 0 else 'REVG')}
    if label is not None:
        value['sourceLabel'] = label
    return value


class ImageLabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)/'document'
        self.transport = Mock(side_effect=lambda _: response())
        self.provider = ai.Provider(self.folder, True, 1, transport=self.transport)
        self.provider.context = {'kind': 'region_study'}
        self.payload = {'task': 'region_teaching', 'blocks': [
            {'id': 'a', 'page': 2}, {'id': 'b', 'page': 16}],
            'crops': [{'page': 2, 'blockIds': ['a']}, {'page': 16, 'blockIds': ['b']}]}
        self.options = {'max_output': 100, 'system_prompt': 'Synthetic source-label test.'}
        self.labels = ['Target image 1 · {"page": 2, "blockIds": ["a"]}',
                       'Target image 2 · {"page": 16, "blockIds": ["b"]}']
        self.opener = patch.object(ai.urllib.request, 'urlopen',
                                  side_effect=AssertionError('Network forbidden')).start()
        self.socket = patch.object(socket.socket, 'connect',
                                  side_effect=AssertionError('Network forbidden')).start()
        self.addCleanup(patch.stopall)

    def test_each_label_immediately_precedes_its_image_in_original_order(self):
        images = [image(i, label) for i, label in enumerate(self.labels)]
        before = copy.deepcopy((images, self.payload))
        self.provider.complete(self.payload, image=images, **self.options)
        content = self.transport.call_args.args[0]['messages'][1]['content']
        self.assertEqual([part['type'] for part in content],
                         ['text', 'text', 'image_url', 'text', 'image_url'])
        self.assertEqual(json.loads(content[0]['text']), self.payload)
        self.assertEqual([content[1]['text'], content[3]['text']], self.labels)
        self.assertEqual([content[2]['image_url']['url'], content[4]['image_url']['url']],
                         [value['data'] for value in images])
        self.assertEqual((images, self.payload), before)
        self.opener.assert_not_called()

    def test_utf8_label_bytes_and_framing_increase_reserved_input_bound(self):
        plain = [image(0), image(1)]
        labelled = [image(i, label) for i, label in enumerate(self.labels)]
        # Isolate explicit sourceLabel accounting from automatic ownership labels.
        with patch('pdf_json_wire.label_images', side_effect=lambda body, task: (body, 0)):
            self.provider.complete(self.payload, image=plain, **self.options)
        first = self.provider.ledger['requests'][-1]
        self.provider.complete(self.payload, image=labelled, **self.options)
        second = self.provider.ledger['requests'][-1]
        # Image placeholders must carry the same labels as transmitted content;
        # count the added text records plus JSON list separators, not image bytes.
        added_bytes = sum(len(json.dumps({'type': 'text', 'text': label},
                                         ensure_ascii=False).encode('utf-8')) + 2
                          for label in self.labels)
        self.assertEqual(second['inputTokenBound'] - first['inputTokenBound'], added_bytes)
        self.assertEqual(second['imageInputTokenEstimate'], first['imageInputTokenEstimate'])
        self.assertEqual(self.transport.call_count, 2)
        self.assertGreater(second['reservedUsd'], first['reservedUsd'])

    def test_automatic_ownership_labels_are_included_in_reserved_input_bound(self):
        images = [image(0), image(1)]
        other = ai.Provider(self.folder/'unlabelled', True, 1, transport=self.transport)
        with patch('pdf_json_wire.label_images', side_effect=lambda body, task: (body, 0)):
            other.complete(self.payload, image=images, **self.options)
        baseline = other.ledger['requests'][-1]
        self.provider.complete(self.payload, image=images, **self.options)
        labelled = self.provider.ledger['requests'][-1]
        content = self.transport.call_args.args[0]['messages'][1]['content']
        labels = [part for part in content[1:] if part['type'] == 'text']
        self.assertEqual(len(labels), 2)
        added_bytes = sum(len(json.dumps(part, ensure_ascii=False).encode('utf-8')) + 2
                          for part in labels)
        self.assertEqual(labelled['inputTokenBound'] - baseline['inputTokenBound'], added_bytes)
        self.assertEqual(labelled['imageInputTokenEstimate'], baseline['imageInputTokenEstimate'])

    def test_unlabelled_images_keep_the_old_wire_shape_and_label_is_per_image_optional(self):
        self.provider.complete(self.payload, image=[image(0), image(1, self.labels[1])], **self.options)
        content = self.transport.call_args.args[0]['messages'][1]['content']
        self.assertEqual([part['type'] for part in content], ['text', 'image_url', 'text', 'image_url'])
        self.assertEqual(content[2]['text'], self.labels[1])
        self.assertEqual(content[1]['image_url']['url'], image(0)['data'])

    def test_label_character_limit_is_validated_before_any_reservation_or_send(self):
        for invalid in ('', 'x' * 2049, 123, {'page': 2}, ['a']):
            with self.subTest(label_type=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    self.provider.complete(self.payload, image=image(0, invalid), **self.options)
        self.assertEqual(self.provider.ledger['requests'], [])
        self.transport.assert_not_called()
        self.opener.assert_not_called()
        self.provider.complete(self.payload, image=image(0, '출' * 2048), **self.options)
        self.transport.assert_called_once()

    def test_source_label_is_part_of_cache_identity_and_identical_repeats_are_free(self):
        original = [image(0, self.labels[0])]
        self.provider.complete(self.payload, image=original, **self.options)
        self.provider.complete(self.payload, image=copy.deepcopy(original), **self.options)
        self.assertEqual(self.transport.call_count, 1)
        revised = [image(0, 'Target image 1 · {"page": 16, "blockIds": ["b"]}')]
        self.provider.complete(self.payload, image=revised, **self.options)
        self.assertEqual(self.transport.call_count, 2)
        self.assertEqual(len(self.provider.ledger['requests']), 2)

    def test_real_teaching_pipeline_labels_follow_crop_order_and_alias_source_ids(self):
        fixture = pipeline_fixtures.CropPipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.groups = [{'title': '그림 세 부분', 'blocks': fixture.blocks}]
        captured = []

        def crops(blocks):
            # Deliberately different from block/page order. Labels must stay
            # paired with these original pixels, never sorted independently.
            order = [2, 0, 1]
            return ([image(i % 2) for i in order],
                    [{'page': blocks[i]['page'], 'blockIds': [blocks[i]['id']]} for i in order])

        def complete(payload, **kwargs):
            images = kwargs['image']
            for index, value in enumerate(images):
                prefix = f'Target image {index + 1} · '
                self.assertTrue(value['sourceLabel'].startswith(prefix))
                metadata = json.loads(value['sourceLabel'][len(prefix):])
                self.assertEqual(metadata, payload['crops'][index])
                self.assertEqual(set(metadata), {'page', 'blockIds'})
                self.assertNotIn(str(fixture.folder), value['sourceLabel'])
                self.assertLessEqual(len(value['sourceLabel']), 2048)
                captured.append(metadata)
            concepts = [fixture.reply(block['id'])['concepts'][0] for block in payload['blocks']]
            return {**fixture.reply(payload['blocks'][0]['id']), 'concepts': concepts}

        with patch.object(study, 'JOB_CROP_LIMIT', 4), \
             patch.object(study, 'JOB_WEIGHT_LIMIT', 10000):
            result, cache = fixture.run_pipeline(lambda _: None, complete, crop_result=crops,
                wire_options={'SOURCE_ID_ALIASES': True, 'IMAGE_SOURCE_LABELS': True,
                              'IMAGE_REGION_LABELS': True})
        self.assertEqual(captured, [{'page': 3, 'blockIds': ['c']},
                                    {'page': 1, 'blockIds': ['a']},
                                    {'page': 2, 'blockIds': ['b']}])
        references = {entry['sourceId'] for concept in result['concepts']
                      for part in concept['entries'] for entry in part['evidence']}
        self.assertEqual(references, {'source0', 'source1', 'source2'})
        canonical = json.loads(next(cache.glob('response-*.json')).read_text())
        self.assertEqual({source for concept in canonical['concepts'] for source in concept['blockIds']},
                         {'source0', 'source1', 'source2'})

    def test_canonical_response_cache_is_not_alias_decoded_or_relabelled_on_reuse(self):
        fixture = pipeline_fixtures.CropPipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        def forbidden(*args, **kwargs):
            raise AssertionError('Canonical paid replies must not be rendered or sent again')

        result, cache = fixture.run_pipeline(forbidden, forbidden, cached=True,
            wire_options={'SOURCE_ID_ALIASES': True, 'IMAGE_SOURCE_LABELS': True,
                          'OWNED_TEACHING': True})
        self.assertTrue(result['processingComplete'])
        references = {entry['sourceId'] for concept in result['concepts']
                      for part in concept['entries'] for entry in part['evidence']}
        self.assertEqual(references, {'source0', 'source1', 'source2'})
        self.assertEqual(result['runUsage']['requests'], 0)
        self.assertEqual([event for event in fixture.events if event[0] in {'api', 'crop_start'}], [])
        for path in cache.glob('response-*.json'):
            saved = json.loads(path.read_text())
            self.assertTrue(saved['concepts'][0]['blockIds'][0].startswith('source'))
            self.assertNotIn('sourceLabel', path.read_text())


class VisualRegionLabelTests(unittest.TestCase):
    def block(self, source, box, page=16, visual=True):
        return {'id': source, 'page': page, 'bbox': box, 'hasVisual': visual,
                'kind': 'visual' if visual else 'text', 'text': ''}

    def labels(self, blocks, crops, wire_ids=None):
        payload = {'blocks': [{'id': (wire_ids or {}).get(block['id'], block['id'])}
                              for block in blocks],
                   'crops': [{'page': crop['page'], 'blockIds': [
                       (wire_ids or {}).get(source, source) for source in crop['blockIds']]}
                             for crop in crops]}
        job = {'blocks': blocks}
        before = copy.deepcopy((job, payload, crops))
        with patch.object(study, 'IMAGE_REGION_LABELS', True):
            result = study.image_source_label_metadata(job, payload, crops)
        self.assertEqual((job, payload, crops), before)
        return result, job, payload

    def test_right_hand_figure_is_located_without_marking_body_or_tiny_icons(self):
        blocks = [self.block('figure', [.32, .04, .99, .98]),
                  self.block('body', [.03, .04, .3, .95], visual=False),
                  self.block('speaker', [.94, .93, .98, .97]),
                  self.block('other-page', [0., 0., 1., 1.], page=15)]
        crops = [{'page': 16, 'bbox': [0., 0., 1., 1.],
                  'blockIds': [block['id'] for block in blocks]}]
        result, job, payload = self.labels(blocks, crops)
        self.assertEqual(result[0]['visualRegions'], [
            {'blockId': 'figure', 'box': [.32, .04, .99, .98]}])
        with patch.object(study, 'IMAGE_REGION_LABELS', False):
            self.assertEqual(study.image_source_label_metadata(job, payload, crops), payload['crops'])
        # Old lightweight fixtures have no rendered crop box. Keep their exact
        # old metadata instead of inventing a full-page geometry.
        self.assertNotIn('visualRegions', self.labels(blocks, [
            {'page': 16, 'blockIds': ['figure']}])[0][0])

    def test_partially_clipped_visuals_are_clamped_and_relative_values_are_rounded(self):
        blocks = [self.block('clipped', [.1, .1, .9, .9]),
                  self.block('inside', [.3, .3, .6, .7]),
                  self.block('outside', [.8, .1, .95, .2])]
        crops = [{'page': 16, 'bbox': [.25, .2, .75, .8],
                  'blockIds': [block['id'] for block in blocks]}]
        result, _, _ = self.labels(blocks, crops)
        self.assertEqual(result[0]['visualRegions'], [
            {'blockId': 'clipped', 'box': [0., 0., 1., 1.]},
            {'blockId': 'inside', 'box': [.1, .1667, .7, .8333]}])

    def test_wire_aliases_follow_original_block_order_and_reordered_crop_pixels(self):
        blocks = [self.block('v2p16f1', [.4, .1, .9, .9]),
                  self.block('v2p6f1', [.1, .2, .6, .8], page=6)]
        # The pixel/crop order is intentionally opposite to the job order.
        crops = [{'page': 6, 'bbox': [0., 0., 1., 1.], 'blockIds': ['v2p6f1']},
                 {'page': 16, 'bbox': [0., 0., 1., 1.], 'blockIds': ['v2p16f1']}]
        result, _, _ = self.labels(blocks, crops, {'v2p16f1': 'a', 'v2p6f1': 'b'})
        self.assertEqual(result, [
            {'page': 6, 'blockIds': ['b'], 'visualRegions': [
                {'blockId': 'b', 'box': [.1, .2, .6, .8]}]},
            {'page': 16, 'blockIds': ['a'], 'visualRegions': [
                {'blockId': 'a', 'box': [.4, .1, .9, .9]}]}])


if __name__ == '__main__':
    unittest.main()
