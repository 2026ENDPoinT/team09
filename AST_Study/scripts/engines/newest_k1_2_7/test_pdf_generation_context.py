import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from pdf_ai import (Provider, BudgetExceeded, ContextBudgetExceeded, REQUEST_INPUT_BOUND, SYSTEM,
                    generation, map_unit, merge_concepts, split_unit, split_visual_notes)
from pdf_generation_context import GENERATION_UNIT_MAX_BYTES, GENERATION_UNIT_MAX_CHUNKS, generation_units, previous_context, relevant_concept_names


def source(text, page=1):
    return {"id": f"c{page}", "documentId": "doc", "page": page, "source": "native",
            "field": "markdown", "start": 0, "end": len(text), "text": text, "bbox": None}


def answer(payload):
    if "sources" not in payload:
        return {"title": "전체", "body": "전체 흐름", "evidence":
                [e for s in payload["summaries"] for e in s["evidence"]][:4]}
    evidence = [{"sourceId": s["sourceId"], "quote": s["text"][:30]} for s in payload["sources"]]
    return {"summary": {"title": "내용", "body": "설명", "evidence": evidence}, "concepts": [
        {"name": "같은 개념", "aliases": ["same concept"], "definition": "정의", "explanation": "구간별 설명",
         "example": "", "confusion": "", "evidence": evidence}]}


