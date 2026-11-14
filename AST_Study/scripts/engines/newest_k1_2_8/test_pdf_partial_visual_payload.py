"""Mixed visual/native targets retain their full image scope on the wire."""
import copy
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study


class PartialVisualPayloadTests(unittest.TestCase):
    def setUp(self):
        enabled = patch.object(study, 'PARTIAL_NATIVE_VISUAL_HINTS', True)
        enabled.start();self.addCleanup(enabled.stop)

    def fixture(self):
        blocks = [
            {'id': 'v2p11f0', 'page': 11, 'kind': 'heading', 'text': '가운데귀'},
            {'id': 'v2p11f1', 'page': 11, 'kind': 'visual', 'text': '속귀신경',
             'hasVisual': True, 'visualOnly': False, 'bbox': [.03, .13, .95, .82]},
            {'id': 'v2p11f2', 'page': 11, 'kind': 'text', 'hasVisual': False,
             'text': '고실에는 공기가 차 있어요. $x+y$ code {"hasVisual":true}'},
            {'id': 'v2p11f3', 'page': 11, 'kind': 'visual', 'text': '',
             'hasVisual': True, 'visualOnly': True, 'bbox': [.93, .92, .98, .98]}]
        job = {'title': '가운데귀의 구조', 'blocks': blocks}
        crops = [{'page': 11, 'blockIds': [b['id'] for b in blocks],
                  'path': '/not-read/image.png', 'bbox': [0, 0, 1, 1]}]
        context = {'pageCount': 16, 'pageCues': ['시각기관', '귀']}
        neighbors = [{'page': 10, 'text': '귀의 세 구획', 'backgroundOnly': True}]
        return job, crops, context, neighbors

    def test_partial_native_word_cannot_describe_the_whole_substantial_image(self):
        args = self.fixture();before = copy.deepcopy(args)
        payload = study.teaching_payload(*args)
        self.assertEqual(args, before)
        image = payload['blocks'][1]
        self.assertEqual(image['id'], 'v2p11f1')
        self.assertEqual(image['text'], '속귀신경')
        self.assertEqual(image['kind'], 'visual')
        self.assertIs(image['hasVisual'], True)
        self.assertIs(image['visualContentRequiresReading'], True)
        self.assertIs(image['nativeTextIsPartialVisualExtraction'], True)
        self.assertEqual(payload['visualReadingHint'], study.PARTIAL_NATIVE_VISUAL_HINT)
        self.assertEqual(payload['crops'], [{'page': 11, 'blockIds': [b['id'] for b in args[0]['blocks']]}])
        self.assertEqual(payload['neighboringContext'], args[3])

    def test_native_text_and_tiny_icons_are_not_promoted_to_substantial_visuals(self):
        payload = study.teaching_payload(*self.fixture())
        native = payload['blocks'][2]
        self.assertEqual(native['kind'], 'text')
        self.assertNotIn('hasVisual', native)
        self.assertNotIn('visualContentRequiresReading', native)
        self.assertNotIn('nativeTextIsPartialVisualExtraction', native)
        self.assertEqual(native['text'], self.fixture()[0]['blocks'][2]['text'])
        icon = payload['blocks'][3]
        self.assertIs(icon['hasVisual'], True)  # Existing visualOnly transport.
        self.assertNotIn('visualContentRequiresReading', icon)
        self.assertNotIn('nativeTextIsPartialVisualExtraction', icon)

    def test_image_only_and_mixed_native_kind_visuals_keep_geometry_and_source_scope(self):
        job, crops, context, neighbors = self.fixture()
        job['blocks'] = [
            {'id': 'v2p1f0', 'page': 1, 'kind': 'text', 'text': '부분 native 라벨',
             'hasVisual': True, 'visualOnly': False, 'bbox': [.1, .1, .9, .8]},
            {'id': 'v2p2f0', 'page': 2, 'kind': 'page', 'text': '', 'hasVisual': True,
             'geometryFallback': True, 'visualOnly': True, 'bbox': [0, 0, 1, 1]}]
        before = copy.deepcopy((job, crops, context, neighbors))
        payload = study.teaching_payload(job, crops, context, neighbors)
        mixed, image = payload['blocks']
        self.assertEqual(mixed['kind'], 'text')
        self.assertTrue(mixed['hasVisual'] and mixed['visualContentRequiresReading'])
        self.assertTrue(mixed['nativeTextIsPartialVisualExtraction'])
        self.assertEqual(image['kind'], 'visual')  # Existing visualOnly rule.
        self.assertTrue(image['hasVisual'] and image['visualContentRequiresReading'])
        self.assertNotIn('nativeTextIsPartialVisualExtraction', image)
        self.assertEqual((job, crops, context, neighbors), before)

    def test_native_only_and_image_only_jobs_do_not_get_partial_text_hint(self):
        for index in (2, 3):
            job, crops, context, neighbors = self.fixture()
            job['blocks'] = [job['blocks'][index]]
            payload = study.teaching_payload(job, crops, context, neighbors)
            self.assertNotIn('visualReadingHint', payload)
        job['blocks'] = [{'id': 'v2p1f0', 'page': 1, 'kind': 'page', 'text': '',
                          'hasVisual': True, 'geometryFallback': True}]
        payload = study.teaching_payload(job, crops, context, neighbors)
        self.assertTrue(payload['blocks'][0]['visualContentRequiresReading'])
        self.assertNotIn('visualReadingHint', payload)

    def test_payload_version_separates_generation_and_teaching_cache_not_planning(self):
        document = {'documentId': 'fixture', 'fingerprint': 'fixture-v1'}
        args = (document, 'new-concept-v99', 'model', 'document', 0)
        original = (study.identity(*args), study.teaching_identity(), study.planner_identity('model'))
        with patch.object(study, 'TEACHING_PAYLOAD_VERSION', 'different-payload-version'):
            changed = (study.identity(*args), study.teaching_identity(), study.planner_identity('model'))
        self.assertNotEqual(original[0], changed[0])
        self.assertNotEqual(original[1], changed[1])
        self.assertEqual(original[2], changed[2])
        with patch.object(study, 'PARTIAL_NATIVE_VISUAL_HINT', 'different explicit scope hint'):
            self.assertNotEqual(original[0], study.identity(*args))
            self.assertNotEqual(original[1], study.teaching_identity())

    def test_default_payload_and_none_teaching_identity_are_exact_original_shape(self):
        job, crops, context, neighbors = self.fixture()
        with patch.multiple(study, PARTIAL_NATIVE_VISUAL_HINTS=False,
                            NEUTRAL_VISUAL_HINT=False, STATEMENT_UNCERTAINTY=False,
                            OWNED_TEACHING=False, COMPACT_TABLE_SETUP=False,
                            STUDY_TEMPERATURE=None, IMAGE_REGION_LABELS=False,
                            IMAGE_SOURCE_LABELS=False, SOURCE_COVERAGE_HINT=False,
                            SOURCE_FACTS=False, VISUAL_TEACHING=False,
                            STUDY_REASONING_EFFORT='none'):
            expected = {'task':'region_teaching','titleHint':job['title'],
                'blocks':[{**{k:b[k] for k in ('id','page','kind','text','planRole') if k in b},
                    **({'kind':'visual','hasVisual':True} if b.get('visualOnly') and b.get('hasVisual') else {})}
                    for b in job['blocks']],
                'entryHints':[{'title':study.entry_label(b),'startsAt':b['id']}
                              for b in job['blocks'] if study.entry_label(b)],
                'crops':[{'page':c['page'],'blockIds':c.get('blockIds',[])} for c in crops],
                'documentContext':{'pageCount':context.get('pageCount'),
                                   'openingCues':context.get('pageCues',[])[:1]},
                'neighboringContext':neighbors}
            self.assertEqual(study.teaching_payload(job,crops,context,neighbors), expected)
            original_teaching = study.digest([study.STUDY_PROMPT,study.STUDY_FORMAT])
            self.assertEqual(study.teaching_identity(), original_teaching)
            args = ({'documentId':'fixture','fingerprint':'fixture-v1'},
                    'new-concept-v99','model','document',0)
            original_generation = study.identity(*args)
            with patch.object(study,'TEACHING_PAYLOAD_VERSION','different-version'), \
                 patch.object(study,'PARTIAL_NATIVE_VISUAL_HINT','different hint'):
                self.assertEqual(study.teaching_identity(),original_teaching)
                self.assertEqual(study.identity(*args),original_generation)


if __name__ == '__main__':
    unittest.main()
