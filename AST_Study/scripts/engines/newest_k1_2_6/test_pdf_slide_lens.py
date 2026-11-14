import json
import tempfile
import unittest
from pathlib import Path

import pdfplumber
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject

from pdf_pipeline import table_regions, text_regions
from pdf_slide_lens import candidates, validate_selection, ensure_region_catalog, prompt_catalog
from pdf_ai import map_unit


class SlideLensTests(unittest.TestCase):
    def test_placement_marker_requires_valid_region_and_stays_in_one_field(self):
        from pdf_slide_lens import normalize_placement
        fields = {"body": "앞 설명\n\n[[SLIDE_LENS]]\n\n뒤 설명", "example": "[[SLIDE_LENS]]\n예시"}
        valid = normalize_placement(fields, {"regionId": "verified"})
        self.assertEqual(valid["body"].count("[[SLIDE_LENS]]"), 1)
        self.assertNotIn("[[SLIDE_LENS]]", valid["example"])
        invalid = normalize_placement(fields, None)
        self.assertTrue(all("[[SLIDE_LENS]]" not in value for value in invalid.values()))
        fenced = normalize_placement({"body": "```text\n[[SLIDE_LENS]]\n```\n\n[[SLIDE_LENS]]"},
                                      {"regionId": "verified"})
        self.assertEqual(fenced["body"].count("[[SLIDE_LENS]]"), 1)

    def test_placement_marker_does_not_enter_overview_reduction(self):
        from pdf_ai import reduction_briefs
        summaries = [{"title": "주제", "body": "앞 설명\n\n[[SLIDE_LENS]]\n\n뒤 설명",
                      "evidence": [], "visualPages": []}]
        self.assertNotIn("[[SLIDE_LENS]]", reduction_briefs(summaries)[0]["summary"]["body"])

    def test_vector_table_has_a_real_crop_and_ai_cannot_choose_arbitrary_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "table.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(width=612, height=792)
            # A two-by-two vector table: no embedded raster image exists.
            lines = ["100 500 m 400 500 l S", "100 550 m 400 550 l S", "100 600 m 400 600 l S",
                     "100 500 m 100 600 l S", "250 500 m 250 600 l S", "400 500 m 400 600 l S"]
            stream = DecodedStreamObject()
            stream.set_data("\n".join(lines).encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
            with path.open("wb") as output:
                writer.write(output)
            with pdfplumber.open(path) as pdf:
                regions = table_regions(pdf.pages[0])
            self.assertEqual(len(regions), 1)
            document = {"pages": [{"tableRegions": regions, "imageRegions": [], "words": []}]}
            catalog = candidates(document, [1])
            region_id = catalog[0]["regionId"]
            self.assertRegex(region_id, r"^sl1-p1-table-[a-f0-9]{12}$")
            self.assertEqual(document["pages"][0]["slideLensRegions"][0]["regionId"], region_id)
            chosen = validate_selection(region_id, catalog, {1})
            self.assertEqual(chosen["moduleId"], "synesis.slide-lens")
            self.assertEqual(chosen["bbox"], regions[0]["bbox"])
            self.assertIsNone(validate_selection(region_id, catalog, {2}))
            self.assertIsNone(validate_selection("p1-table-42", catalog, {1}))

    def test_small_footer_is_not_offered_and_important_image_is(self):
        document = {"pages": [{"imageRegions": [
            {"bbox": [.4, .93, .55, .98]}, {"bbox": [.15, .2, .8, .75]}],
            "tableRegions": [], "words": []}]}
        ids = [x["regionId"] for x in candidates(document, [1])]
        self.assertEqual(len(ids), 1)
        self.assertRegex(ids[0], r"^sl1-p1-image-[a-f0-9]{12}$")
        original_id = document["pages"][0]["slideLensRegions"][1]["regionId"]
        document["pages"][0]["imageRegions"].reverse()
        self.assertFalse(ensure_region_catalog(document))
        self.assertEqual(document["pages"][0]["slideLensRegions"][1]["regionId"], original_id)
        document["pages"][0]["imageRegions"].append({"bbox": [.2, .3, .7, .6]})
        self.assertTrue(ensure_region_catalog(document))
        self.assertEqual(document["pages"][0]["slideLensRegions"][1]["regionId"], original_id)
        self.assertEqual(len(document["pages"][0]["slideLensRegions"]), 3)
        self.assertIn(document["pages"][0]["slideLensRegions"][2]["regionId"],
                      [item["regionId"] for item in candidates(document, [1])])

    def test_dense_catalog_keeps_every_id_when_prompt_context_is_compacted(self):
        catalog = [{"regionId": f"sl1-p1-image-{number:012x}", "page": 1,
                    "kind": "image", "bbox": [.1, .2, .8, .7],
                    "cue": "설명 " * 100, "nearbyText": "주변 글자 " * 100}
                   for number in range(200)]
        compact = prompt_catalog(catalog)
        self.assertEqual([item["regionId"] for item in compact], [item["regionId"] for item in catalog])
        self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False).encode()), 24000)

    def test_text_only_example_can_be_selected_by_its_measured_paragraph_box(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "example.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(width=612, height=792)
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
                DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 100 650 Td (Worked example begins here) Tj "
                            b"0 -15 Td (The second line continues it) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
            with path.open("wb") as output:
                writer.write(output)
            with pdfplumber.open(path) as pdf:
                regions = text_regions(pdf.pages[0])
            self.assertEqual(len(regions), 1)
            self.assertIn("second line", regions[0]["text"])
            document = {"pages": [{"textRegions": regions, "imageRegions": [],
                                    "tableRegions": [], "words": []}]}
            self.assertRegex(candidates(document, [1])[0]["regionId"], r"^sl1-p1-text-[a-f0-9]{12}$")

    def test_map_result_binds_crop_to_cited_page_and_discards_unknown_id(self):
        chunk = {"id": "source-1", "documentId": "doc", "page": 1, "source": "native",
                 "field": "markdown", "start": 0, "end": 17,
                 "text": "그림으로 관계를 설명합니다", "bbox": None}
        document = {"documentId": "doc", "pages": [{"imageRegions": [
                    {"bbox": [.1, .2 + .01 * i, .8, .7 + .01 * i]} for i in range(20)],
                    "tableRegions": [], "words": []}], "chunks": [chunk]}
        region_id = candidates(document, [1])[-1]["regionId"]

        class FakeProvider:
            def complete(self, payload, max_output=6500):
                assert "regionCatalog" not in payload
                assert "SlideLens" not in payload["task"]
                assert "slideLensRegionId" not in payload["task"]
                assert "[[SLIDE_LENS]]" not in payload["task"]
                assert region_id.startswith("sl1-p1-image-")
                assert payload["sources"][0]["page"] == 1
                evidence = [{"sourceId": "source-1", "quote": "그림으로 관계를 설명합니다"}]
                return {"summary": {"title": "관계", "parts": [{"title": "그림", "body": "관계를 설명합니다.\n\n[[SLIDE_LENS]]\n\n그림에서 확인합니다.",
                    "easyExplanation": "그림을 보면 이해돼요.", "evidence": evidence,
                    "slideLensRegionId": region_id}], "visualPages": []},
                    "concepts": [{"name": "관계", "aliases": [], "definition": "정의", "explanation": "설명\n\n[[SLIDE_LENS]]",
                    "easyExplanation": "쉬운 설명", "example": "", "confusion": "",
                    "evidence": evidence, "visualPages": [], "slideLensRegionId": "p1-image-99"}],
                    "processingNotes": []}

        with tempfile.TemporaryDirectory() as folder:
            result = map_unit(FakeProvider(), Path(folder), [chunk], "one", [], document=document)
        self.assertEqual(result["summary"]["parts"][0]["slideLens"]["page"], 1)
        self.assertIn("[[SLIDE_LENS]]", result["summary"]["parts"][0]["body"])
        self.assertIsNone(result["concepts"][0]["slideLens"])
        self.assertNotIn("[[SLIDE_LENS]]", result["concepts"][0]["explanation"])


if __name__ == "__main__":
    unittest.main()
