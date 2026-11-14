"""Source-bearing diagrams/articles survive text-only selection, without a reviewer call."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study
from pdf_visual_selection import (substantive_visual, locally_skipped, protect_visual_groups,
                                  unjustified_visual_exclusion)


def diagram(**changes):
    return {'id':'v2p1f0','page':1,'zone':0,'bbox':[0.,0.,1.,1.],
            'kind':'page','text':'Array of Pointers & Pointers to Array',
            'hasVisual':True,'geometryFallback':True,'visualOnly':False,
            'wordIds':[],**changes}


class VisualSelectionTests(unittest.TestCase):
    def test_large_diagram_cannot_be_skipped_as_navigation_by_text_only_plan(self):
        b=diagram(planRole='navigation')
        groups=[{'title':'구조 정보','blocks':[b]}]
        self.assertIs(protect_visual_groups(groups),groups)
        self.assertEqual(b['planRole'],'uncertain')
        self.assertEqual(b['planRoleBeforeVisualGuard'],'navigation')
        self.assertTrue(b['visualReadingRequired'])
        self.assertEqual(len(groups[0]['blocks']),1)
        protect_visual_groups(groups)
        self.assertEqual(b['planRoleBeforeVisualGuard'],'navigation')

    def test_small_icons_thin_rules_and_explicit_native_exercises_stay_cheap(self):
        for changes in [dict(kind='visual',geometryFallback=False,bbox=[.9,.9,.94,.94]),
                        dict(kind='visual',geometryFallback=False,bbox=[.1,.03,.9,.045]),
                        dict(localRole='exercise',text='문제 1. 넓이를 구하여라.'),
                        dict(localRole='decoration')]:
            b=diagram(planRole='navigation',**changes)
            self.assertFalse(substantive_visual(b))
            protect_visual_groups([{'blocks':[b]}])
            self.assertEqual(b['planRole'],'navigation')

    def test_local_contents_label_cannot_hide_a_large_unread_image(self):
        self.assertFalse(locally_skipped(diagram(localRole='navigation')))
        self.assertTrue(locally_skipped(diagram(localRole='exercise')))

    def test_article_exclusion_only_for_lack_of_general_principle_remains_unresolved(self):
        b=diagram(kind='visual',geometryFallback=False,text='동아일보 (2026.10.01)',planRole='uncertain')
        result=study.validate({'concepts':[],'excludedBlocks':[{'blockId':b['id'],
            'reason':'기사 제목과 요약이 보이지만 일반적인 개념이나 원리를 가르치지 않아요.'}],
            'uncertainBlocks':[]}, {'id':'news','title':'기사','blocks':[b]},
            {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(result['coverage'][0]['state'],'needs_review')
        self.assertNotEqual(result['coverage'][0]['state'],'excluded')
        self.assertEqual(result['concepts'],[])

    def test_readable_visual_cannot_be_excluded_for_topic_scope_in_either_language(self):
        reasons = [
            '요청 주제인 광수용기와 시각이상에 대한 내용이 아님.',
            '눈꺼풀과 결막, 눈물기관을 설명하는 그림으로, 안구근육과 그 지배 신경에 관한 내용이 아니에요.',
            '전혀 다른 구조가 그려져 있으므로 제외합니다.',
            'This informative diagram addresses a different topic.',
            '지정 주제에 해당하지 않음.',
            '주어진 묶음의 주제와 직접 관련 없음.',
            '현재 그룹의 주제 범위 밖에 있는 표입니다.',
            '요청한 주제와 무관한 기관 기능표여서 제외합니다.',
            'This table is not about the selected topic.',
            'Outside the requested scope.',
            'Unrelated to the assigned topic.',
            'Does not match the topic hint.',
            "Doesn't belong to this section's topic.",
            'Out-of-scope for the current group.',
            'The current subject is unrelated to this diagram.',
        ]
        for reason in reasons:
            with self.subTest(reason=reason):
                b=diagram(planRole='uncertain')
                self.assertTrue(unjustified_visual_exclusion(b,reason))
                result=study.validate({'concepts':[], 'excludedBlocks':[{
                    'blockId':b['id'],'reason':reason}], 'uncertainBlocks':[]},
                    {'id':'group','title':'일부 주제','blocks':[b]},
                    {'documentId':'doc','pages':[{'label':'1'}]})
                self.assertEqual(result['coverage'][0]['state'],'needs_review')
                self.assertEqual(result['concepts'],[])

    def test_topic_guard_does_not_turn_verified_covers_or_quizzes_into_teaching(self):
        b=diagram(planRole='uncertain')
        for reason in ['요청 주제와 무관한 표지 정보로 강의명과 강사 이름만 있습니다.',
                       '지정 주제와 무관한 OX 퀴즈 문항만 있으며 풀이·정답은 없습니다.']:
            with self.subTest(reason=reason):
                self.assertFalse(unjustified_visual_exclusion(b,reason))
                result=study.validate({'concepts':[], 'excludedBlocks':[{
                    'blockId':b['id'],'reason':reason}], 'uncertainBlocks':[]},
                    {'id':'group','title':'학습 내용','blocks':[b]},
                    {'documentId':'doc','pages':[{'label':'1'}]})
                self.assertEqual(result['coverage'][0]['state'],'excluded')

    def test_arbitrary_exclusion_reason_cannot_drop_substantive_content(self):
        b=diagram(planRole='uncertain')
        for reason in ['표의 주제는 기관들의 기능입니다.',
                       'The topic title describes the scope of this table.',
                       'Not readable: labels are blurred.']:
            self.assertTrue(unjustified_visual_exclusion(b,reason))
        icon=diagram(kind='visual',geometryFallback=False,bbox=[.9,.9,.94,.94])
        self.assertFalse(unjustified_visual_exclusion(icon,'Outside the requested scope.'))

    def test_visually_identified_unanswered_quiz_stays_excluded(self):
        b=diagram(planRole='uncertain')
        result=study.validate({'concepts':[],'excludedBlocks':[{'blockId':b['id'],
            'reason':'OX 퀴즈와 빈칸 채우기 문항만 있으며, 풀이·정답이나 별도 개념 설명은 없습니다.'}],
            'uncertainBlocks':[]},{'id':'quiz','title':'퀴즈','blocks':[b]},
            {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(result['coverage'][0]['state'],'excluded')

    def test_cover_can_be_excluded_after_its_image_was_read(self):
        b=diagram(planRole='uncertain')
        result=study.validate({'concepts':[],'excludedBlocks':[{'blockId':b['id'],
            'reason':'강의명과 강사·소속 등 표지 정보로 독립적인 학습 내용은 없어요.'}],
            'uncertainBlocks':[]},{'id':'cover','title':'표지','blocks':[b]},
            {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(result['coverage'][0]['state'],'excluded')

    def test_confirmed_english_cover_and_unanswered_exercises_stay_excluded(self):
        b=diagram(planRole='uncertain')
        for reason in ['Cover page with course title and instructor name only.',
                       'Table of contents listing chapter headings.',
                       'Title slide with course title and institution name.',
                       '강의 자료의 표지로, 배열 이름과 포인터의 관계를 설명하는 내용이 없어요.',
                       'Unanswered quiz questions only, without solutions.',
                       'Practice problems only; no answers or worked steps are supplied.',
                       '연습 문제만 제시되어 있으며 풀이와 정답이 없습니다.',
                       '연습 문제만 제시되며 풀이를 제공하지 않습니다.',
                       'Unanswered quiz questions; this does not contain a worked solution.']:
            with self.subTest(reason=reason):
                self.assertFalse(unjustified_visual_exclusion(b,reason))

    def test_mentioning_quiz_or_cover_does_not_hide_taught_workings(self):
        b=diagram(planRole='uncertain')
        for reason in ['퀴즈 문항만이 아니라 새로운 풀이와 개념 설명이 있어요.',
                       '표지 정보와 강의명 옆에 새로운 원리 설명이 있어요.',
                       'Quiz questions only, but this contains a worked solution.',
                       'Cover page with course title also includes an explanation.']:
            with self.subTest(reason=reason):
                self.assertTrue(unjustified_visual_exclusion(b,reason))

    def test_cached_navigation_plan_reaches_existing_image_call_once(self):
        b=diagram(planRole='navigation')
        class Provider:
            model='gpt-6-luna';billing=None;ledger={'requests':[]}
            def __init__(self):self.calls=[]
            def complete(self,payload,**kwargs):
                self.calls.append((payload,kwargs))
                assert payload['task']=='region_teaching'
                assert kwargs.get('image')
                return {'concepts':[{'title':'포인터 배열과 배열 원소 포인터',
                    'definition':'포인터 배열은 포인터를 여러 개 담는 배열이에요.',
                    'explanation':'각 포인터 원소는 서로 다른 객체의 주소를 저장할 수 있어요.',
                    'easyExplanation':'여러 주소를 담는 배열과 한 원소의 주소를 담는 포인터를 구분해요.',
                    'blockIds':[payload['blocks'][0]['id']],'standardKnowledgeUsed':False,
                    'tables':[],'sequences':[]}],
                    'excludedBlocks':[],'uncertainBlocks':[]}
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);doc={'documentId':'doc','fingerprint':'fp','pages':[
                {'number':1,'nativeText':b['text'],'label':'1'}],'chunks':[]}
            cache=study.root_path(folder,doc,'new-concept-v99','gpt-6-luna','document',0)
            cache.mkdir(parents=True)
            (cache/'plan.json').write_text(json.dumps(study.plan_record(
                [{'title':'구조 정보','blocks':[copy.deepcopy(b)]}],[],'gpt-6-luna')))
            provider=Provider()
            with patch.object(study,'extract',return_value=[b]),\
                 patch.object(study,'render_crops',return_value=([{'data':'fixture'}],[{'page':1,'blockIds':[b['id']]}])),\
                 patch('pdf_outline.overview',return_value={'body':'포인터를 구분해요.'}):
                result=study.generate(folder,doc,provider)
            self.assertEqual(len(provider.calls),1)
            self.assertTrue(result['processingComplete'])
            self.assertTrue(result['coverageComplete'])
            self.assertEqual(result['coverage'][0]['state'],'summarized')
            self.assertIn('포인터 배열',result['sections'][0]['body'])


if __name__=='__main__':unittest.main()
