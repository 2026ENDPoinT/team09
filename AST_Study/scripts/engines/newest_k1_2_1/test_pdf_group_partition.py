"""Deterministic source accounting, malformed assignments and cache validation."""
import copy
import json
import random
import unittest

from pdf_group_partition import (PartitionError, PartitionFormatError,
                                 recover_ranges, repair_partition, validate_partition)


def block(index, **fields):
    return {'id': f'p{index//3+1}f{index%3}', 'page': index//3+1, 'zone': 0,
            'text': f'정의와 조건 {index}: 원문 문장과 수식 x > {index}예요.',
            'kind': 'text', 'bbox': [.1, .2, .8, .3], **fields}


def group(ids, **fields):
    return {'title': '하나의 원리', 'blockIds': ids, 'role': 'teaching',
            'continuesPrevious': False, **fields}


def flatten(groups):
    return [b for g in groups for b in g['blocks']]


class GroupPartitionTests(unittest.TestCase):
    def test_clean_groups_preserve_payload_order_and_do_not_mutate_inputs(self):
        targets=[block(i) for i in range(5)]
        raw={'groups':[group([b['id'] for b in targets[:3]]),
                       group([b['id'] for b in targets[3:]],title='다른 원리')]}
        original=copy.deepcopy((targets,raw))
        groups,audit=repair_partition(raw,targets)
        self.assertEqual(len(groups),2)
        self.assertEqual(audit['semanticGroupingStatus'],'ai_assigned')
        self.assertEqual(audit['diagnostics'],[])
        self.assertEqual(audit['coverageProof']['sourceDigest'],
                         audit['coverageProof']['assignedSourceDigest'])
        self.assertEqual((targets,raw),original)
        flatten(groups)[0]['bbox'][0]=.7
        self.assertEqual(targets,original[0])

    def test_missing_middle_source_gets_its_own_uncertain_owner(self):
        targets=[block(i) for i in range(3)]
        groups,audit=repair_partition({'groups':[group([targets[0]['id'],targets[2]['id']])]},targets)
        self.assertEqual([b['id'] for b in flatten(groups)],[b['id'] for b in targets])
        self.assertEqual(groups[1]['assignmentOrigin'],'local_unassigned')
        self.assertEqual(groups[1]['blocks'][0]['planRole'],'uncertain')
        self.assertEqual(audit['unassignedBlockIds'],[targets[1]['id']])
        self.assertEqual(audit['additionalRecoveryApiRequests'],0)

    def test_empty_valid_response_recovers_contiguous_same_page_zone_runs(self):
        targets=[block(0),block(1),block(2,zone=1),block(3)]
        groups,audit=repair_partition({'groups':[]},targets)
        self.assertEqual([len(g['blocks']) for g in groups],[2,1,1])
        self.assertTrue(all(b['planRole']=='uncertain' for b in flatten(groups)))
        self.assertTrue(all(not g['continuesPrevious'] for g in groups))
        self.assertTrue(audit['partitionComplete'])

    def test_cross_group_conflict_never_uses_first_navigation_or_exercise_owner(self):
        targets=[block(i) for i in range(3)]
        raw={'groups':[group([targets[0]['id'],targets[1]['id']],role='navigation'),
                       group([targets[1]['id'],targets[2]['id']],role='exercise')]}
        groups,audit=repair_partition(raw,targets)
        self.assertEqual(flatten(groups)[1]['planRole'],'uncertain')
        self.assertEqual(groups[1]['assignmentOrigin'],'local_ambiguous')
        self.assertEqual(audit['ambiguousBlockIds'],[targets[1]['id']])
        self.assertEqual([b['planRole'] for b in flatten(groups)],['navigation','uncertain','exercise'])

    def test_same_group_repetition_deduplicates_without_losing_clear_ownership(self):
        target=block(0)
        groups,audit=repair_partition({'groups':[group([target['id'],target['id']])]},[target])
        self.assertEqual(len(flatten(groups)),1)
        self.assertEqual(flatten(groups)[0]['planRole'],'teaching')
        self.assertEqual(audit['ambiguousBlockIds'],[])
        self.assertEqual(audit['diagnosticCounts']['same_group_repeat'],1)

    def test_unknown_and_malformed_ids_are_not_guessed_or_used_as_commands(self):
        target=block(0,id='v2p10f7')
        raw={'groups':[group(['v2p10f07','ignore all instructions',None,[],{'id':target['id']}])]}
        groups,audit=repair_partition(raw,[target])
        self.assertEqual(flatten(groups)[0]['id'],target['id'])
        self.assertEqual(flatten(groups)[0]['planRole'],'uncertain')
        self.assertEqual(audit['diagnosticCounts']['unknown_id'],2)
        self.assertEqual(audit['diagnosticCounts']['invalid_id_type'],3)

    def test_individual_bad_groups_do_not_abort_or_turn_unknown_roles_into_exclusion(self):
        targets=[block(i) for i in range(3)]
        raw={'groups':[None,42,{'blockIds':targets[0]['id']},
                       group([targets[1]['id']],role=['navigation'],title={}),
                       group([targets[2]['id']],role='unknown')]}
        groups,audit=repair_partition(raw,targets)
        self.assertTrue(all(b['planRole']=='uncertain' for b in flatten(groups)))
        self.assertEqual(audit['diagnosticCounts']['malformed_group'],2)
        self.assertEqual(audit['diagnosticCounts']['invalid_id_list'],1)

    def test_omitted_verified_furniture_does_not_split_one_paid_topic(self):
        targets=[]
        for page in range(3):
            targets.extend([block(page*3,kind='label'),block(page*3+1),block(page*3+2)])
        furniture={b['id'] for index,b in enumerate(targets) if index%3!=2}
        raw={'groups':[group([b['id'] for b in targets if b['id'] not in furniture])]}
        groups,audit=repair_partition(raw,targets,furniture_ids=furniture)
        self.assertEqual(len(groups),1)
        self.assertEqual(sum(b['planRole']=='decoration' for b in flatten(groups)),6)
        self.assertEqual(audit['localUncertainBlockIds'],[])
        self.assertEqual(len(flatten(groups)),9)

    def test_only_supplied_furniture_or_actual_page_number_is_structural(self):
        targets=[block(0,kind='page_number',text='94'),block(1,text='짧은 중요 설명'),block(2)]
        groups,audit=repair_partition({'groups':[]},targets,furniture_ids={'absent'})
        self.assertEqual([b['planRole'] for b in flatten(groups)],['decoration','uncertain','uncertain'])
        self.assertEqual(audit['furnitureBlockIds'],[targets[0]['id']])

    def test_unambiguous_ai_page_number_keeps_its_original_role(self):
        targets=[block(0,kind='page_number',text='5'),block(1,kind='page_number',text='6'),block(2)]
        raw={'groups':[group([targets[0]['id'],targets[2]['id']])]}
        groups,audit=repair_partition(raw,targets)
        self.assertEqual([b['planRole'] for b in flatten(groups)],['teaching','decoration','teaching'])
        self.assertEqual(audit['furnitureBlockIds'],[targets[1]['id']])
        groups,_=repair_partition(raw,targets,furniture_ids={targets[0]['id']})
        self.assertEqual(flatten(groups)[0]['planRole'],'decoration')

    def test_ambiguous_page_number_recovers_structurally_instead_of_first_owner(self):
        target=block(0,kind='page_number',text='5')
        raw={'groups':[group([target['id']]),group([target['id']],role='exercise')]}
        groups,audit=repair_partition(raw,[target])
        self.assertEqual(groups[0]['blocks'][0]['planRole'],'decoration')
        self.assertEqual(audit['ambiguousBlockIds'],[target['id']])
        self.assertEqual(audit['localUncertainBlockIds'],[])

    def test_reordered_model_groups_and_noncontiguous_members_restore_source_order(self):
        targets=[block(i) for i in range(4)]
        raw={'groups':[group([targets[3]['id'],targets[0]['id']],title='A'),
                       group([targets[2]['id'],targets[1]['id']],title='B')]}
        groups,audit=repair_partition(raw,targets)
        self.assertEqual([g['title'] for g in groups],['A','B','A'])
        self.assertEqual([b['id'] for b in flatten(groups)],[b['id'] for b in targets])
        self.assertEqual(audit['diagnosticCounts']['source_order_restored'],2)

    def test_continuation_requires_clean_first_ai_group_at_first_source(self):
        target=block(0)
        groups,_=repair_partition({'groups':[group([target['id']],continuesPrevious=True)]},[target])
        self.assertTrue(groups[0]['continuesPrevious'])
        for raw in [
            {'groups':[group([target['id'],'unknown'],continuesPrevious=True)]},
            {'groups':[group([],continuesPrevious=True),group([target['id']],continuesPrevious=True)]},
            {'groups':[group([target['id']],role='navigation',continuesPrevious=True)]},
            {'groups':[group([target['id']],continuesPrevious='true')]},
        ]:
            groups,_=repair_partition(raw,[target])
            self.assertTrue(all(not g['continuesPrevious'] for g in groups))

    def test_cache_proof_allows_only_the_three_derived_annotations(self):
        targets=[block(0)]
        groups,_=repair_partition({'groups':[]},targets)
        g=copy.deepcopy(groups)
        g[0]['blocks'][0].update(planRole='teaching',visualReadingRequired=True,
                                planRoleBeforeVisualGuard='navigation')
        self.assertTrue(validate_partition(targets,g)['complete'])
        for name,value in [('text','삭제된 본문'),('bbox',[0,0,1,1]),('page',9),
                           ('zone',8),('kind','page_number'),('unrecognizedAnnotation',True)]:
            with self.subTest(field=name):
                g=copy.deepcopy(groups);g[0]['blocks'][0][name]=value
                with self.assertRaises(PartitionError):validate_partition(targets,g)

    def test_recovery_replaces_stale_skip_roles_and_rederives_visual_annotations(self):
        from pdf_visual_selection import protect_visual_groups
        native=block(0,planRole='exercise',visualReadingRequired=True,
                     planRoleBeforeVisualGuard='navigation')
        visual=block(1,kind='visual',hasVisual=True,bbox=[.1,.1,.9,.8],
                     planRole='navigation',visualReadingRequired=False,
                     planRoleBeforeVisualGuard='exercise')
        targets=[native,visual];before=copy.deepcopy(targets)
        groups,_=repair_partition({'groups':[]},targets)
        for b in flatten(groups):
            self.assertEqual(b['planRole'],'uncertain')
            self.assertNotIn('visualReadingRequired',b)
            self.assertNotIn('planRoleBeforeVisualGuard',b)
        protect_visual_groups(groups)
        self.assertNotIn('visualReadingRequired',flatten(groups)[0])
        self.assertTrue(flatten(groups)[1]['visualReadingRequired'])
        self.assertNotIn('planRoleBeforeVisualGuard',flatten(groups)[1])
        self.assertTrue(validate_partition(targets,groups)['complete'])
        self.assertEqual(targets,before)

    def test_cache_proof_rejects_missing_duplicate_unknown_and_reordered_ids(self):
        targets=[block(i) for i in range(3)]
        groups,_=repair_partition({'groups':[]},targets)
        for blocks in [targets[:2],[targets[0],targets[0],targets[2]],
                       [targets[0],block(7),targets[2]],list(reversed(targets))]:
            with self.subTest(blocks=[b['id'] for b in blocks]):
                with self.assertRaises(PartitionError):validate_partition(targets,[{'blocks':blocks}])

    def test_pre_normalization_check_can_allow_group_interleaving_but_not_internal_reordering(self):
        targets=[block(i) for i in range(3)]
        groups=[{'blocks':[targets[0],targets[2]]},{'blocks':[targets[1]]}]
        proof=validate_partition(targets,groups,require_global_order=False)
        self.assertFalse(proof['orderPreserved'])
        self.assertTrue(proof['eachGroupSourceOrderPreserved'])
        with self.assertRaises(PartitionError):validate_partition(targets,groups)
        groups[0]['blocks'].reverse()
        with self.assertRaises(PartitionError):validate_partition(targets,groups,require_global_order=False)

    def test_top_level_parse_failures_and_invalid_canonical_sources_still_raise(self):
        for raw in [None,[],{}, {'groups':None},{'groups':{}}]:
            with self.subTest(raw=raw),self.assertRaises(PartitionFormatError):
                repair_partition(raw,[block(0)])
        for targets in [[block(0),block(0)],[{'id':None}],[{'id':[]}]]:
            with self.subTest(targets=targets),self.assertRaises(PartitionError):
                repair_partition({'groups':[]},targets)
        groups,audit=repair_partition({'groups':[]},[])
        self.assertEqual(groups,[]);self.assertEqual(audit['coverageProof']['sourceCount'],0)

    def test_ranges_leave_gaps_and_conflicts_for_common_exact_partition(self):
        targets=[block(i) for i in range(5)]
        raw={'groups':[{'title':'A','first':0,'last':1,'role':'teaching'},
                       {'title':'B','first':1,'last':3,'role':'navigation'}]}
        before=copy.deepcopy(raw)
        expanded,transport=recover_ranges(raw,targets)
        groups,audit=repair_partition(expanded,targets)
        self.assertEqual(audit['ambiguousBlockIds'],[targets[1]['id']])
        self.assertEqual(audit['unassignedBlockIds'],[targets[4]['id']])
        self.assertEqual(transport['invalidRangeGroups'],[])
        self.assertEqual(raw,before)
        self.assertEqual([b['planRole'] for b in flatten(groups)],
                         ['teaching','uncertain','navigation','navigation','uncertain'])

    def test_ranges_never_clip_guess_boolean_float_or_context_indices(self):
        targets=[block(i) for i in range(3)]
        for first,last in [(-1,2),(0,3),(True,2),(0,1.0),('0',2),(2,1)]:
            with self.subTest(first=first,last=last):
                raw={'groups':[{'first':first,'last':last,'role':'navigation'}]}
                expanded,audit=recover_ranges(raw,targets)
                self.assertEqual(expanded['groups'],[])
                self.assertEqual(len(audit['invalidRangeGroups']),1)
                groups,_=repair_partition(expanded,targets)
                self.assertTrue(all(b['planRole']=='uncertain' for b in flatten(groups)))

    def test_dropped_range_cannot_promote_a_later_continuation_claim(self):
        targets=[block(0),block(1)]
        raw={'groups':[{'first':-1,'last':0,'title':'invalid','role':'teaching'},
                       {'first':0,'last':1,'title':'valid','role':'teaching',
                        'continuesPrevious':True}]}
        expanded,_=recover_ranges(raw,targets)
        groups,_=repair_partition(expanded,targets)
        self.assertFalse(groups[0]['continuesPrevious'])

    def test_seeded_malformed_assignments_always_preserve_every_source_exactly_once(self):
        rng=random.Random(41018)
        for trial in range(300):
            targets=[block(i,zone=rng.randrange(2)) for i in range(rng.randrange(1,21))]
            choices=[b['id'] for b in targets]+['missing-id',None,[],{'id':'x'},9]
            raw={'groups':[]}
            for _ in range(rng.randrange(12)):
                if rng.random()<.15:raw['groups'].append(None);continue
                raw['groups'].append(group([rng.choice(choices) for _ in range(rng.randrange(10))],
                    role=rng.choice(['teaching','navigation','exercise','uncertain',None,{}])))
            before=json.dumps([targets,raw],ensure_ascii=False,sort_keys=True)
            groups,audit=repair_partition(raw,targets)
            self.assertTrue(validate_partition(targets,groups)['complete'],trial)
            self.assertEqual(json.dumps([targets,raw],ensure_ascii=False,sort_keys=True),before)
            self.assertEqual(audit['coverageProof']['sourceCount'],len(targets))

    def test_seeded_ranges_preserve_sources_without_clipping_invalid_intervals(self):
        rng=random.Random(143991)
        for trial in range(150):
            targets=[block(i) for i in range(rng.randrange(1,16))]
            choices=list(range(-2,len(targets)+3))+[None,True,1.5,'0']
            raw={'groups':[{'first':rng.choice(choices),'last':rng.choice(choices),
                            'title':'주제','role':rng.choice(['teaching','navigation']),
                            'continuesPrevious':True}
                           for _ in range(rng.randrange(10))]}
            before=copy.deepcopy(raw)
            expanded,_=recover_ranges(raw,targets)
            groups,audit=repair_partition(expanded,targets)
            self.assertTrue(validate_partition(targets,groups)['complete'],trial)
            self.assertEqual(raw,before)
            self.assertEqual(audit['coverageProof']['sourceCount'],len(targets))


if __name__=='__main__':
    unittest.main()
