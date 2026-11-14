"""Review decoders must emit the exact requested targets on each bounded pass."""
import unittest
from unittest.mock import patch
import pdf_quiz_review as review
import test_pdf_quiz_review as fixtures


class ReviewTargetSchemaTests(unittest.TestCase):
    setUp = fixtures.QuizReviewTests.setUp
    candidates = fixtures.QuizReviewTests.candidates
    run_review = fixtures.QuizReviewTests.run_review

    def test_actual_review_schema_requires_all_targets_without_unknown_ids(self):
        candidates, assignments = self.candidates(('mcq', 'ox', 'essay'))
        _, _, provider = self.run_review([fixtures.approve], candidates, assignments)
        schema = provider.calls[0][1]['response_format']['json_schema']['schema']['properties']['reviews']
        self.assertEqual((schema['minItems'], schema['maxItems']), (3, 3))
        self.assertEqual(schema['items']['properties']['questionId']['enum'], [q['id'] for q in candidates])

    def test_recheck_schema_only_requires_revised_subset_and_cannot_leak_between_calls(self):
        candidates, assignments = self.candidates(('mcq', 'ox', 'essay'))
        original = candidates[1]
        def corrected(payload):
            return {'reviews': [fixtures.verdict(row, decision='revise', issues=['wording'],
                replacement=fixtures.revision(original)) if row['id']==original['id'] else fixtures.verdict(row)
                for row in payload['candidates']]}
        with patch.object(review, 'VERIFY_REVISED_QUESTIONS', True):
            accepted, _, provider = self.run_review([corrected, fixtures.approve], candidates, assignments)
        self.assertEqual(len(accepted), 3)
        schemas=[c[1]['response_format']['json_schema']['schema']['properties']['reviews'] for c in provider.calls]
        self.assertEqual([s['minItems'] for s in schemas], [3,1])
        self.assertEqual(schemas[1]['items']['properties']['questionId']['enum'], [original['id']])
        self.assertEqual(len(schemas[0]['items']['properties']['questionId']['enum']), 3)


if __name__=='__main__':
    unittest.main()
