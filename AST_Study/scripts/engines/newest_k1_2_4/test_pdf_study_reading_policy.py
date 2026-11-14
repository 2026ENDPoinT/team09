import copy
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import pdf_study_reading_policy as policy
import pdf_new_concept_v02_regions as layout
import pdf_new_concept_ver99_study as study
from pdf_visual_selection import locally_skipped, protect_visual_groups


def chart(page=1, zone=0):
    blocks=[{'id':f'{page}title','page':page,'zone':zone,'kind':'heading',
             'text':'Annual working hour','bbox':[.2,.1,.8,.15]}]
    for i in range(8):
        blocks.append({'id':f'{page}bar{i}','page':page,'zone':zone,'kind':'visual',
                       'text':'','bbox':[.2+i*.07,.25+i*.025,.22+i*.07,.7],
                       'hasVisual':True,'visualKinds':['vector']})
    for i in range(5):
        blocks.append({'id':f'{page}tick{i}','page':page,'zone':zone,'kind':'text',
                       'text':str(i*20),'bbox':[.1,.2+i*.1,.14,.22+i*.1]})
    blocks.append({'id':f'{page}labels','page':page,'zone':zone,'kind':'text',
                   'text':'Korea OECD Australia','bbox':[.2,.72,.9,.8]})
    return blocks


class ReadingPolicyTests(unittest.TestCase):
    def test_connected_chart_keeps_labels_and_every_source_once_without_mutation(self):
        blocks=chart();before=copy.deepcopy(blocks)
        runs=layout.crop_runs(blocks)
        self.assertEqual(runs,[blocks])
        self.assertEqual(blocks,before)
        self.assertEqual([b['id'] for run in runs for b in run],[b['id'] for b in blocks])

    def test_pages_and_panels_are_never_joined(self):
        blocks=chart()+chart(2)
        self.assertEqual(len(layout.crop_runs(blocks)),2)
        blocks=chart()+chart(1,1)
        self.assertEqual(len(layout.crop_runs(blocks)),2)

    def test_multiple_plots_or_headings_keep_original_crop_path(self):
        for second_heading in (False,True):
            blocks=chart()
            if second_heading:
                blocks.append({**blocks[0],'id':'other-title'})
            else:
                blocks.extend([{**b,'id':b['id']+'b','bbox':[b['bbox'][0],.75,b['bbox'][2],.95]}
                               for b in blocks if b['kind']=='visual'])
            self.assertFalse(policy.coherent_chart(blocks))
            self.assertEqual(layout.crop_runs(blocks),layout._fragment_crop_runs(blocks))

    def test_sizeof_exercise_is_read_and_cannot_be_silently_excluded(self):
        block={'id':'p13','page':1,'zone':0,'kind':'visual','bbox':[0,0,1,1],
               'text':'What is the output? int a=3; int* pa=&a; sizeof(pa); sizeof(*pa); sizeof(&pa);',
               'hasVisual':True,'localRole':'exercise','planRole':'exercise'}
        self.assertFalse(locally_skipped(block))
        protect_visual_groups([{'blocks':[block]}])
        self.assertEqual(block['planRole'],'uncertain')
        result=study.validate({'concepts':[],'excludedBlocks':[{'blockId':'p13',
            'reason':'출력 결과를 묻는 독립 연습문제이며 풀이 원리나 정답이 없어요.',
            'referenceContext':None}]}, {'id':'unit','title':'sizeof','blocks':[block]},
            {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(result['coverage'][0]['state'],'needs_review')

    def test_plain_unanswered_repetition_can_still_be_skipped(self):
        self.assertTrue(locally_skipped({'localRole':'exercise','text':'문제 1. 넓이를 구하여라.'}))

    def test_running_legacy_desktop_workers_keep_old_rules(self):
        env={**os.environ,'SYNESIS_APP_ROOT':'/existing-desktop'}
        env.pop('SYNESIS_STUDY_READING_POLICY',None)
        output=subprocess.check_output([sys.executable,'-B','-c',
            'import pdf_study_reading_policy as p; print(p.ENABLED)'],env=env,text=True)
        self.assertEqual(output.strip(),'False')
        env['SYNESIS_STUDY_READING_POLICY']=policy.VERSION
        output=subprocess.check_output([sys.executable,'-B','-c',
            'import pdf_study_reading_policy as p; print(p.ENABLED)'],env=env,text=True)
        self.assertEqual(output.strip(),'True')

    def test_legacy_crop_behavior_is_unchanged(self):
        blocks=chart()
        with patch.object(policy,'ENABLED',False):
            self.assertEqual(layout.crop_runs(blocks),layout._fragment_crop_runs(blocks))


if __name__=='__main__':unittest.main()
