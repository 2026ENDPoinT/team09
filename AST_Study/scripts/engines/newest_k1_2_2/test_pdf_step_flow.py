import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdf_ai import PROMPT_VERSION, clean_generated_display_text, map_unit, normalize_generation_result, review_evidence
from pdf_step_flow import validate_sequence


def fixture():
    sentences=["수집 결과를 정제의 입력으로 사용한다.", "정제 결과에 의해 게시할 자료가 결정된다."]
    text=" ".join(sentences)
    chunk={"id":"s1","documentId":"doc","page":1,"source":"native","field":"markdown",
           "text":text,"start":0,"end":len(text),"bbox":None}
    sequence={"title":"자료 처리 순서","orderKind":"procedure","transitions":[
        {"fromStep":0,"toStep":1,"relation":"수집 결과가 정제 입력으로 사용돼요.","blockIds":["s1"],"sourceQuote":sentences[0]},
        {"fromStep":1,"toStep":2,"relation":"정제 결과에 의해 게시할 자료가 정해져요.","blockIds":["s1"],"sourceQuote":sentences[1]}],
        "steps":[{"title":title,"body":body,"evidence":[{"sourceId":"s1","quote":sentences[i]}]}
                 for title,body,i in [("수집","수집으로 원자료를 모아요.",0),
                                      ("정제","수집 결과를 정제해요.",0),("게시","정제한 자료를 게시해요.",1)]]}
    return chunk,sequence


class StepFlowTests(unittest.TestCase):
    def test_generated_math_controls_are_restored_before_cleanup(self):
        result={"body":"구간 \x1c\\Delta x=(b-a)/n\x1c에서 $$"+"\f"+"rac{1}{2}$$"}
        clean_generated_display_text(result)
        self.assertEqual(result["body"],r"구간 \(\Delta x=(b-a)/n\)에서 $$\frac{1}{2}$$")

    def test_both_styles_and_source_links_are_application_owned(self):
        chunk, sequence = fixture()
        for style in ("a", "d"):
            with patch("pdf_step_flow.secrets.choice", return_value=style):
                module = validate_sequence(sequence, {"s1": chunk}, review_evidence)
            self.assertEqual(module["variant"], style)
            self.assertEqual(module["moduleId"], "synesis.step-flow")
            self.assertEqual(module["steps"][1]["evidence"][0]["page"], 1)

    def test_rejects_whole_sequence_if_one_step_lacks_exact_evidence(self):
        chunk, sequence = fixture()
        sequence["steps"][1]["evidence"][0]["quote"] = "존재하지 않는 원문"
        self.assertIsNone(validate_sequence(sequence, {"s1": chunk}, review_evidence))
        self.assertIsNone(validate_sequence({"title": "one", "steps": [sequence["steps"][0]]}, {"s1": chunk}, review_evidence))

    def test_case_only_quote_difference_uses_exact_source_span(self):
        chunk, sequence = fixture()
        chunk["text"] = "수집 결과를 정제의 입력으로 사용한다. 정제 결과에 의해 게시할 자료가 결정된다. First call returns 3."
        sequence["steps"][0]["evidence"][0]["quote"] = "first call returns 3."
        sequence["steps"][1]["evidence"][0]["quote"] = "수집 결과를 정제의 입력으로 사용한다."
        module = validate_sequence(sequence, {"s1": chunk}, review_evidence)
        self.assertIsNotNone(module)
        self.assertEqual(module["steps"][0]["evidence"][0]["quote"], "First call returns 3.")

    def test_same_process_is_not_shown_twice_in_summary_and_concept(self):
        evidence = [{"page": 1, "sourceId": "s1", "quote": "First call returns 3."}]
        from pdf_step_flow import validate_sequence
        chunk,raw=fixture()
        flow=validate_sequence(raw,{"s1":chunk},review_evidence)
        result = {"localPostprocessVersion": 2,
                  "sections": [{"parts": [{"stepFlow": flow}]}],
                  "concepts": [{"entries": [{"stepFlow": {**flow}}]}]}
        normalized = normalize_generation_result(result)
        self.assertEqual(normalized["localPostprocessVersion"], 5)
        self.assertIsNotNone(normalized["sections"][0]["parts"][0]["stepFlow"])
        self.assertIsNone(normalized["concepts"][0]["entries"][0]["stepFlow"])

    def test_generation_attaches_both_outputs_and_cached_style_does_not_change(self):
        chunk, sequence = fixture()
        class Provider:
            calls = 0
            def complete(self, payload, max_output=2400):
                self.calls += 1
                assert "THREE" in payload["task"]
                assert "slideLensRegionId" not in payload["task"]
                assert "excludedElementIds" in payload["task"]
                evidence = sequence["steps"][0]["evidence"]
                return {"summary": {"title": "처리", "parts": [{"title": "순서", "body": "본문 유지",
                    "evidence": evidence, "sequence": sequence}]}, "concepts": [{"name": "처리", "aliases": [],
                    "definition": "정의", "explanation": "설명", "example": "", "confusion": "",
                    "evidence": evidence, "sequence": sequence}]}
        provider = Provider()
        with tempfile.TemporaryDirectory() as directory:
            result = map_unit(provider, Path(directory), [chunk], "one", [])
            self.assertEqual(result, map_unit(provider, Path(directory), [chunk], "one", []))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result["summary"]["parts"][0]["stepFlow"]["steps"][1]["title"], "정제")
        self.assertEqual(result["concepts"][0]["stepFlow"]["schemaVersion"], 1)
        self.assertTrue(PROMPT_VERSION.startswith("pdf-grounded-ko-"))

if __name__ == "__main__":
    unittest.main()
