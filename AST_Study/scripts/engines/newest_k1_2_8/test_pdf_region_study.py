"""Offline geometry, isolation, evidence and restart contracts. Never calls an API."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import shutil
import base64
import unittest
from unittest.mock import patch

import pdf_regions as regions
import pdf_region_study as study


def block(n, page=None):
    return {'id':f'b{n}','page':page or n,'bbox':[0,0,1,1],
            'text':f'개념 {n}의 정의와 조건','visualOnly':False,'geometryFallback':False}


def response(payload):
    return {'concepts':[{'title':payload['titleHint'],'definition':'입력을 처리하는 개념이에요.',
        'explanation':'입력과 처리 과정을 연결해요.','easyExplanation':'비유: 재료를 넣고 요리법을 따르면 음식이 나오는 것과 같아요.',
        'blockIds':[b['id'] for b in payload['blocks']],'standardKnowledgeUsed':True}],
        'excludedBlocks':[],'uncertainBlocks':[]}


class Provider:
    model='gpt-6-luna'
    def __init__(self,fail=None):
        self.calls=[];self.fail=fail;self.ledger={'requests':[]};self.lock=threading.Lock()
    def complete(self,payload,**kwargs):
        with self.lock:self.calls.append(payload['task'])
        if payload['task']=='region_groups':
            return {'groups':[{'title':'함수','blockIds':[b['id'] for b in payload['targets']],
                               'continuesPrevious':False}]}
        if payload['task']=='lecture_flow_from_headings':
            return {'body':'함수의 정의에서 조건으로 이어져요.','topicIds':[x['id'] for x in payload['topics']]}
        if self.fail in [b['id'] for b in payload['blocks']]:raise RuntimeError('offline failure')
        return response(payload)


class RegionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.doc={'documentId':'fixture','fingerprint':'fp','incompletePages':[],
            'pages':[{'number':i,'nativeText':f'개념 {i}','label':str(i)} for i in range(1,4)]}
        self.quiet=contextlib.redirect_stdout(io.StringIO());self.quiet.__enter__()
    def tearDown(self):
        self.quiet.__exit__(None,None,None);self.temp.cleanup()

    def test_partitions_tile_page_and_do_not_cut_objects(self):
        objects=[[.1,.1,.9,.2],[.1,.5,.4,.8],[.6,.5,.9,.8]]
        boxes=regions.partitions(objects)
        self.assertGreater(len(boxes),1)
        self.assertAlmostEqual(sum((b[2]-b[0])*(b[3]-b[1]) for b in boxes),1)
        for obj in objects:
            containing=[b for b in boxes if b[0]<=obj[0] and b[1]<=obj[1] and b[2]>=obj[2] and b[3]>=obj[3]]
            self.assertEqual(len(containing),1)

    def test_scans_and_unsafe_frames_keep_whole_page(self):
        p={'number':1,'nativeText':'scan','words':[]}
        self.assertEqual(regions.page_blocks(p)[0]['bbox'],[0,0,1,1])
        p['words']=[{'text':'one','bbox':[.1,.1,.2,.2]},{'text':'two','bbox':[.7,.7,.8,.8]}]
        self.assertEqual(len(regions.page_blocks(p,False)),1)

    @unittest.skipUnless(Path('build/pdf-tests/crop-rotation.pdf').is_file(),'Java rotation fixture not built')
    def test_local_crop_matches_independent_java_rotated_page_render(self):
        from PIL import Image
        shutil.copyfile('build/pdf-tests/crop-rotation.pdf',self.folder/'source.pdf')
        b=block(1);b['bbox']=[0,0,.5,.5]
        images,manifest=regions.render_crops(self.folder,[b],self.folder/'cache')
        with Image.open(io.BytesIO(base64.b64decode(images[0]['data'].split(',',1)[1]))) as cropped, \
                Image.open('build/pdf-tests/crop-rotation-java.png') as java:
            self.assertEqual(cropped.convert('RGB').getpixel((cropped.width//2,cropped.height//2)),
                             java.convert('RGB').getpixel((java.width//4,java.height//4)))
        self.assertEqual(manifest[0]['page'],1)

    def test_full_native_words_survive_partition_without_region_text_truncation(self):
        words=[{'text':'가'*800,'bbox':[.1,.1,.8,.2]}, {'text':'나'*800,'bbox':[.1,.6,.8,.7]}]
        p={'number':1,'nativeText':'가'*800+'\n'+'나'*800,'words':words,'textRegions':[]}
        bs=regions.page_blocks(p)
        self.assertEqual(sum(len(b['text']) for b in bs),1600)

    def test_planner_missing_ids_are_preserved(self):
        p=Provider()
        p.complete=lambda *a,**k:{'groups':[{'title':'함수','blockIds':['b1','bogus'],'continuesPrevious':False}]}
        groups,warnings=study.plan_groups(self.folder,p,[block(1),block(2)],self.folder)
        self.assertEqual([b['id'] for g in groups for b in g['blocks']],['b1','b2'])
        self.assertTrue(warnings)

    def test_transport_split_preserves_every_page_and_four_image_limit(self):
        jobs=study.jobs_for([{'title':'긴 개념','blocks':[block(i) for i in range(1,10)]}])
        self.assertEqual(len(jobs),3)
        self.assertEqual([b['id'] for j in jobs for b in j['blocks']],[f'b{i}' for i in range(1,10)])
        self.assertTrue(all(len({b['page'] for b in j['blocks']})<=4 for j in jobs))

    def test_unknown_evidence_rejected_but_missing_coverage_is_visible(self):
        job={'id':'u','title':'함수','blocks':[block(1),block(2)]}
        raw=response({'titleHint':'함수','blocks':[block(1)]})
        value=study.validate(raw,job,self.doc)
        self.assertEqual(value['coverage'][1]['state'],'needs_review')
        raw['concepts'][0]['blockIds']=['unknown']
        with self.assertRaises(ValueError):study.validate(raw,job,self.doc)

    def test_summary_and_card_use_same_generated_teaching(self):
        job={'id':'u','title':'함수','blocks':[block(1)]}
        value=study.validate(response({'titleHint':'함수','blocks':job['blocks']}),job,self.doc)
        self.assertEqual(value['concepts'][0]['easyExplanation'],value['summary']['parts'][0]['easyExplanation'])
        self.assertEqual(value['concepts'][0]['evidence'][0]['source'],'region_image')

    def test_inherited_teaching_policy_has_analogy_titles_and_no_length_quota(self):
        self.assertIn('no character,',study.STUDY_PROMPT)
        self.assertIn('nominal definition/relationship phrase',study.STUDY_PROMPT)
        self.assertIn('map its roles to the concept',study.STUDY_PROMPT)
        for legacy in ('excludedElementIds','resolvedBoundaries','partIndex','definedTerms'):
            self.assertNotIn(legacy,study.STUDY_PROMPT)

    def test_isolated_failure_persists_success_and_resume_only_missing_unit(self):
        def render(folder,blocks,cache):
            return ([{'data':'offline','width':50,'height':50}], [{'page':blocks[0]['page'],'bbox':[0,0,1,1],'path':'unused'}])
        with patch.object(study,'extract',return_value=[block(1),block(2),block(3)]),patch.object(study,'render_crops',side_effect=render):
            p=Provider('b2')
            first=study.generate(self.folder,self.doc,p,strategy='slide-v1')
            self.assertEqual(first['kind'],'partial');self.assertEqual(first['partialUnits'],2)
            self.assertEqual(first['incompleteStudyPages'],[2])
            recovered=study.recover(self.folder,self.doc,strategy='slide-v1')
            self.assertEqual(recovered['partialUnits'],2)
            p2=Provider()
            second=study.generate(self.folder,self.doc,p2,strategy='slide-v1')
            self.assertEqual(second['kind'],'ai_generated')
            self.assertEqual(p2.calls.count('region_teaching'),1)
            p3=Provider();third=study.generate(self.folder,self.doc,p3,strategy='slide-v1')
            self.assertTrue(third['processingComplete']);self.assertEqual(p3.calls,[])
        self.assertNotEqual(study.latest_path(self.folder,'region-v1','document',0),
                            study.latest_path(self.folder,'slide-v1','document',0))

    def test_render_error_is_local_to_one_unit(self):
        def render(folder,blocks,cache):
            if blocks[0]['page']==2:raise ValueError('damaged crop')
            return ([{'data':'offline','width':50,'height':50}],[{'page':1,'bbox':[0,0,1,1]}])
        with patch.object(study,'extract',return_value=[block(1),block(2),block(3)]),patch.object(study,'render_crops',side_effect=render):
            result=study.generate(self.folder,self.doc,Provider(),strategy='slide-v1')
        self.assertEqual(result['partialUnits'],2)
        self.assertEqual(result['failedUnits'][0]['stage'],'render')
        self.assertEqual(result['incompleteStudyPages'],[2])


if __name__=='__main__':unittest.main()