class GenerationContextTests(unittest.TestCase):
    def test_complete_page_image_supports_concept_when_model_text_citation_is_invalid(self):
        class VisualProvider:
            model = "test-provider"
            def complete(self, payload, max_output=2400):
                return {"summary":{"title":"벡터 관계","body":"벡터 관계를 설명한다.",
                        "evidence":[{"sourceId":"c1","quote":"벡터 관계를 설명한다"}]},
                    "concepts":[{"name":"벡터 관계","aliases":[],"definition":"방향을 나타낸다.",
                        "explanation":"그림의 화살표로 방향을 확인한다.","example":"","confusion":"",
                        "evidence":[{"sourceId":"invented","quote":"존재하지 않는 인용"}],"visualPages":[1]}]}
        chunk=source("벡터 관계를 설명한다",1)
        document={"pages":[{"pageAnalysis":{"status":"ready"}}],"chunks":[chunk]}
        notes=[{"page":1,"description":"벡터 방향 화살표","visibleRelationships":[],"uncertainDetails":[]}]
        with tempfile.TemporaryDirectory() as directory:
            result=map_unit(VisualProvider(),Path(directory),[chunk],"unit",[],notes,document=document)
        card=result["concepts"][0]
        self.assertEqual(card["evidence"],[])
        self.assertTrue(card["visualEvidenceOnly"])
        self.assertFalse(card["evidenceIncomplete"])

    def test_document_context_is_stable_across_process_hash_seeds(self):
        words = " ".join(f"term{index:02}" for index in range(30))
        document = {"pages": [{"markdown": words}, {"markdown": words}]}
        script = ("import json,sys; from pathlib import Path; "
                  "sys.path.insert(0, sys.argv[1]); "
                  "from pdf_study_policy import document_context; "
                  "document=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')); "
                  "print(json.dumps(document_context(document),ensure_ascii=False))")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            outputs = [subprocess.check_output(
                [sys.executable, "-c", script, str(Path(__file__).parent), str(path)],
                env={**os.environ, "PYTHONHASHSEED": seed}, text=True)
                for seed in ("1", "2", "3")]
        self.assertEqual(len(set(outputs)), 1)
        self.assertEqual(json.loads(outputs[0])["recurringTerms"],
                         [f"term{index:02}" for index in range(20)])

    def test_parallel_provider_reservations_respect_budget_and_page_context(self):
        def transport(body):
            time.sleep(.08)
            return {"choices":[{"finish_reason":"stop","message":{"content":"{}"}}],
                    "usage":{"prompt_tokens":10,"completion_tokens":2}}

        with tempfile.TemporaryDirectory() as directory:
            provider = Provider(Path(directory), True, .009, "gpt-6-luna", transport)

            def request(page):
                provider.context = {"kind":"page_summary","page":page}
                try:
                    provider.complete({"page":page}, max_output=6500)
                    return True
                except BudgetExceeded:
                    return False

            with ThreadPoolExecutor(max_workers=3) as pool:
                outcomes = list(pool.map(request, [1,2,3]))
            self.assertTrue(any(outcomes))
            self.assertTrue(any(not done for done in outcomes))
            entries = provider.ledger["requests"]
            self.assertLessEqual(sum(e["reservedUsd"] for e in entries),provider.max_usd)
            self.assertEqual({e["page"] for e in entries},
                             {page for page,done in zip([1,2,3],outcomes) if done})
            saved = json.loads(provider.ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["requests"]),len(entries))

    def test_old_32k_guard_no_longer_rejects_valid_request(self):
        seen = []
        def transport(body):
            seen.append(body)
            return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
        with tempfile.TemporaryDirectory() as directory:
            provider = Provider(Path(directory), True, .2, "gpt-6-luna", transport)
            provider.complete({"text": "자료" * 6000})
            self.assertEqual(len(seen), 1)
            self.assertGreater(provider.ledger["requests"][0]["inputTokenBound"], 32000)
            with self.assertRaises(ContextBudgetExceeded):
                provider.complete({"text": "자료" * REQUEST_INPUT_BOUND})
            self.assertEqual(len(seen), 1)  # Rejected before network/billing.

    def test_chapter_boundary_preferred_and_sources_covered_exactly_once(self):
        chunks = [source(("# New chapter\n" if p == 3 else "plain slide\n") + "x" * 800, p)
                  for p in range(1, 9)]
        doc = {"pages": [{"markdown": c["text"]} for c in chunks], "chunks": chunks}
        units = list(generation_units(chunks, doc, 4000))
        self.assertEqual([c["page"] for c in units[0]], [1, 2])
        self.assertEqual([c["id"] for u in units for c in u], [c["id"] for c in chunks])

    def test_default_unit_size_can_hold_three_medium_pages(self):
        self.assertEqual(GENERATION_UNIT_MAX_BYTES, 24000)
        chunks = [source("가" * 2000, p) for p in range(1, 4)]
        doc = {"pages": [{"markdown": c["text"]} for c in chunks], "chunks": chunks}
        self.assertEqual([[c["page"] for c in unit] for unit in generation_units(chunks, doc)],
                         [[1, 2, 3]])

    def test_source_count_remains_within_evidence_review_capacity(self):
        self.assertEqual(GENERATION_UNIT_MAX_CHUNKS, 12)
        chunks = [source(f"slide {p}", p) for p in range(1, 21)]
        doc = {"pages": [{"markdown": c["text"]} for c in chunks], "chunks": chunks}
        self.assertEqual([len(unit) for unit in generation_units(chunks, doc)], [12, 8])

    def test_background_previous_three_only_without_citation_ids(self):
        doc = {"pages": [{"markdown": f"page {p} " + "가" * 3000} for p in range(1, 9)]}
        context = previous_context(doc, [source("target", 6)])
        self.assertEqual([c["page"] for c in context], [3, 4, 5])
        self.assertTrue(all(c["backgroundOnly"] and c["excerpted"] for c in context))
        self.assertTrue(all("sourceId" not in c for c in context))

    def test_relevant_early_concept_survives_more_than_40_later_names(self):
        names = ["Energy conservation"] + [f"unrelated term {n}" for n in range(100)]
        self.assertEqual(relevant_concept_names(names, [source("Energy conservation in motion")])[0], names[0])

    def test_filtered_source_split_preserves_all_visible_text(self):
        chunk = source("logo\n" + "학습내용\n" * 500)
        chunk["aiText"] = "학습내용\n" * 500
        left, right = split_unit([chunk])
        self.assertEqual(left[0]["aiText"] + right[0]["aiText"], chunk["aiText"])
        self.assertEqual(left[0]["text"], chunk["text"])

    def test_input_overflow_adapts_and_completed_children_are_reused(self):
        class SmallProvider:
            calls = 0
            def complete(self, payload, max_output=2400):
                self.calls += 1
                if sum(len(s["text"]) for s in payload["sources"]) > 1500:
                    raise ContextBudgetExceeded("split")
                return answer(payload)
        chunk = source("원문내용 " * 1200)
        with tempfile.TemporaryDirectory() as directory:
            provider = SmallProvider()
            cache = Path(directory)
            result = map_unit(provider, cache, [chunk], "unit", [])
            self.assertGreater(len(result["concepts"]), 1)
            calls = provider.calls
            (cache / "unit.json").unlink()
            self.assertEqual(map_unit(provider, cache, [chunk], "unit", []), result)
            self.assertEqual(provider.calls, calls)

    def test_split_passes_visual_notes_only_to_own_page(self):
        seen = []
        class PageProvider:
            def complete(self, payload, max_output=2400):
                if len(payload["sources"]) > 1:
                    raise ContextBudgetExceeded("split")
                seen.append(payload)
                return answer(payload)
        with tempfile.TemporaryDirectory() as directory:
            map_unit(PageProvider(), Path(directory), [source("first", 1), source("second", 2)], "unit", [],
                     [{"page": 1, "description": "first image"}, {"page": 2, "description": "second image"}])
        self.assertEqual([[n["page"] for n in p["visualNotes"]] for p in seen], [[1], [2]])

    def test_single_large_visual_note_is_split_without_losing_text(self):
        note = {"page": 1, "description": "diagram " * 5000, "visibleRelationships": [], "uncertainDetails": []}
        left, right = split_visual_notes([note])
        self.assertEqual(left[0]["description"] + right[0]["description"], note["description"])

    def test_180_pages_keep_every_source_and_merge_distant_concepts(self):
        chunks = [source(f"page {p} same concept " + "설명 " * 170, p) for p in range(1, 181)]
        doc = {"documentId": "doc", "fingerprint": "long", "incompletePages": [],
               "pages": [{"markdown": c["text"]} for c in chunks], "chunks": chunks}
        seen = []
        class LongProvider:
            model = "test"
            def complete(self, payload, max_output=2400):
                bound = len(json.dumps([{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], ensure_ascii=False).encode()) + 2048
                if bound > REQUEST_INPUT_BOUND:
                    raise ContextBudgetExceeded("split")
                if "sources" in payload:
                    seen.extend(s["sourceId"] for s in payload["sources"])
                return answer(payload)
        with tempfile.TemporaryDirectory() as directory, patch("pdf_ai.emit"):
            result = generation(Path(directory), doc, LongProvider())
        self.assertEqual(seen, [c["id"] for c in chunks])
        self.assertEqual(result["sourcePages"], list(range(1, 181)))
        self.assertEqual(result["concepts"][0]["pages"], list(range(1, 181)))
        self.assertEqual(sum(len(c["evidence"]) for c in result["concepts"][0]["entries"]), 180)

    def test_alias_bridge_preserves_original_order_and_all_entries(self):
        cards = [{"name": "A", "aliases": [], "evidence": [{"page": 1}]},
                 {"name": "B", "aliases": [], "evidence": [{"page": 80}]},
                 {"name": "C", "aliases": ["A", "B"], "evidence": [{"page": 180}]}]
        merged = merge_concepts(cards)
        self.assertEqual(merged[0]["name"], "A")
        self.assertEqual(merged[0]["entries"], cards)
        self.assertEqual(merged[0]["pages"], [1, 80, 180])


if __name__ == "__main__":
    unittest.main()
