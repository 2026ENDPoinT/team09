import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from pdf_ai import BudgetExceeded, Provider, load_visual_notes, PRICES, map_unit, analyze_selected_image, selected_generation_sources
from pdf_pipeline import image_regions
from pdf_visual import analyze_images, candidates, context, fixed_repeat_groups, inspect_repeat_objects, plan, render_region, validate, SYSTEM


def reply(role="concept", importance="default", review=False):
    if importance == "default":
        importance = 0 if role in {"logo", "watermark", "mascot", "decoration"} else None if role == "uncertain" else 2
    needed = importance in (1, 2)
    return {"role": role, "importance": importance,
            "purposes": ["uncertain" if importance is None else "decoration" if importance == 0 else "concept_explanation"],
            "needsImageReview": review, "imageReviewReason": "새 문맥에서 확인해야 하는 화살표가 관찰 정보에 없습니다." if review else "",
            "roleReason": "문맥과 그림의 관계", "explanationMarkdown": "## 원리\n\n관계를 설명합니다." if needed else "",
            "visibleRelationships": ["대상 간 관계"] if needed else [], "uncertainDetails": [],
            "observation": {"description": "그림에 표시된 대상과 선", "visibleRelationships": ["선으로 연결되어 있습니다."], "uncertainDetails": []}}


def fixture(folder, boxes=None, count=3):
    boxes = boxes or [[.03, .9, .12, .96]]
    writer = PdfWriter()
    pages = []
    for n in range(count):
        page = writer.add_blank_page(width=300, height=200)
        stream = DecodedStreamObject()
        stream.set_data(b"1 0 0 rg 0 100 300 100 re f 0 0 1 rg 0 0 300 100 re f")
        page[NameObject("/Contents")] = writer._add_object(stream)
        pages.append({"markdown": f"{n+1}쪽 고유한 학습 문맥", "ocrBlocks": [],
                      "imageRegions": [{"bbox": box, "imageHash": "same-graphic"} for box in boxes]})
    writer.write(folder / "source.pdf")
    return {"documentId": "test-doc", "fingerprint": "test-v1", "pages": pages, "chunks": []}


class FakeProvider:
    model = "gpt-6-luna"
    spent = 0

    def __init__(self, role="concept", fail_at=None):
        self.calls = []
        self.images = []
        self.role, self.fail_at = role, fail_at

    def complete(self, payload, max_output, image, system_prompt):
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise BudgetExceeded("test budget")
        self.calls.append(payload)
        self.images.append(image is not None)
        if image is not None:
            assert max(image["width"], image["height"]) <= 1600
        assert "precedingAndCurrentContext" in payload
        assert "professor" in system_prompt
        return reply(self.role)


