"""Offline New개념Ver contracts: heading ownership, crop/text alignment, isolation."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pdf_new_concept_regions as layout
import pdf_new_concept_study as study
import pdf_region_study as old
from test_pdf_region_study import Provider,response,block


def frag(key,kind='text',page=1):
    return {'id':key,'kind':kind,'page':page,'text':key,'bbox':[.1,.1,.9,.2],
            'hasVisual':kind=='visual','visualOnly':kind=='visual','headingLevel':1 if kind=='heading' else None}


class NewConceptTests(unittest.TestCase):
    def test_page_end_heading_moves_forward_even_when_planner_assigns_it_back(self):
        a,h,v,c=frag('previous'),frag('new heading','heading'),frag('chart','visual',2),frag('caption','caption',2)
        groups=study.normalize_groups([a,h,v,c],[{'title':'old','blocks':[a,h]},{'title':'next','blocks':[v,c]}])
        self.assertEqual([[b['id'] for b in g['blocks']] for g in groups],[['previous'],['new heading','chart','caption']])

    def test_heading_starts_new_topic_even_when_all_fragments_are_one_group(self):
        bs=[frag('old'),frag('heading','heading'),frag('body'),frag('subheading','heading'),frag('detail')]
        groups=study.normalize_groups(bs,[{'title':'all','blocks':bs}])
        self.assertEqual([[b['id'] for b in g['blocks']] for g in groups],[['old'],['heading','body'],['subheading','detail']])

    def test_plain_list_introduction_moves_to_its_list_not_previous_example(self):
        a,h,b=frag('prior example'),frag('list introduction','label'),frag('list body')
        groups=study.normalize_groups([a,h,b],[{'title':'old','blocks':[a,h]},{'title':'list','blocks':[b]}])
        self.assertEqual([[b['id'] for b in g['blocks']] for g in groups],[['prior example'],['list introduction','list body']])

    def test_reordered_planner_groups_restore_source_order_and_every_fragment(self):
        bs=[frag(str(i)) for i in range(4)]
        groups=study.normalize_groups(bs,[{'title':'B','blocks':bs[2:]},{'title':'A','blocks':bs[:2]}])
        self.assertEqual([b['id'] for g in groups for b in g['blocks']],[str(i) for i in range(4)])

    def test_transport_split_moves_heading_chain_with_its_body(self):
        bs=[frag('a',page=1),frag('b',page=2),frag('c',page=3),frag('title','heading',4),frag('body',page=5)]
        jobs=study.jobs_for([{'title':'test','blocks':bs}])
        self.assertEqual([b['id'] for b in jobs[1]['blocks']],['title','body'])

    def test_isolated_cache_and_old_prompt_identity_unchanged(self):
        doc={'documentId':'id','fingerprint':'fp'}
        self.assertNotEqual(old.root_path('/tmp',doc,'region-v1','gpt-6-luna','document',0),study.root_path('/tmp',doc,'new-concept-v1','gpt-6-luna','document',0))
        self.assertNotIn('new-concept-v1',old.STRATEGIES)
        self.assertIn('graph/table/diagram',study.STUDY_PROMPT)
        self.assertIn('axes',study.STUDY_PROMPT)

    def test_resume_only_requests_failed_fragment_group(self):
        class SeparateProvider(Provider):
            def complete(self,payload,**kw):
                if payload['task']=='region_groups':
                    self.calls.append(payload['task'])
                    return {'groups':[{'title':b['id'],'blockIds':[b['id']],'continuesPrevious':False} for b in payload['targets']]}
                return super().complete(payload,**kw)
        doc={'documentId':'fixture','fingerprint':'fp','incompletePages':[],
             'pages':[{'number':i,'nativeText':'text','label':str(i)} for i in range(1,4)]}
        def render(folder,blocks,cache):return ([{'data':'offline','width':50,'height':50}],[])
        with tempfile.TemporaryDirectory() as t,contextlib.redirect_stdout(io.StringIO()),patch.object(study,'extract',return_value=[block(1),block(2),block(3)]),patch.object(study,'render_crops',side_effect=render):
            first=study.generate(Path(t),doc,SeparateProvider('b2'))
            self.assertEqual(first['partialUnits'],2)
            second_provider=SeparateProvider();second=study.generate(Path(t),doc,second_provider)
            self.assertTrue(second['processingComplete']);self.assertEqual(second_provider.calls.count('region_teaching'),1)
            third_provider=SeparateProvider();third=study.generate(Path(t),doc,third_provider)
            self.assertTrue(third['cacheHit']);self.assertEqual(third_provider.calls,[])

    def test_unreferenced_heading_is_context_but_missing_visual_stays_unresolved(self):
        h,b,v=frag('heading','heading'),frag('body'),frag('graph','visual')
        doc={'documentId':'doc','pages':[{'label':'1'}]}
        raw=response({'titleHint':'topic','blocks':[b]})
        value=study.validate(raw,{'id':'job','title':'topic','blocks':[h,b,v]},doc)
        states={c['blockId']:c['state'] for c in value['coverage']}
        self.assertEqual(states,{'heading':'context','body':'summarized','graph':'needs_review'})

    def test_typographic_heading_and_page_number_detection(self):
        row={'text':'1.5. 금융중개기관의 기능','bbox':[.06,.78,.55,.81],'fontSize':18,'bold':True}
        self.assertEqual(layout.row_kind(row,11)[0],'heading')
        row.update(text='7',bbox=[.49,.88,.51,.89],fontSize=11,bold=False)
        self.assertEqual(layout.row_kind(row,11)[0],'page_number')
        row.update(text='7',bbox=[.1,.5,.12,.52])
        self.assertEqual(layout.row_kind(row,11)[0],'text')

    def test_balanced_jobs_preserve_cross_page_definition_and_example(self):
        bs=[]
        for i in range(8):
            b=frag(f'term{i}');b['text']=f'개념{i}: '+'설명 '*100;bs.append(b)
            detail=frag(f'example{i}',page=2);detail['text']='이어지는 예시예요.';bs.append(detail)
        jobs=study.jobs_for([{'title':'terms','blocks':bs}])
        self.assertGreater(len(jobs),1)
        self.assertEqual([b['id'] for j in jobs for b in j['blocks']],[b['id'] for b in bs])
        for i in range(8):
            owner=next(j for j in jobs if any(b['id']==f'term{i}' for b in j['blocks']))
            self.assertIn(f'example{i}',[b['id'] for b in owner['blocks']])

    def test_four_crop_limit_counts_disconnected_runs_on_one_page(self):
        bs=[]
        for i in range(6):
            b=frag(str(i));b['bbox']=[.1,i*.16,.9,i*.16+.03];bs.append(b)
        jobs=study.jobs_for([{'title':'same page','blocks':bs}])
        self.assertGreater(len(jobs),1)
        self.assertTrue(all(len(layout.crop_runs(j['blocks']))<=4 for j in jobs))
        self.assertEqual(sum(len(j['blocks']) for j in jobs),6)

    def test_compact_payload_retains_full_text_and_image_source_mapping(self):
        b=frag('source');b['text']='긴 원문'*300;b['headingTitle']='반복 제목'
        payload=study.teaching_payload({'title':'t','blocks':[b]},[{'page':1,'blockIds':['source'],'bbox':b['bbox'],'path':'local'}],{},[])
        self.assertEqual(payload['blocks'][0]['text'],b['text'])
        self.assertNotIn('bbox',payload['blocks'][0]);self.assertNotIn('headingTitle',payload['blocks'][0])
        self.assertEqual(payload['crops'],[{'page':1,'blockIds':['source']}])

    def test_structural_label_does_not_hide_missing_body_or_explicit_uncertainty(self):
        h,b,missing,next_h,detail=[frag('label','label'),frag('body'),frag('missing'),frag('next','heading'),frag('detail')]
        doc={'documentId':'doc','pages':[{'label':'1'}]}
        job={'id':'job','title':'topic','blocks':[h,b,missing,next_h,detail]}
        raw=response({'titleHint':'topic','blocks':[b]})
        value=study.validate(raw,job,doc);states={c['blockId']:c['state'] for c in value['coverage']}
        self.assertEqual(states['label'],'context');self.assertEqual(states['missing'],'needs_review')
        self.assertEqual(states['next'],'needs_review')
        raw['uncertainBlocks']=[{'blockId':'label','reason':'읽을 수 없음'}]
        self.assertEqual(study.validate(raw,job,doc)['coverage'][0]['state'],'needs_review')

    def test_heading_chain_owns_the_following_taught_body(self):
        bs=[frag('section','heading'),frag('subsection','heading'),frag('body')]
        raw=response({'titleHint':'topic','blocks':[bs[-1]]})
        value=study.validate(raw,{'id':'job','title':'topic','blocks':bs},{'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual([c['state'] for c in value['coverage']],['context','context','summarized'])

    def test_only_unambiguous_metadata_cover_skips_paid_teaching(self):
        b=frag('cover');b['text']='강의노트 금융의 이해 2026년 2학기 이름'
        self.assertEqual(study.plain_cover_ids([b]),{'cover'})
        b['hasVisual']=True;self.assertEqual(study.plain_cover_ids([b]),set())
        b['hasVisual']=False;b['text']+=' 함수: 실행 코드의 묶음'
        self.assertEqual(study.plain_cover_ids([b]),set())

    def test_split_topic_reassembles_in_source_order_without_mutating_saved_units(self):
        bs=[frag('a'),frag('b')];doc={'documentId':'d','fingerprint':'f','pages':[{'label':'1'}]}
        jobs=[{'id':str(i),'title':'shared','topicIndex':0,'blocks':[b]} for i,b in enumerate(bs)]
        done={i:study.validate(response({'titleHint':b['id'],'blocks':[b]}),jobs[i],doc) for i,b in enumerate(bs)}
        value=study.assemble(doc,'new-concept-v1','document',0,[1],jobs,done,[],[])
        self.assertEqual(len(value['sections']),1)
        self.assertEqual([p['title'] for p in value['sections'][0]['parts']],['a','b'])
        self.assertEqual(len(done[0]['summary']['parts']),1)

    @unittest.skipUnless(Path('build/finance1-fiveway-20261011/runs/region-v1/source.pdf').exists(),'finance source not available')
    def test_actual_finance_fragments_align_and_graph_is_explicit(self):
        base=Path('build/finance1-fiveway-20261011/runs/region-v1')
        doc=json.loads((base/'document.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            bs=layout.extract(base,doc,range(1,15),Path(tmp))
            data=json.loads((Path(tmp)/'local-layout.json').read_text())
            for p in data['pages']:
                for w in p['words']:
                    matches=[b for b in p['fragments'] if layout.inside(w['bbox'],b['bbox'])]
                    self.assertEqual(len(matches),1,(p['page'],w['text']))
                    self.assertTrue(layout.contains(matches[0]['bbox'],w['bbox']))
            self.assertGreater(len(bs),70)
            self.assertFalse(any(b['kind']=='page_number' for b in bs))
            h=next(b for b in bs if b['text'].startswith('1.5. 금융중개기관'))
            self.assertEqual(h['kind'],'heading');self.assertEqual(h['page'],7)
            graph=next(b for b in bs if b['page']==8 and b['hasVisual'])
            self.assertEqual(graph['kind'],'visual');self.assertNotEqual(graph['id'],h['id'])
            groups=study.normalize_groups(bs,[{'title':'malformed all-in-one','blocks':bs}])
            group=next(g for g in groups if h in g['blocks'])
            self.assertIn(graph,group['blocks']);self.assertFalse(any(b['text'].startswith('1.4.') for b in group['blocks']))
            images,crops=layout.render_crops(base,group['blocks'],Path(tmp))
            for c in crops:
                for b in group['blocks']:
                    if b['id'] in c['blockIds']:self.assertTrue(layout.contains(c['bbox'],b['bbox']))
            self.assertGreaterEqual(len(images),2)
            self.assertEqual(next(b for b in bs if b['text']=='금융시스템에 대한 규제의 유형:')['kind'],'label')
            self.assertEqual(next(b for b in bs if b['text']=='(참고) 장기정부증권의 종류')['kind'],'label')
            # Real Korean heading strokes extend above pdfplumber's nominal font box.
            from PIL import Image
            heading_crop=next(c for c in crops if h['id'] in c['blockIds'])
            with Image.open(heading_crop['path']).convert('RGB') as im:
                self.assertFalse(any(max(im.getpixel((x,0)))<180 for x in range(im.width)))


if __name__=='__main__':unittest.main()
