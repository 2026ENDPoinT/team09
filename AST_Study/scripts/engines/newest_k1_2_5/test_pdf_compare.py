"""Offline checks for the sequential, isolated PDF extraction comparison."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pdf_compare import compare, cumulative_usage, prepare_variant
from pdf_pipeline import check_cancel


def text_pdf(path: Path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 16 Tf 40 200 Td (Direct PDF text) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)


def document():
    return {"documentId": "comparison-test", "fingerprint": "source-v1", "pages": [{
        "number": 1, "label": "1", "nativeText": "old preview", "markdown": "old preview",
        "textRegions": [], "imageRegions": [], "slideLensRegions": [],
    }], "chunks": [], "pageAnalysisStates": [], "pageAnalysisIncompletePages": [1]}


class PdfCompareTests(unittest.TestCase):
    def test_markitdown_repairs_known_equation_font_glyphs(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            text_pdf(folder / "source.pdf")
            original = document()
            original["pages"][0]["fontRepair"] = {
                "replacedGlyphs": 2, "otherPrivateUseGlyphs": 0}
            with patch("markitdown.MarkItDown") as converter:
                converter.return_value.convert_stream.return_value = SimpleNamespace(
                    text_content="\ue035\ue048")
                _, converted, _, _, _ = prepare_variant(folder, original, "markitdown")
            self.assertEqual(converted["pages"][0]["markdown"], "2+")

    def test_source_cancel_stops_variant(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            variant = root / "comparison" / "direct-test"
            variant.mkdir(parents=True)
            (root / "cancel").write_text("cancel", encoding="utf-8")
            with self.assertRaises(InterruptedError):
                check_cancel(variant)

    def test_extractors_have_separate_documents_and_direct_mode_reextracts(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            text_pdf(folder / "source.pdf")
            original = document()
            md_folder, markdown, _, _, _ = prepare_variant(folder, original, "markitdown")
            direct_folder, direct, _, _, _ = prepare_variant(folder, original, "direct")
            self.assertNotEqual(md_folder, direct_folder)
            self.assertIn("Direct PDF text", direct["pages"][0]["nativeText"])
            self.assertEqual(direct["chunks"][0]["field"], "nativeText")
            self.assertEqual(markdown["chunks"][0]["field"], "markdown")
            self.assertEqual(original["pages"][0]["nativeText"], "old preview")
            self.assertNotEqual(markdown["fingerprint"], direct["fingerprint"])
            self.assertTrue((md_folder / "source.pdf").exists())
            self.assertTrue((direct_folder / "source.pdf").exists())
            _, cached, seconds, was_cached, _ = prepare_variant(folder, original, "direct")
            self.assertTrue(was_cached)
            self.assertEqual(seconds, 0)
            self.assertEqual(cached["chunks"], direct["chunks"])

    def test_comparison_runs_markdown_then_direct_with_one_shared_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            events = []

            class FakeProvider:
                def __init__(self, path, allowed, limit, model, **kwargs):
                    events.append(("provider", path.name, round(limit, 2)))
                    self.spent = .1
                    self.ledger = {"requests": [{"state": "settled", "estimatedUsd": .1,
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}}]}

            def fake_prepare(_, base, mode):
                events.append(("extract", mode))
                return folder / mode, base, .2, False, []

            def fake_generate(path, base, provider, scope, page, page_mode):
                events.append(("generate", path.name, scope, page_mode))
                return {"kind": "ai_generated", "documentId": base["documentId"]}

            with patch("pdf_compare.prepare_variant", side_effect=fake_prepare), \
                 patch("pdf_ai.Provider", FakeProvider), \
                 patch("pdf_ai.generation", side_effect=fake_generate):
                result = compare(folder, document(), 2.5, "gpt-6-luna")

            self.assertEqual([entry[0] for entry in events],
                             ["extract", "provider", "generate", "extract", "provider", "generate"])
            self.assertEqual([entry[1] for entry in events if entry[0] == "extract"],
                             ["markitdown", "direct"])
            self.assertEqual([entry[2] for entry in events if entry[0] == "provider"], [2.5, 2.4])
            self.assertEqual(result["usageBasedUsd"], .2)
            self.assertEqual([v["status"] for v in result["variants"]], ["complete", "complete"])
            self.assertEqual(json.loads((folder / "comparison/latest-report.json").read_text(encoding="utf-8"))["kind"],
                             "extraction_comparison")

    def test_exhausted_budget_shows_skipped_second_method_and_prior_spend(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            first = folder / "comparison" / "markitdown-test"
            ledger_dir = first / "usage"
            ledger_dir.mkdir(parents=True)
            (ledger_dir / "prior.json").write_text(json.dumps({"requests": [{"state": "settled",
                "estimatedUsd": .03, "usage": {"prompt_tokens": 10, "completion_tokens": 5}}]}), encoding="utf-8")
            self.assertEqual(cumulative_usage(first)["usageBasedUsd"], .03)

            class ExhaustingProvider:
                def __init__(self, *args, **kwargs):
                    self.spent = .5
                    self.ledger = {"requests": []}

            with patch("pdf_compare.prepare_variant", return_value=(first, document(), 0, False, [])), \
                 patch("pdf_ai.Provider", ExhaustingProvider), \
                 patch("pdf_ai.generation", return_value={"kind": "ai_generated"}):
                result = compare(folder, document(), .5, "gpt-6-luna")
            self.assertEqual([v["status"] for v in result["variants"]],
                             ["complete", "skipped_due_to_budget"])
            self.assertEqual(result["cumulativeUsageBasedUsd"], .03)


if __name__ == "__main__":
    unittest.main()
