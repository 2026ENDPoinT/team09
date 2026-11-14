"""Offline image-ownership, glyph completeness and risky-source preservation."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pdf_study_text_input import VERSION, native_prose_verified, select_images, render_blocks


def block(**extra):
    return {'id':'a','page':1,'kind':'text','bbox':[.1,.1,.8,.3],
            'text':'가족이 사회의 변화를 경험해요.', 'hasVisual':False, **extra}


def page(**extra):
    return SimpleNamespace(width=100,height=100,rotation=0,images=[],curves=[],rects=[],lines=[],**extra)


def glyph(**extra):
    return {'text':'가','fontname':'KoPubBatang','upright':True,
            'x0':10,'x1':20,'top':10,'bottom':25, **extra}


class TextInputTests(unittest.TestCase):
    def test_prose_requires_matching_glyphs_without_graphics(self):
        b=block(); p=page()
        with patch('pdfplumber.utils.extract_text',return_value=b['text']):
            self.assertTrue(native_prose_verified(p,b,[glyph()]))
            self.assertFalse(native_prose_verified(p,b,[]))
            self.assertFalse(native_prose_verified(p,b,[glyph(fontname='Symbol')]))
            self.assertFalse(native_prose_verified(p,b,[glyph(upright=False)]))
            self.assertFalse(native_prose_verified(p,b,[glyph(x1=90)]))
            p.rotation=90
            self.assertFalse(native_prose_verified(p,b,[glyph()]))
        with patch('pdfplumber.utils.extract_text',return_value='가족이 변화를 경험해요.'):
            self.assertFalse(native_prose_verified(page(),b,[glyph()]))

    def test_math_code_numbers_missing_glyphs_and_visuals_keep_image(self):
        for text in ['속도 v와 가속도 a','금리가 3% 이상이에요.','배열 int *p를 설명해요.',
                     '가족의 (cid:123) 변화','가족의 \ufffd 변화','가족의 \ue001 변화']:
            self.assertFalse(native_prose_verified(page(),block(text=text),[glyph()]))
        for extra in [{'hasVisual':True},{'visualOnly':True},{'geometryFallback':True},
                      {'pageEdgeClipped':True},{'kind':'visual'}]:
            self.assertFalse(native_prose_verified(page(),block(**extra),[glyph()]))

    def test_even_a_tiny_rule_or_raster_below_text_keeps_image(self):
        for field in ['images','curves','rects','lines']:
            p=page();setattr(p,field,[{'x0':11,'x1':50,'top':15,'bottom':15}])
            self.assertFalse(native_prose_verified(p,block(),[glyph()]))

    def test_only_flat_full_page_white_background_is_ignored(self):
        p=page();bg={'object_type':'rect','x0':0,'x1':100,'top':0,'bottom':100,
                    'fill':True,'stroke':False,'non_stroking_color':1}
        with patch('pdfplumber.utils.extract_text',return_value=block()['text']):
            p.rects=[bg];self.assertTrue(native_prose_verified(p,block(),[glyph()]))
            p.rects=[{**bg,'stroke':True}];self.assertFalse(native_prose_verified(p,block(),[glyph()]))
            p.rects=[{**bg,'non_stroking_color':.5}];self.assertFalse(native_prose_verified(p,block(),[glyph()]))
            p.rects=[{**bg,'x1':60}];self.assertFalse(native_prose_verified(p,block(),[glyph()]))

    def test_mixed_crop_ownership_order_old_layout_and_sources_preserved(self):
        a=block(nativeTextProof=VERSION)
        b=block(id='b',kind='visual',hasVisual=True)
        old=block(id='old')
        blocks=[a,b,old];before=copy.deepcopy(blocks)
        crops=[{'page':1,'blockIds':['a']},{'page':1,'blockIds':['a','b']},
               {'page':1,'blockIds':['old']},{'page':1,'blockIds':['unknown']}]
        imgs,kept,text_only=select_images(blocks,['a','mixed','old','unknown'],crops)
        self.assertEqual(imgs,['mixed','old','unknown'])
        self.assertEqual(kept,crops[1:])
        self.assertEqual(text_only,set())
        self.assertEqual(blocks,before)
        self.assertEqual(select_images([a],['a'],[crops[0]]),([],[],{'a'}))
        with self.assertRaises(ValueError): select_images(blocks,[],crops)

    def test_payload_keeps_full_native_text_id_and_page_and_coverage(self):
        import pdf_new_concept_ver99_study as study
        b=block(nativeTextProof=VERSION);job={'title':'가족','blocks':[b]}
        data=study.teaching_payload(job,[],{},[])
        self.assertEqual(data['blocks'][0]['text'],b['text'])
        self.assertEqual(data['blocks'][0]['id'],'a')
        self.assertEqual(data['blocks'][0]['page'],1)
        self.assertTrue(data['blocks'][0]['nativeTextOnly'])
        self.assertNotIn('nativeTextOnly',study.teaching_payload(job,[{'blockIds':['a'],'page':1}],{},[])['blocks'][0])
        refs=study.evidence(b,{'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(refs['sourceId'],'a');self.assertEqual(refs['bbox'],b['bbox'])
        setup=study.STUDY_FORMAT['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']
        self.assertEqual(set(setup['required']),{'observedRelations','boundaryChecks','interpretation'})
        self.assertNotIn('maxLength',setup['properties']['interpretation'])

    def test_mixed_run_recrops_visual_without_discarding_native_source(self):
        a=block(nativeTextProof=VERSION,bbox=[.1,.1,.8,.2])
        b=block(id='b',kind='visual',hasVisual=True,bbox=[.1,.22,.8,.5])
        before=copy.deepcopy([a,b]);chosen=render_blocks([a,b])
        self.assertEqual(chosen,[b]);self.assertEqual([a,b],before)
        self.assertEqual(select_images([a,b],['visual'],[{'blockIds':['b']}])[2],{'a'})
        self.assertEqual(render_blocks([a]),[])
        self.assertEqual(render_blocks([block()]),[block()])

    def test_separating_plain_text_must_not_create_extra_images(self):
        left=block(id='left',bbox=[.1,.1,.8,.2])
        bridge=block(nativeTextProof=VERSION,bbox=[.1,.24,.8,.34])
        right=block(id='right',bbox=[.1,.38,.8,.48])
        self.assertEqual(render_blocks([left,bridge,right]),[left,bridge,right])

    def test_cost_workload_keeps_text_and_excludes_only_verified_image(self):
        from pdf_ver99_cost_estimate import workload
        a=block(nativeTextProof=VERSION)
        doc={'pages':[{'number':1,'width':600,'height':800,'nativeText':a['text']}]}
        job={'id':'a','title':'가족','blocks':[a]}
        safe=workload(doc,[1],blocks=[a],jobs=[job])
        old=block();baseline=workload(doc,[1],blocks=[old],jobs=[{**job,'blocks':[old]}])
        self.assertEqual(safe['details']['textCharacters'],baseline['details']['textCharacters'])
        self.assertEqual(safe['details']['sourceTokenProxy'],baseline['details']['sourceTokenProxy'])
        self.assertEqual(safe['details']['cropImages'],0)
        self.assertEqual(baseline['details']['cropImages'],1)

    def test_compact_setup_keeps_learner_paragraphs_and_rejects_foreign_evidence(self):
        import pdf_new_concept_ver99_study as study
        b=block(nativeTextProof=VERSION);job={'id':'a','title':'가족','blocks':[b]}
        doc={'documentId':'doc','pages':[{'label':'1'}]}
        raw={'concepts':[{'title':'가족과 사회','sourceSetup':{
            'observedRelations':['가족이 사회의 변화를 경험해요.'],
            'boundaryChecks':[],'interpretation':'가족과 사회의 변화예요.'},
            'segments':[{'kind':kind,'text':text,'blockIds':['a']} for kind,text in [
                ('definition','가족은 사회의 변화를 경험하는 생활 단위예요.'),
                ('explanation','사회가 변하면 가족의 생활도 달라질 수 있어요.'),
                ('easyExplanation','가족의 일상과 사회의 변화가 연결돼 있어요.')]],
            'standardKnowledgeUsed':False}], 'excludedBlocks':[], 'uncertainBlocks':[],
            'tables':[],'sequences':[]}
        compact=copy.deepcopy(raw)
        compact['concepts'][0]['sourceSetup']={'observedRelations':[],'boundaryChecks':[],'interpretation':''}
        self.assertEqual(study.validate(raw,job,doc),study.validate(compact,job,doc))
        compact['concepts'][0]['segments'][0]['blockIds']=['foreign-source-999']
        with self.assertRaises(ValueError): study.validate(compact,job,doc)


if __name__=='__main__':unittest.main()
