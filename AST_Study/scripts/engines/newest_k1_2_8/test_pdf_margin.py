import copy
import json
import unittest

from pdf_margin import margin_policy, clean_text, clean_chunk
from pdf_ai import model_sources, selected_generation_sources, split_unit
from pdf_study_policy import document_context, neighboring_context
from pdf_visual import context


def fixture():
    pages, chunks = [], []
    footer = "Teacher (teacher@example.edu)"
    for number in range(1, 4):
        text = f"{number}쪽 학습 본문입니다.\n" + footer
        pages.append({"markdown": text, "nativeText": text, "words": [
            {"text": "Teacher", "bbox": [.3, .94, .4, .96]},
            {"text": "(teacher@example.edu)", "bbox": [.41, .94, .7, .96]}]})
        chunks.append({"id": f"p{number}", "page": number, "source": "native", "field": "markdown",
                       "start": 0, "end": len(text), "text": text, "documentId": "doc"})
    return {"documentId": "doc", "fingerprint": "fp", "pages": pages, "chunks": chunks}


class MarginTests(unittest.TestCase):
    def test_model_and_context_copies_cleaned_originals_and_offsets_preserved(self):
        doc = fixture()
        before = copy.deepcopy(doc)
        self.assertEqual(len(margin_policy(doc)), 3)
        _, chunks, _ = selected_generation_sources(None, doc, "document", 1)
        for payload in (model_sources(chunks), model_sources(doc["chunks"], doc),
                        document_context(doc), neighboring_context(doc, [doc["chunks"][1]]), context(doc, 2)):
            self.assertNotIn("teacher@example.edu", json.dumps(payload))
        self.assertEqual(doc, before)
        for original, filtered in zip(doc["chunks"], chunks):
            self.assertEqual(original["text"], filtered["text"])
            self.assertEqual(doc["pages"][filtered["page"]-1]["markdown"][filtered["start"]:filtered["end"]], filtered["text"])

    def test_body_contact_example_preserved_footer_removed(self):
        doc = fixture()
        text = "Teacher (teacher@example.edu)\n이메일 형식을 설명하는 본문입니다.\nTeacher (teacher@example.edu)"
        doc["pages"][0]["markdown"] = text
        cleaned = clean_text(text, margin_policy(doc)[1])
        self.assertEqual(cleaned.count("teacher@example.edu"), 1)
        self.assertTrue(cleaned.startswith("Teacher"))

    def test_general_repeated_content_not_filtered(self):
        for token, box in (("E=mc^2", [.3, .94, .6, .96]),
                           ("반복되는 수업 제목", [.3, .02, .6, .04]),
                           ("teacher@example.edu", [.3, .4, .6, .42])):
            doc = fixture()
            for page in doc["pages"]:
                page["words"] = [{"text": token, "bbox": box}]
            self.assertEqual(margin_policy(doc), {})

    def test_missing_coordinates_or_insufficient_repetition_keeps_text(self):
        doc = fixture()
        for page in doc["pages"][1:]:
            page["words"] = []
        self.assertEqual(margin_policy(doc), {})
        self.assertEqual(model_sources(doc["chunks"], doc)[0]["text"], doc["chunks"][0]["text"])

    def test_table_separators_and_changing_page_numbers(self):
        doc = fixture()
        for number, page in enumerate(doc["pages"], 1):
            page["words"].append({"text": str(number), "bbox": [.95, .94, .98, .96]})
            page["markdown"] = f"본문\n| Teacher | (teacher@example.edu) | {number} |"
        policy = margin_policy(doc)
        self.assertEqual(len(policy), 3)
        for number, page in enumerate(doc["pages"], 1):
            self.assertNotIn("teacher@example.edu", clean_text(page["markdown"], policy[number]))

    def test_partial_chunks_and_recursive_splits_do_not_restore_footer(self):
        doc = fixture()
        text = "학습 본문입니다. " * 100 + "\nTeacher (teacher@example.edu)"
        doc["pages"][0]["markdown"] = text
        chunk = {**doc["chunks"][0], "text": text, "start": 0, "end": len(text)}
        chunk["aiText"] = clean_chunk(chunk, doc, margin_policy(doc))
        self.assertEqual(len(chunk["aiText"]), len(text))
        left, right = split_unit([chunk])
        self.assertNotIn("teacher@example.edu", json.dumps(model_sources(left+right)))
        self.assertEqual(left[0]["text"]+right[0]["text"], text)
        start = text.index("example")
        partial = {**chunk, "start": start, "text": text[start:]}
        self.assertFalse(clean_chunk(partial, doc, margin_policy(doc)).strip())
        broken = {**partial, "start": 0}
        self.assertEqual(clean_chunk(broken, doc, margin_policy(doc)), broken["text"])


if __name__ == "__main__":
    unittest.main()
