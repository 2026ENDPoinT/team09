"""Independent integration review of partition ownership and annotation routing."""
import copy
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study
from pdf_group_partition import PartitionFormatError, validate_partition


def block(index, **fields):
    return {'id': f'b{index}', 'page': 1, 'zone': 0, 'kind': 'text',
            'text': f'개념{index}의 정의와 조건을 설명하는 학습 본문이에요.',
            'bbox': [.1, .1+index*.1, .9, .18+index*.1],
            'visualOnly': False, 'hasVisual': False, **fields}


def group(ids, title='원리', role='teaching', continues=False):
    return {'title': title, 'role': role, 'blockIds': ids,
            'continuesPrevious': continues}


class PartitionIntegrationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.folder=Path(self.temporary.name)
        self.stack=patch.object(socket.socket,'connect',side_effect=AssertionError('No network'))
        self.stack.start();self.addCleanup(self.stack.stop)

    def plan(self,blocks,reply,**settings):
        provider=SimpleNamespace(model='gpt-6-luna',complete=reply)
        with patch.multiple(study,PLAN_TRANSPORT='ids',**settings):
            return study.plan_groups(self.folder,provider,blocks,self.folder)

    def test_original_owner_is_restored_before_following_heading_guard(self):
        blocks=[block(0),block(1,kind='heading',text='다음 원리'),block(2),block(3)]
        raw={'groups':[group(['b0','b2'],'A'),group(['b1','b3'],'B')]}
        groups,warnings=self.plan(blocks,lambda *a,**kw:copy.deepcopy(raw))
        self.assertFalse(warnings)
        self.assertEqual([(g['title'],[b['id'] for b in g['blocks']]) for g in groups],
                         [('A',['b0','b1','b2']),('B',['b3'])])
        self.assertTrue(validate_partition(blocks,groups)['complete'])

    def test_missing_window_prefix_does_not_merge_a_later_group_as_continuation(self):
        blocks=[block(i) for i in range(4)]
        def reply(payload,**kw):
            ids=[b['id'] for b in payload['targets']]
            return {'groups':[group(ids if ids[0]=='b0' else ids[1:],continues=bool(payload['before']))]}
        groups,_=self.plan(blocks,reply,PLAN_WINDOW_BLOCKS=2)
        by_id={b['id']:b for g in groups for b in g['blocks']}
        self.assertEqual(by_id['b2']['planRole'],'uncertain')
        self.assertEqual([b['id'] for b in groups[0]['blocks']],['b0','b1'])
        self.assertTrue(validate_partition(blocks,groups)['complete'])

    def test_none_response_with_real_text_cannot_be_confirmed_as_a_scan(self):
        with self.assertRaises(PartitionFormatError):
            self.plan([block(0)],lambda *a,**kw:None)
        self.assertFalse((self.folder/'plan.json').exists())

    def test_scan_bypass_does_not_reuse_stale_skip_or_guard_annotations(self):
        target=block(0,text='',kind='visual',hasVisual=True,visualOnly=True,
                     bbox=[.1,.1,.9,.9],planRole='exercise',
                     visualReadingRequired=False,planRoleBeforeVisualGuard='navigation')
        groups,warnings=self.plan([target],lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No planner call')))
        self.assertFalse(warnings)
        actual=groups[0]['blocks'][0]
        # This path deliberately bypasses model roles: an absent role is
        # eligible for direct image reading and is not a fabricated AI label.
        self.assertNotIn(actual.get('planRole'),('exercise','navigation','decoration'))
        self.assertTrue(actual['visualReadingRequired'])
        self.assertNotIn('planRoleBeforeVisualGuard',actual)
        self.assertTrue(validate_partition([target],groups)['complete'])


if __name__=='__main__':
    unittest.main()
