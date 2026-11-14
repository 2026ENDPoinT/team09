from __future__ import annotations

import unittest
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfWriter

from seoultech_lms.campus_file_text import extract_file_text


def office_archive(parts: dict[str, str]) -> bytes:
    result = BytesIO()
    with ZipFile(result, "w", compression=ZIP_DEFLATED) as archive:
        for name, xml in parts.items():
            archive.writestr(name, xml)
    return result.getvalue()


class CampusFileTextTests(unittest.TestCase):
    def test_text_chunks_continue_without_losing_content(self):
        content = ("교내 안내\n" * 5_000).encode("cp949")
        first = extract_file_text("안내.TXT", content)
        following = extract_file_text("안내.TXT", content, start_page=first["next_page"])
        self.assertEqual(first["unit"], "chunk")
        self.assertEqual("".join(first["pages"] + following["pages"]), content.decode("cp949"))
        self.assertIsNone(following["next_page"])

    def test_pdf_preserves_page_number_and_empty_page(self):
        content = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(100, 100)
        writer.add_blank_page(100, 100)
        writer.write(content)
        result = extract_file_text("첨부.pdf", content.getvalue(), start_page=2)
        self.assertEqual((result["unit"], result["total_pages"], result["pages"]), ("page", 2, [""]))
        self.assertIsNone(result["next_page"])

    def test_docx_reads_body_paragraphs_and_table_cells(self):
        content = office_archive({
            "word/document.xml": (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>학교</w:t><w:tab/><w:t>공지</w:t></w:r></w:p>"
                "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>표 내용</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
                "</w:body></w:document>"
            ),
            "word/comments.xml": "<comment>본문에 섞이지 않을 메모</comment>",
        })
        self.assertEqual(extract_file_text("첨부.docx", content)["pages"], ["학교\t공지\n표 내용"])

    def test_hwpx_reads_sections_in_numeric_order(self):
        namespace = "http://www.hancom.co.kr/hwpml/2011/paragraph"
        content = office_archive({
            "Contents/section10.xml": f'<body xmlns:hp="{namespace}"><hp:p><hp:t>두 번째</hp:t></hp:p></body>',
            "Contents/section2.xml": (
                f'<body xmlns:hp="{namespace}"><hp:p><hp:t>첫<hp:lineBreak/>번째</hp:t></hp:p></body>'
            ),
        })
        self.assertEqual(extract_file_text("첨부.hwpx", content)["pages"], ["첫\n번째\n두 번째"])

    def test_office_dtd_and_oversized_document_members_are_rejected(self):
        dtd = office_archive({"word/document.xml": '<!DOCTYPE doc [<!ENTITY secret "abc">]><doc>&secret;</doc>'})
        with self.assertRaisesRegex(ValueError, "DTD"):
            extract_file_text("첨부.docx", dtd)
        oversized = office_archive({"word/document.xml": " " * (8 * 1024 * 1024 + 1)})
        with self.assertRaisesRegex(ValueError, "8 MiB"):
            extract_file_text("첨부.docx", oversized)

    def test_binary_hwp_reports_unavailable_text(self):
        result = extract_file_text("첨부.hwp", b"\x00binary HWP sample")
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["format"], "hwp")
        self.assertEqual(result["pages"], [])