class VisualTests(unittest.TestCase):
    def setUp(self):
        progress = patch("pdf_visual.emit")
        progress.start()
        self.addCleanup(progress.stop)

    def test_exercise_role_is_accepted_and_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=1)
            provider = FakeProvider("exercise")
            result = analyze_images(folder, doc, provider)
            self.assertEqual(result["completed"], 1)
            self.assertEqual(result["pending"], 0)
            self.assertEqual(result["stopReason"], "")
            self.assertEqual(result["assessments"][0]["role"], "exercise")
            self.assertEqual(len(load_visual_notes(folder, doc, [1])), 1)

    def test_context_change_replaces_stale_published_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=1)
            analyze_images(folder, doc, FakeProvider())
            self.assertEqual(len(load_visual_notes(folder, doc, [1])), 1)
            doc["pages"][0]["markdown"] = "다른 주제로 수정된 원문"
            self.assertEqual(load_visual_notes(folder, doc, [1]), [])
            self.assertEqual(plan(folder, doc, PRICES["gpt-6-luna"])["pending"], 1)
            self.assertEqual(list((folder / "generated" / "visual-pages").glob("*.json")), [])

    def test_long_useful_image_explanation_reaches_summary_without_character_cutoff(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=1)
            explanation = "A" * 2300
            class Detailed(FakeProvider):
                def complete(self, payload, max_output, image, system_prompt):
                    value = super().complete(payload, max_output, image, system_prompt)
                    value["explanationMarkdown"] = explanation
                    value["roleReason"] = "B" * 500
                    value["observation"]["description"] = "C" * 1900
                    return value
            analyze_images(folder, doc, Detailed())
            notes = load_visual_notes(folder, doc, [1])
            self.assertEqual(notes[0]["description"], explanation)
            self.assertEqual(notes[0]["roleReason"], "B" * 500)

    def test_legacy_manual_prose_is_preserved_but_not_treated_as_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=1)
            class Manual:
                model = "gpt-6-luna"
                def complete(self, payload, max_output, image):
                    return {k: v for k, v in reply().items() if k in ("explanationMarkdown", "visibleRelationships", "uncertainDetails")}
            analyze_selected_image(folder, doc, 1, 0, Manual())
            provider = FakeProvider()
            result = analyze_images(folder, doc, provider)
            self.assertEqual(provider.images, [True])
            self.assertEqual(len(result["explanations"]), 1)
            self.assertEqual(len(load_visual_notes(folder, doc, [1])), 1)
            self.assertEqual(len(list((folder / "generated" / "visual-pages").glob("*.json"))), 2)

    def test_importance_zero_does_not_leak_old_manual_description_into_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=1)
            class Manual:
                model = "gpt-6-luna"
                def complete(self, payload, max_output, image):
                    return {k: v for k, v in reply().items() if k in ("explanationMarkdown", "visibleRelationships", "uncertainDetails")}
            analyze_selected_image(folder, doc, 1, 0, Manual())
            analyze_images(folder, doc, FakeProvider("mascot"))
            self.assertEqual(load_visual_notes(folder, doc, [1]), [])
            self.assertTrue(list((folder / "generated" / "visual-pages").glob("*.json")))

    def test_multiple_images_without_ocr_produce_one_page_source(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, [[.1, .1, .5, .5], [.6, .6, .9, .9]], count=1)
            analyze_images(folder, doc, FakeProvider())
            _, chunks, notes = selected_generation_sources(folder, doc, "document", None)
            self.assertEqual(len(notes), 2)
            self.assertEqual([x["id"] for x in chunks], ["visual-p1"])

    def test_many_image_notes_are_all_sent_in_bounded_summary_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            unit = [{"id": "s1", "documentId": "doc", "page": 1, "source": "native", "text": "원문",
                     "field": "markdown", "start": 0, "end": 2, "bbox": None}]
            notes = [{"page": 1, "regionId": str(i), "description": "그림 설명 " * 80} for i in range(20)]
            received = []
            class Mock:
                def complete(self, payload, max_output):
                    self.assert_bound = len(json.dumps(payload["visualNotes"], ensure_ascii=False).encode())
                    assert self.assert_bound <= 24000
                    received.extend(x["regionId"] for x in payload["visualNotes"])
                    return {"summary": {"title": "주제", "body": "설명", "evidence": [{"sourceId": "s1", "quote": "원문"}]}, "concepts": []}
            map_unit(Mock(), folder, unit, "many-images", [], notes)
            self.assertEqual(received, [str(i) for i in range(20)])
            map_unit(Mock(), folder, unit, "many-images", [], notes)
            self.assertEqual(len(received), 20)

    def test_fixed_zero_logo_120_pages_calls_once_then_skips_locally(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=120)
            provider = FakeProvider("logo")
            result = analyze_images(folder, doc, provider)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(sum(provider.images), 1)
            self.assertEqual((result["skipped"], result["localZeroSkips"], result["pending"]), (120, 119, 0))
            self.assertEqual(result["observationReuses"], 0)
            self.assertEqual(result["assessments"][-1]["decisionSource"], "fixed_repeat_cache")
            self.assertEqual(result["importanceCounts"], {"0": 120, "1": 0, "2": 0, "undetermined": 0})
            self.assertEqual(result["explanations"], [])
            self.assertEqual(load_visual_notes(folder, doc, range(1, 121)), [])
            self.assertEqual(plan(folder, doc, PRICES[provider.model])["pending"], 0)
            analyze_images(folder, doc, provider)
            self.assertEqual(len(provider.calls), 1)

    def test_fixed_zero_resumes_from_saved_classification_without_calls(self):
        from pdf_visual import cache_path
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder)
            analyze_images(folder, doc, FakeProvider("mascot"))
            for item in candidates(doc)[1:]:
                cache_path(folder, item).unlink()
            provider = FakeProvider()
            result = analyze_images(folder, doc, provider)
            self.assertEqual(provider.calls, [])
            self.assertEqual(result["localZeroSkips"], 2)

    def test_changed_placement_or_size_reassesses_zero(self):
        for box in ([.3, .9, .39, .96], [.03, .82, .21, .94]):
            with self.subTest(box=box), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                doc = fixture(folder)
                doc["pages"][2]["imageRegions"][0]["bbox"] = box
                provider = FakeProvider("logo")
                result = analyze_images(folder, doc, provider)
                self.assertEqual(len(provider.calls), 2)
                self.assertEqual(result["localZeroSkips"], 1)

    def test_fixed_geometry_different_pixels_or_unknown_do_not_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder)
            original = render_region
            def changed(folder, item):
                return {**original(folder, item), "visualFingerprint": str(item["page"])}
            provider = FakeProvider("logo")
            with patch("pdf_visual.render_region", side_effect=changed):
                result = analyze_images(folder, doc, provider)
            self.assertEqual(provider.images, [True, True, True])
            self.assertEqual(result["localZeroSkips"], 0)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder)
            provider = FakeProvider("uncertain")
            result = analyze_images(folder, doc, provider)
            self.assertEqual(len(provider.calls), 3)
            self.assertEqual(result["localZeroSkips"], 0)

    def test_known_learning_use_blocks_zero_shortcut_for_group(self):
        from pdf_visual import cache_path
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder)
            analyze_images(folder, doc, FakeProvider())
            for item in candidates(doc)[1:]:
                cache_path(folder, item).unlink()
            provider = FakeProvider("logo")
            result = analyze_images(folder, doc, provider)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(result["localZeroSkips"], 0)

    def test_repeated_educational_image_keeps_context_and_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder)
            provider = FakeProvider()
            result = analyze_images(folder, doc, provider)
            self.assertEqual(len(provider.calls), 3)
            self.assertEqual(provider.images, [True, False, False])
            self.assertNotIn("roleReason", provider.calls[1]["storedObservation"])
            self.assertEqual([x["page"] for x in result["explanations"]], [1, 2, 3])
            self.assertEqual([x["page"] for x in load_visual_notes(folder, doc, [1, 2, 3])], [1, 2, 3])
            self.assertEqual([x["relativePosition"] for x in provider.calls[2]["precedingAndCurrentContext"]], [-2, -1, 0])
            self.assertNotEqual(provider.calls[0]["precedingAndCurrentContext"], provider.calls[2]["precedingAndCurrentContext"])

    def test_selected_repeated_object_skips_only_uncovered_occurrences(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=3)
            items = candidates(doc)
            group = next(iter(fixed_repeat_groups(items).values()))
            inspection = [{"id": group, "occurrences": 3, "eligible": 2,
                           "eligibleRegionIds": [items[0]["regionId"], items[2]["regionId"]],
                           "protectedPages": [2], "signal": "translucent_monochrome_image"}]
            with patch("pdf_visual.inspect_repeat_objects", return_value=inspection):
                before = plan(folder, doc, PRICES["gpt-6-luna"])
                selected = plan(folder, doc, PRICES["gpt-6-luna"], [group])
                self.assertEqual((before["externalCandidateRegions"], selected["plannedLocalExclusions"],
                                  selected["externalCandidateRegions"]), (3, 2, 1))
                provider = FakeProvider()
                result = analyze_images(folder, doc, provider, [group])
            self.assertEqual(provider.images, [True])
            self.assertEqual(result["localZeroSkips"], 2)
            self.assertEqual([x["importance"] for x in result["assessments"]], [0, 2, 0])
            self.assertEqual([x["page"] for x in result["explanations"]], [2])
            # A later run reuses the paid response and every local decision.
            resumed = FakeProvider()
            analyze_images(folder, doc, resumed)
            self.assertEqual(resumed.calls, [])

    def test_isolated_translucent_object_with_vector_overlay_is_protected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            writer = PdfWriter()
            mask = DecodedStreamObject()
            mask.set_data(bytes([100]) * 400)
            mask.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                         NameObject("/Width"): NumberObject(20), NameObject("/Height"): NumberObject(20),
                         NameObject("/ColorSpace"): NameObject("/DeviceGray"), NameObject("/BitsPerComponent"): NumberObject(8)})
            mask_ref = writer._add_object(mask)
            graphic = DecodedStreamObject()
            graphic.set_data(bytes(20 * 20 * 3))
            graphic.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                            NameObject("/Width"): NumberObject(20), NameObject("/Height"): NumberObject(20),
                            NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8),
                            NameObject("/SMask"): mask_ref})
            graphic_ref = writer._add_object(graphic)
            for number in range(3):
                page = writer.add_blank_page(width=300, height=200)
                page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): graphic_ref})})
                contents = DecodedStreamObject()
                command = b"q 20 0 0 20 270 160 cm /Im1 Do Q"
                if number == 1:
                    command += b" 1 0 0 rg 273 163 5 5 re f"
                contents.set_data(command)
                page[NameObject("/Contents")] = writer._add_object(contents)
            writer.write(folder / "source.pdf")
            import pdfplumber
            with pdfplumber.open(folder / "source.pdf") as pdf:
                pages = [{"markdown": "", "ocrBlocks": [], "imageRegions": image_regions(page)} for page in pdf.pages]
            doc = {"documentId": "overlay", "fingerprint": "v1", "pages": pages, "chunks": []}
            items = candidates(doc)
            groups = inspect_repeat_objects(folder, doc, items)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["eligible"], 2)
            self.assertEqual(groups[0]["protectedPages"], [2])

    def test_repeated_object_is_not_excluded_without_document_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=2)
            provider = FakeProvider()
            result = analyze_images(folder, doc, provider)
            self.assertEqual(result["importanceCounts"]["2"], 2)
            self.assertEqual(provider.images, [True, False])

    def test_repeated_central_logo_is_not_blanket_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, [[.2, .2, .8, .8]])
            provider = FakeProvider("logo")
            analyze_images(folder, doc, provider)
            self.assertEqual(len(provider.calls), 3)

    def test_budget_stop_resumes_without_rebilling_completed_images(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder)
            first = analyze_images(folder, doc, FakeProvider(fail_at=1))
            self.assertEqual(first["pending"], 2)
            self.assertIn("비용 한도", first["stopReason"])
            self.assertEqual(len(load_visual_notes(folder, doc, [1])), 1)
            second = FakeProvider()
            resumed = analyze_images(folder, doc, second)
            self.assertEqual((len(second.calls), resumed["pending"]), (2, 0))
            doc["fingerprint"] = "new-extraction"
            self.assertEqual(plan(folder, doc, PRICES[second.model])["pending"], 3)

    def test_raster_crop_uses_selected_top_region_not_full_slide(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, [[.1, .1, .6, .4]])
            value = render_region(folder, candidates(doc)[0])
            image = Image.open(io.BytesIO(base64.b64decode(value["data"].split(",", 1)[1])))
            self.assertAlmostEqual(image.width / image.height, 2.5, places=1)
            red, green, blue = image.getpixel((image.width//2, image.height//2))
            self.assertGreater(red, 240)
            self.assertLess(blue, 20)
            image.close()

    def test_subpoint_image_fragments_render_and_do_not_block_later_regions(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, [[.1, .1, .6, .4], [.5, .5, .501, .501], [.2, .2, .7, .6]], count=1)
            doc["pages"][0].update(width=300, height=200)
            self.assertEqual(len(candidates(doc)), 3)
            tiny = render_region(folder, candidates(doc)[1])
            self.assertGreaterEqual(tiny["width"], 40)
            self.assertGreaterEqual(tiny["height"], 40)
            provider = FakeProvider()
            result = analyze_images(folder, doc, provider)
            self.assertEqual((result["completed"], result["total"], result["pending"]), (3, 3, 0))
            self.assertEqual(len(provider.calls), 3)

    def test_invalid_or_uncertain_response_cannot_hide_learning_content(self):
        for value in ({**reply(), "importance": True},
                      {**reply("uncertain"), "importance": 0},
                      {**reply(), "explanationMarkdown": ""}):
            with self.assertRaises(ValueError):
                validate(value)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=1)
            class Broken(FakeProvider):
                def complete(self, *args, **kwargs):
                    return {"role": "logo"}
            result = analyze_images(folder, doc, Broken())
            self.assertEqual(result["pending"], 1)
            self.assertEqual(load_visual_notes(folder, doc, [1]), [])

    def test_image_stream_hash_distinguishes_transparency_masks(self):
        class Stream:
            def __init__(self, mask):
                self.attrs = {"Width": 10, "Height": 10, "SMask": mask}
            def get_data(self):
                return b"same-pixels"
        class Page:
            width, height = 300, 200
            images = [{"x0": 1, "top": 1, "x1": 10, "bottom": 10, "stream": Stream("mask-one")},
                      {"x0": 50, "top": 1, "x1": 59, "bottom": 10, "stream": Stream("mask-two")}]
        images = image_regions(Page())
        self.assertEqual(len(images), 2)
        self.assertNotEqual(images[0]["imageHash"], images[1]["imageHash"])

    def test_zero_importance_mascot_can_become_teaching_subject(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=2)
            doc["pages"][1]["imageRegions"][0]["bbox"] = [.3, .9, .39, .96]
            class Changing(FakeProvider):
                def complete(self, *args, **kwargs):
                    super().complete(*args, **kwargs)
                    value = reply("mascot", 0 if len(self.calls) == 1 else 2)
                    value["roleReason"] = "장식" if len(self.calls) == 1 else "이번 페이지에서는 디자인의 특징을 비교합니다."
                    return value
            provider = Changing()
            result = analyze_images(folder, doc, provider)
            self.assertEqual(provider.images, [True, False])
            self.assertEqual([x["importance"] for x in result["assessments"]], [0, 2])
            notes = load_visual_notes(folder, doc, [1, 2])
            self.assertEqual([x["page"] for x in notes], [2])
            self.assertEqual(notes[0]["importance"], 2)
            self.assertEqual(notes[0]["purposes"], ["concept_explanation"])

    def test_contextual_fields_cannot_enter_reusable_observation_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=2)
            class ExtraFields(FakeProvider):
                def complete(self, *args, **kwargs):
                    value = super().complete(*args, **kwargs)
                    value["observation"].update(importance=0, roleReason="이전 페이지에서 장식으로 쓰임", purposes=["decoration"])
                    return value
            provider = ExtraFields()
            analyze_images(folder, doc, provider)
            self.assertEqual(set(provider.calls[1]["storedObservation"]), {"description", "visibleRelationships", "uncertainDetails"})

    def test_missing_detail_triggers_one_image_reread_and_budget_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=2)
            class Recheck(FakeProvider):
                def complete(self, *args, **kwargs):
                    super().complete(*args, **kwargs)
                    return reply("uncertain", review=True) if kwargs["image"] is None else reply()
            provider = Recheck()
            result = analyze_images(folder, doc, provider)
            self.assertEqual(provider.images, [True, False, True])
            self.assertEqual(result["imageRechecks"], 1)
            self.assertEqual(result["pending"], 0)
            self.assertIn("missingVisualDetail", provider.calls[-1])
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=2)
            failed = Recheck(fail_at=2)
            result = analyze_images(folder, doc, failed)
            self.assertEqual(result["pending"], 1)
            resumed = Recheck()
            result = analyze_images(folder, doc, resumed)
            self.assertEqual(resumed.images, [False, True])
            self.assertEqual(result["pending"], 0)

    def test_unresolved_image_is_not_zero_and_does_not_loop_or_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=1)
            class Unresolved(FakeProvider):
                def complete(self, *args, **kwargs):
                    super().complete(*args, **kwargs)
                    return reply("uncertain", review=True)
            provider = Unresolved()
            result = analyze_images(folder, doc, provider)
            self.assertEqual(provider.images, [True])
            self.assertEqual(result["importanceCounts"]["undetermined"], 1)
            self.assertEqual(result["skipped"], 0)
            self.assertEqual(result["explanations"], [])
            self.assertEqual(load_visual_notes(folder, doc, [1]), [])
            self.assertEqual(plan(folder, doc, PRICES[provider.model])["pending"], 0)

    def test_same_stream_with_different_visible_crop_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, [[.1, .1, .4, .3], [.1, .7, .4, .9]], count=1)
            provider = FakeProvider()
            analyze_images(folder, doc, provider)
            self.assertEqual(provider.images, [True, True])

    def test_distinct_rasters_at_same_coordinates_remain_separate(self):
        class Stream:
            attrs = {}
            def __init__(self, data): self.data = data
            def get_data(self): return self.data
        first, second = Stream(b"first-image"), Stream(b"second-image")
        class Page:
            width = height = 100
            images = [{"x0": 1, "top": 1, "x1": 20, "bottom": 20, "stream": stream}
                      for stream in (first, second)]
        regions = image_regions(Page())
        self.assertEqual(len(regions), 2)
        self.assertNotEqual(regions[0]["imageHash"], regions[1]["imageHash"])

    def test_plan_reserves_for_text_assessment_plus_optional_image_review(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=2)
            value = plan(folder, doc, PRICES["gpt-6-luna"])
            self.assertEqual(value["requestUpperBound"], 4)
            self.assertGreater(value["costUpperEstimateUsd"], .01)

    def test_provider_reserves_and_records_mock_vision_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = fixture(folder, count=1)
            def transport(body):
                self.assertEqual(body["messages"][1]["content"][1]["type"], "image_url")
                return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(reply())}}],
                        "usage": {"prompt_tokens": 1100, "completion_tokens": 300}}
            provider = Provider(folder, True, .02, "gpt-6-luna", transport=transport)
            result = analyze_images(folder, doc, provider)
            self.assertEqual(result["pending"], 0)
            self.assertAlmostEqual(result["accountedUsd"], .00026)
            self.assertEqual(result["runUsage"]["imageRequests"], 1)
            self.assertEqual(result["runUsage"]["confirmedImageRequests"], 1)
            self.assertEqual(result["runUsage"]["imageRegions"], 1)
            self.assertEqual(result["runUsage"]["textOnlyRequests"], 0)
            self.assertAlmostEqual(result["runUsage"]["usageBasedUsd"], .00026)
            self.assertEqual(result["runUsage"]["unknownUsageRequests"], 0)
            self.assertEqual(provider.ledger["requests"][0]["kind"], "image_role")
            self.assertLess(provider.ledger["requests"][0]["inputTokenBound"], 32000)

    def test_empty_document_and_large_context_remain_local_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            doc = {"documentId": "empty", "fingerprint": "v1", "pages": [{"imageRegions": []}], "chunks": []}
            self.assertEqual(plan(folder, doc, PRICES["gpt-6-luna"])["costUpperEstimateUsd"], 0)
            provider = FakeProvider()
            self.assertEqual(analyze_images(folder, doc, provider)["total"], 0)
            self.assertEqual(provider.calls, [])
            doc["pages"] = [{"markdown": "가" * 50000, "ocrBlocks": [{"text": "나" * 50000}]}] * 150
            self.assertLess(len(json.dumps(context(doc, 150), ensure_ascii=False).encode()), 9000)


if __name__ == "__main__":
    unittest.main()
