import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pdf_ai import Provider, BudgetExceeded
from pdf_luna import prepare_luna, compare_generation, validate_page, usage_totals
from pdf_pipeline import enrich_visual_routing


def page_result():
    return {"pageType": "mixed", "visibleText": "에너지는 보존됩니다.", "formulas": [], "tables": [],
        "figures": [{"description": "화살표가 오른쪽을 가리킵니다.", "labels": "에너지", "relationships": "",
                     "possiblePurpose": "에너지 전달을 보여주려는 그림으로 추정합니다.", "uncertainty": "앞뒤 맥락은 없습니다."}],
        "unreadable": []}


def document(root, count=2):
    writer = PdfWriter()
    for n in range(count):
        writer.add_blank_page(width=300+n*10, height=200)
    writer.write(root / "source.pdf")
    return {"documentId": "doc", "fingerprint": "local-v1", "pages": [
        {"number": n, "label": str(n), "nativeText": "OCR_INPUT_MUST_NOT_LEAK"} for n in range(1, count+1)],
        "chunks": [{"id": "local-p1", "documentId": "doc", "page": 1, "source": "native",
                    "field": "markdown", "start": 0, "end": 14, "text": "기존 추출 원문입니다.", "bbox": None}],
        "incompletePages": []}


class LunaTests(unittest.TestCase):
    def test_no_letters_is_not_ocr_failure(self):
        doc = {"pages": [{"number": 8, "nativeText": "", "ocrNeeded": True,
            "status": "needs_review", "ocrBlocks": [{"text": "", "bbox": [0, 0, 1, 1]}],
            "warnings": ["읽을 수 있는 글자 없음 · 스캔/그림 직접 확인 필요", "그림·표·수식의 의미와 OCR 기호는 원본 대조 필요"]},
            {"number": 9, "nativeText": "", "status": "needs_review", "ocrNeeded": True,
             "warnings": ["이미지 OCR 실패 · 재시도 필요"], "ocrBlocks": []}]}
        enrich_visual_routing(doc)
        self.assertEqual(doc["incompletePages"], [])
        self.assertEqual(doc["visualOnlyPages"], [8, 9])
        self.assertEqual(doc["pages"][0]["textState"], "no_text_detected")

    def test_page_images_cache_provenance_usage_and_dual_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = document(root)
            requests = []

            def transport(body):
                requests.append(body)
                text = json.dumps(body, ensure_ascii=False)
                if isinstance(body["messages"][1]["content"], list):
                    self.assertNotIn("OCR_INPUT_MUST_NOT_LEAK", text)
                    self.assertEqual(body["model"], "gpt-6-luna")
                    self.assertEqual(body["messages"][1]["content"][1]["type"], "image_url")
                    value = page_result()
                else:
                    payload = json.loads(body["messages"][1]["content"])
                    source = payload["sources"][0]
                    if source["sourceId"].startswith("luna-"):
                        self.assertNotIn("OCR_INPUT_MUST_NOT_LEAK", text)
                    value = {"summary": {"title": "요약", "body": "근거를 정리합니다.",
                        "evidence": [{"sourceId": source["sourceId"], "quote": source["text"][:20]}]}, "concepts": []}
                return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value, ensure_ascii=False)}}],
                    "usage": {"prompt_tokens": 2000, "completion_tokens": 300,
                              "prompt_tokens_details": {"cached_tokens": 100}}}

            provider = Provider(root, True, .2, "gpt-6-luna", transport)
            result = prepare_luna(root, original, provider)
            self.assertEqual(len(requests), 2)
            self.assertFalse(result["incompletePages"])
            self.assertEqual({c["source"] for c in result["chunks"]}, {"ai_transcription", "ai_visual_observation", "ai_inference"})
            self.assertTrue(all(c["id"].startswith("luna-") for c in result["chunks"]))
            again = prepare_luna(root, original, provider)
            self.assertEqual(len(requests), 2)
            self.assertEqual(again["cachedPages"], 2)
            self.assertEqual(again["fingerprint"], result["fingerprint"])
            usage = usage_totals(root, "luna-extraction")
            self.assertEqual(usage["inputTokens"], 4000)
            self.assertAlmostEqual(usage["usageBasedUsd"], 2 * (1900*.1+100*.01+300*.5)/1e6)
            compared = compare_generation(root, original, provider, "document", 0)
            self.assertEqual(set(compared["results"]), {"local", "luna"})
            self.assertNotEqual(compared["results"]["local"]["sourceFingerprint"], compared["results"]["luna"]["sourceFingerprint"])
            self.assertEqual(compared["results"]["luna"]["overview"]["evidence"][0]["source"], "ai_transcription")
            count = len(requests)
            compare_generation(root, original, provider, "document", 0)
            self.assertEqual(len(requests), count)

    def test_budget_stop_keeps_pages_and_resume(self):
        class Stub:
            model = "gpt-6-luna"
            calls = 0
            def complete(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise BudgetExceeded("한도 도달")
                return page_result()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = document(root)
            stub = Stub()
            partial = prepare_luna(root, original, stub)
            self.assertEqual(partial["incompletePages"], [2])
            completed = prepare_luna(root, original, stub)
            self.assertEqual(stub.calls, 3)
            self.assertFalse(completed["incompletePages"])

    def test_model_cannot_override_page_metadata(self):
        value = {**page_result(), "number": 999, "documentId": "other", "status": "ready"}
        validated = validate_page(value)
        self.assertNotIn("number", validated)
        self.assertNotIn("documentId", validated)


if __name__ == "__main__":
    unittest.main()
