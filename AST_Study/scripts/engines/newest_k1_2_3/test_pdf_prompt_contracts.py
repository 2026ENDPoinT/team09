"""Integration guards against diverging stage instructions and response contracts."""
import unittest

import pdf_ai as ai
import pdf_outline as outline
import pdf_page_study as page
import pdf_semantic as semantic
import pdf_summary_editor as editor
import pdf_study_policy as policy


class PromptContractTests(unittest.TestCase):
    def test_all_writing_stages_include_one_shared_easy_and_layout_policy(self):
        for prompt in (ai.SYSTEM + ai.MAP_TASK, page.system_prompt(), semantic.STUDY_PROMPT,
                       editor.PROMPT, semantic.CONCEPT_AUDIT_PROMPT):
            with self.subTest(length=len(prompt)):
                self.assertEqual(prompt.count(policy.EASY_EXPLANATION_POLICY), 1)
                self.assertEqual(prompt.count(policy.STUDY_LAYOUT_POLICY), 1)
                self.assertEqual(prompt.count(policy.LEARNER_PROSE_POLICY), 1)
                self.assertNotIn('supersedes', prompt)
                self.assertNotIn('데이먼', prompt)
                for old_fixture_name in ('readlist', 'starbar', 'M1/M2'):
                    self.assertNotIn(old_fixture_name, prompt)

    def test_stage_specific_contracts_do_not_leak_into_other_requests(self):
        self.assertNotIn(policy.CONCEPT_WRITING_POLICY, editor.PROMPT)
        self.assertNotIn(policy.SUMMARY_WRITING_POLICY, semantic.CONCEPT_AUDIT_PROMPT)
        self.assertNotIn('sourceId,quote', page.system_prompt())
        self.assertNotIn('one or two specific sentences', page.system_prompt())
        self.assertNotIn('one or two grounded explanatory sentences', semantic.CONCEPT_AUDIT_PROMPT)
        self.assertNotIn('substantially shorter', editor.PROMPT)
        self.assertNotIn('overview', editor.FORMAT['json_schema']['schema']['properties'])
        audit_card = semantic.CONCEPT_AUDIT_FORMAT['json_schema']['schema']['properties']['decisions']['items']
        self.assertIn('standardKnowledgeUsed', audit_card['required'])
        self.assertIn('example', audit_card['required'])
        self.assertIn('confusion', audit_card['required'])

    def test_flow_payload_never_contains_study_bodies_or_easy_explanations(self):
        items, _ = outline.outline_items([{'title': '함수', 'body': '본문 비밀 표본',
            'parts': [{'title': '함수 호출', 'body': '호출 본문', 'easyExplanation': '새 비유'}]}])
        self.assertEqual(items, [{'id': 's0', 'title': '함수', 'subheadings': ['함수 호출']}])


if __name__ == '__main__':
    unittest.main()
