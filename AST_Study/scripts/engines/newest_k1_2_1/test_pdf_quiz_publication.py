"""Regression: every returned item survives, with no invented answers or citations."""
import copy
import unittest
import pdf_quiz as quiz
from test_pdf_quiz import fixture, question, planned

class PublicationTests(unittest.TestCase):
    def test_ox_answer_with_explanation_remains_failed_and_untrimmed(self):
        doc,req=fixture(); *_,concepts,sources=quiz.context(doc,req)
        raw=question('ox');raw['answer']='X. 조건이 다르기 때문이다.'
        before=copy.deepcopy(raw)
        items,rejected=quiz.validate_questions({'questions':[raw]},planned()['allocations'][0],concepts,sources,set())
        self.assertEqual(raw,before)
        self.assertEqual((len(items),rejected),(1,0))
        self.assertEqual(items[0]['type'],'essay')
        self.assertEqual(items[0]['answer'],raw['answer'])
        self.assertEqual(items[0]['rawQuestion']['type'],'ox')
        self.assertTrue(items[0]['warnings'])

    def test_warning_keeps_assigned_target_trace_without_dropping_question(self):
        doc, req = fixture(); *_, concepts, sources = quiz.context(doc, req)
        raw = question('word')
        raw.update(targetId='t7', evidence=[{'sourceId': 'missing', 'quote': 'missing'}])
        items, rejected = quiz.validate_questions({'questions': [raw]}, planned()['allocations'][0],
                                                   concepts, sources, set())
        self.assertEqual((len(items), rejected), (1, 0))
        self.assertEqual(items[0]['targetId'], 't7')
        self.assertEqual(items[0]['rawQuestion'], raw)
        self.assertTrue(items[0]['warnings'])

    def test_malformed_wire_choices_and_warnings_remain_visible(self):
        from pdf_quiz_response import assemble_answers
        doc, req = fixture(); *_, concepts, sources = quiz.context(doc, req)
        assignment = planned()['allocations'][0]
        raw = question('mcq'); raw.pop('options')
        raw.update(answer='원래 정답', distractors=[{'text':'남은 보기 하나','explanation':'설명'},
                    {'text':'남은 보기 둘','explanation':'설명'}], warnings=None)
        items, rejected = quiz.validate_questions(assemble_answers({'questions':[raw]}), assignment, concepts, sources, set())
        self.assertEqual((len(items), rejected), (1, 0))
        self.assertEqual(items[0]['type'], 'essay')
        self.assertIn('남은 보기 하나', items[0]['stem'])
        self.assertIn('남은 보기 둘', items[0]['stem'])
        self.assertIn('원래 정답', items[0]['stem'])
        self.assertEqual(items[0]['rawQuestion']['distractors'], raw['distractors'])

    def test_malformed_and_missing_fields_are_visible_without_false_citations(self):
        doc, req = fixture(); *_, concepts, sources = quiz.context(doc, req)
        assignment = planned()['allocations'][0]
        cases = [question('mcq'), question('essay'), question('ox'), 'broken item']
        cases[0]['options'].pop()
        cases[1]['evidence'] = [{'sourceId': 'fake', 'quote': 'fake'}]
        cases[1]['keyPoints'] = []
        cases[2]['answer'] = ''
        before = copy.deepcopy(cases)
        items, rejected = quiz.validate_questions({'questions': cases}, assignment, concepts, sources, set())
        self.assertEqual(cases, before)
        self.assertEqual((len(items), rejected), (4, 0))
        self.assertTrue(all(q['warnings'] for q in items))
        self.assertEqual(items[0]['type'], 'essay')
        self.assertIn(cases[0]['options'][0]['text'], items[0]['stem'])
        self.assertEqual(items[1]['evidence'], [])
        self.assertEqual(items[2]['answer'], '생성 응답에 답안이 없어요.')
        self.assertEqual([q['rawQuestion'] for q in items], before)

if __name__ == '__main__': unittest.main()
