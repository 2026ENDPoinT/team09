import unittest

from pdf_chart_titles import chart_title_owners, repair_chart_groups
from pdf_group_partition import validate_partition
from pdf_new_concept_v02_regions import crop_runs
from pdf_newest_k1_2_0 import jobs_for, normalize_groups


def block(key, page, text, box, *, kind='text', zone=0):
    visual = kind == 'visual'
    return dict(id=key, page=page, text=text, bbox=box, kind=kind, zone=zone,
                hasVisual=visual, visualOnly=visual,
                visualKinds=['vector'] if visual else [], planRole='teaching')


def chart(page, title):
    ticks = [
        block(f'{page}-axis-{n}', page, f'{n}%', [.89, y, .94, y+.025])
        for n, y in ((80, .05), (75, .14), (70, .22), (65, .30), (60, .40))
    ]
    return ticks[:2] + [
        block(f'{page}-body', page, '', [.14, .15, .86, .54], kind='visual'),
    ] + ticks[2:] + [
        block(f'{page}-strip', page, '', [.14, .59, .86, .68], kind='visual', zone=1),
        block(f'{page}-legend', page, '공립 사립', [.3, .83, .6, .86], kind='heading', zone=1),
        block(f'{page}-title', page, title, [.4, .92, .93, .95], kind='heading', zone=1),
    ]


class ChartTitleTests(unittest.TestCase):
    def test_saved_cross_page_title_stays_with_its_own_chart_and_crop(self):
        high_school = chart(19, '설립 유형별 고등학교 수 및 사립고 비율 (1965-2020)')
        university = chart(20, '설립 유형별 대학 수 및 사립대학의 비율 (1965-2023)')
        blocks = high_school + university
        saved = [{'title':'고등학교','blocks':high_school[:-1]},
                 {'title':'대학','blocks':high_school[-1:] + university}]
        for groups in (repair_chart_groups(blocks, saved), normalize_groups(blocks, saved)):
            self.assertTrue(validate_partition(blocks, groups)['complete'])
            self.assertEqual([g['blocks'] for g in groups], [high_school, university])
            self.assertEqual([j['blocks'] for j in jobs_for(groups)], [high_school, university])
            self.assertEqual(crop_runs(university), [university])
        self.assertIs(saved[1]['blocks'][0], high_school[-1])

    def test_topic_heading_without_same_page_axes_still_follows_its_prose(self):
        photo = block('photo', 19, '', [.2, .2, .8, .7], kind='visual')
        heading = block('topic', 19, '고등학교 비율 추세 (1965-2020)', [.4, .92, .93, .95],
                        kind='heading')
        prose = block('body', 20, '고등학교의 수업에 관한 일반 설명', [.1, .1, .9, .3])
        blocks = [photo, heading, prose]
        groups = [{'title':'사진','blocks':blocks[:2]}, {'title':'본문','blocks':blocks[2:]}]
        self.assertEqual(chart_title_owners(blocks), {})
        self.assertEqual([g['blocks'] for g in normalize_groups(blocks, groups)],
                         [[photo], [heading, prose]])


if __name__ == '__main__':
    unittest.main()
