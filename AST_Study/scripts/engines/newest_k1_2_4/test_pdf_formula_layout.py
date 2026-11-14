"""Offline checks for the active generation paths and lossless formula grouping markup."""
import unittest

import pdf_ai
import pdf_new_concept_ver99_study as current
import pdf_page_study
import pdf_summary_editor
from pdf_new_concept_v02_math import format_math
from pdf_study_policy import FORMULA_LAYOUT_POLICY, study_rules


class FormulaLayoutTests(unittest.TestCase):
    def test_active_writers_receive_rule_once_and_tutor_is_unchanged(self):
        for prompt in (current.STUDY_PROMPT, pdf_ai.SYSTEM, pdf_page_study.system_prompt(),
                       pdf_summary_editor.PROMPT, study_rules(concepts=False),
                       study_rules(summaries=False)):
            self.assertEqual(prompt.count(FORMULA_LAYOUT_POLICY), 1)
        self.assertNotIn(FORMULA_LAYOUT_POLICY, current.PLAN_PROMPT)
        self.assertNotIn(FORMULA_LAYOUT_POLICY, pdf_ai.TUTOR_SYSTEM)
        self.assertLess(len(FORMULA_LAYOUT_POLICY.encode()), 450)

    def test_quote_and_conditions_survive_existing_math_cleanup(self):
        text = '> 운동량\n>\n> $$p_i=p_f$$\n>\n> 에너지\n> $$E_i=E_f$$\n>\n> 외력이 없을 때예요.'
        self.assertEqual(format_math(text), text)
        multiline = '> $$\n> x>0\n> $$'
        self.assertEqual(format_math(multiline), multiline)
        self.assertFalse(pdf_ai.study_math_issues({'body': text}))


if __name__ == '__main__':
    unittest.main()
