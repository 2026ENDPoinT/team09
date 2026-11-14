import unittest

from pdf_quiz_difficulty import POLICIES, RECALL_POLICIES, difficulty_instruction


class DifficultyCompilationTests(unittest.TestCase):
    def test_compiles_only_requested_level(self):
        for level, policy in POLICIES.items():
            compiled = difficulty_instruction(level)
            self.assertIn(policy, compiled)
            for other_level, other_policy in POLICIES.items():
                if other_level != level:
                    self.assertNotIn(other_policy, compiled)

    def test_word_clause_is_only_for_selected_high_short_answers(self):
        for level in POLICIES:
            for kinds in (['ox'], ['mcq', 'essay'], ['word'], ['ox', 'word', 'mcq', 'essay']):
                with self.subTest(level=level, types=kinds):
                    self.assertEqual('\nword' in difficulty_instruction(level, kinds),
                                     level in ('상', '최상') and 'word' in kinds)

    def test_unknown_level_fails_instead_of_silently_using_default(self):
        with self.assertRaises(ValueError):
            difficulty_instruction('어려움')

    def test_recall_uses_only_its_selected_level_and_never_inference_clause(self):
        for level, policy in RECALL_POLICIES.items():
            compiled = difficulty_instruction(level, ['ox', 'mcq', 'word', 'essay'], 'recall')
            self.assertIn(policy, compiled)
            self.assertNotIn('\nword', compiled)
            self.assertNotIn('법칙명을 떠올리거나', compiled)
            for other_level, other_policy in RECALL_POLICIES.items():
                if other_level != level:
                    self.assertNotIn(other_policy, compiled)
            for general_policy in POLICIES.values():
                self.assertNotIn(general_policy, compiled)

    def test_other_themes_keep_the_existing_general_policy(self):
        for level in POLICIES:
            for theme in ('concept_completion', 'understanding', 'practice_set'):
                self.assertEqual(difficulty_instruction(level, ['word'], theme),
                                 difficulty_instruction(level, ['word']))


if __name__ == '__main__':
    unittest.main()
