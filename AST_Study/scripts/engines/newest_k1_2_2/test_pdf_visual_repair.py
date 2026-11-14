"""Incremental cache repair preserves healthy prose and distinguishes layout IDs."""
import copy
import unittest
from pdf_visual_repair import merge_repair


def fixture():
    def part(page,identity,title):
        return {'title':title,'body':'정의예요.\n\n설명을 보존해요.',
            'easyExplanation':'쉽게 설명해요.','evidence':[{'sourceId':identity,'page':page,
                'documentId':'doc','bbox':[.1,.1,.9,.9]}], 'visualPages':[page]}
    def result(scope,parts):
        return {'documentId':'doc','sourceFingerprint':'fp','strategy':'new-concept-v99',
            'model':'gpt-6-luna','scope':scope,'page':0 if scope=='document' else 2,
            'sourcePages':[1,2] if scope=='document' else [2],
            'processingComplete':True,'failedUnits':[], 'sections':[
                {'title':p['title'],'parts':[p],'body':p['body'],'evidence':p['evidence']} for p in parts],
            'concepts':[{'name':p['title'],'entries':[{'name':p['title'],
                'definition':'정의예요.','explanation':'설명을 보존해요.',
                'easyExplanation':p['easyExplanation'],'evidence':p['evidence']}]} for p in parts],
            'overview':{'body':'전체 흐름이에요.','sourceSectionIds':['s0']},'metrics':{},
            'coverage':[{'blockId':p['evidence'][0]['sourceId'],'page':p['evidence'][0]['page'],
                         'state':'summarized'} for p in parts]}
    base=result('document',[part(1,'v2p1f0','기존 원리')])
    base['coverage'].append({'blockId':'v2p2f0','page':2,'state':'excluded','reason':'navigation'})
    patch=result('page',[part(2,'v2p2f0','포인터 비교')])
    def block(page,identity,box):
        return {'id':identity,'page':page,'kind':'visual','hasVisual':True,'text':'',
                'bbox':box,'wordIds':[],'zone':0}
    old=[block(1,'v2p1f0',[.1,.1,.9,.9]),block(2,'v2p2f0',[.1,.1,.11,.11])]
    new=[block(2,'v2p2f0',[.1,.1,.9,.9])]
    doc={'documentId':'doc','fingerprint':'fp','pages':[{'label':'1'},{'label':'2'}]}
    return base,old,patch,new,doc


class VisualRepairTests(unittest.TestCase):
    def test_repair_appends_missing_page_without_editing_healthy_body(self):
        args=fixture();unchanged=copy.deepcopy(args)
        value,blocks=merge_repair(*args)
        self.assertEqual(args,unchanged)
        self.assertEqual(value['sections'][0]['parts'][0]['body'],args[0]['sections'][0]['parts'][0]['body'])
        self.assertEqual(len(value['sections']),2)
        self.assertTrue(value['coverageComplete']);self.assertTrue(value['cacheHit'])
        new_id=value['sections'][1]['parts'][0]['evidence'][0]['sourceId']
        self.assertTrue(new_id.startswith('visual-repair-'))
        self.assertEqual(new_id,blocks[1]['id'])
        self.assertEqual(blocks[1]['bbox'],[.1,.1,.9,.9])
        self.assertEqual(value['coverage'][1]['blockId'],new_id)
        self.assertEqual(value['overview']['sourceSectionIds'],['s0'])

    def test_existing_teaching_on_target_page_is_never_overwritten(self):
        args=list(fixture());args[0]['sections'][0]['parts'][0]['evidence'][0]['page']=2
        with self.assertRaisesRegex(ValueError,'이미 설명'):merge_repair(*args)

    def test_source_identity_and_completion_must_match(self):
        for key,value in [('documentId','other'),('sourceFingerprint','different'),
                          ('model','different'),('processingComplete',False)]:
            args=list(fixture());args[2][key]=value
            with self.assertRaises(ValueError):merge_repair(*args)


if __name__=='__main__':unittest.main()
