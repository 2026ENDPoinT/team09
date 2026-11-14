from __future__ import annotations

import unittest
import asyncio

from seoultech_lms.client import ReadOnlyViolation, SeoultechLMSClient
from seoultech_lms.models import AssignmentMetadata, CourseMeeting
from seoultech_lms.parser import enrich_assignment, enrich_notice, parse_assignment_index, parse_courses, parse_notices


class ParserTests(unittest.TestCase):
    def test_write_endpoint_is_blocked_before_network_access(self) -> None:
        client = SeoultechLMSClient()
        with self.assertRaises(ReadOnlyViolation):
            asyncio.run(client._request("POST", "/ilos/cls/st/report/report_submit.acl"))

    def test_courses_use_native_kjkey(self) -> None:
        html = """<a id='kj_1' title='테스트과목 강의실 들어가기'
        onclick=\"eclassRoom('A2026312345631001'); return false;\">
        테스트과목 123456-31001 홍길동 월(1 ~ 2) 3학점</a>"""
        course = parse_courses(html)[0]
        self.assertEqual(course.id, "A2026312345631001")
        self.assertEqual(course.course_code, "123456-31001")
        self.assertEqual(course.professor, "홍길동")
        self.assertEqual(course.schedule_text, "월(1 ~ 2)")
        self.assertEqual(course.meetings, (CourseMeeting("월", "1 ~ 2"),))

    def test_course_schedule_preserves_card_period_labels(self) -> None:
        html = """
        <a id="kj_1" title="예시 과목 강의실 들어가기" onclick="eclassRoom('A20260001')">
          <div class="card_top">예시 과목 토(1)</div>
          <div class="card_bottom"><div class="divide_bottom"><div class="info_txt">
            <span>월(7A ~ 9B)</span><span>화(1, 3)</span><span>목(5B)</span><span>3학점</span>
          </div></div></div>
        </a>
        """
        course = parse_courses(html)[0]
        self.assertEqual(course.schedule_text, "월(7A ~ 9B), 화(1, 3), 목(5B)")
        self.assertEqual(course.meetings, (
            CourseMeeting("월", "7A ~ 9B"), CourseMeeting("화", "1, 3"), CourseMeeting("목", "5B"),
        ))

    def test_course_without_displayed_meetings_has_no_schedule(self) -> None:
        html = """
        <section class="my_lecture_container">
          <div class="term_wrap">
            <p class="container_subtitle">2학기</p>
            <a id="kj_1" onclick="eclassRoom('A20260001')">
              <div class="card_bottom"><div class="info_txt"><span>3학점</span></div></div>
            </a>
          </div>
          <div class="term_wrap">
            <p class="container_subtitle">비정규과목</p>
            <a id="kj_2" onclick="eclassRoom('비20260002')">
              <div class="card_bottom"><div class="info_txt"><span>온라인</span></div></div>
            </a>
          </div>
        </section>
        """
        courses = parse_courses(html)
        self.assertEqual(len(courses), 2)
        for course in courses:
            self.assertIsNone(course.schedule_text)
            self.assertIsNone(course.course_code)
            self.assertEqual(course.meetings, ())

    def test_notices_keep_native_article_id(self) -> None:
        html = """<button class='board_list_wrap' data-num='8769498'>
        <div class='board_list'><div class='board_title'>휴강 공지</div>
        <div class='board_text'>다음 수업 안내</div></div>
        <div class='board_list_bottom'>조회 3 9월 12일 오후 1:00</div></button>"""
        notice = parse_notices(html, "A2026312345631001")[0]
        self.assertEqual(notice.id, "8769498")
        self.assertEqual(notice.title, "휴강 공지")
        self.assertEqual(notice.created_at.isoformat(), "2026-09-12T13:00:00")

    def test_notice_date_without_verified_course_year_stays_unknown(self) -> None:
        html = """<button class='board_list_wrap' data-num='42'>
        <div class='board_title'>공지</div>
        <div class='board_list_bottom'><div class='reg_info'>9월 12일 오후 1:00</div></div>
        </button>"""
        notice = parse_notices(html, "course-without-year")[0]
        self.assertIsNone(notice.created_at)

    def test_assignment_detail_has_exact_due_time(self) -> None:
        index = """<a id='class_menu_report_8762976' class='activity not_submit'>
        <div class='activity_title'>토론 과제 제출 시스템</div></a>"""
        item = parse_assignment_index(index, "course-1")[0]
        detail = """<div class='view_title'><span class='font_headline2'>토론 과제 제출 시스템</span></div>
        <table>
          <tr><th>마감일</th><td>2026.11.05 (목) 오후 11:59</td></tr>
          <tr><th>지각 제출</th><td>허용 ( 마감일 : 2026.11.09 (월) 오후 9:30 )</td></tr>
        </table>
        <div id='submit_form'>제출정보 <span>제출된 내역이 없습니다.</span></div>"""
        enriched = enrich_assignment(detail, item)
        self.assertEqual(enriched.due_at.isoformat(), "2026-11-05T23:59:00")
        self.assertEqual(enriched.late_due_at.isoformat(), "2026-11-09T21:30:00")
        self.assertFalse(enriched.submitted)

    def test_assignment_instructions_exclude_student_submission(self) -> None:
        item = parse_assignment_index('<a id="class_menu_report_1">과제 1</a>', "course-1")[0]
        detail = """
        <div id="submit_form">
            <table><tr><th>마감일</th><td>2026.11.09 (월) 오후 9:30</td></tr>
                <tr><th>지각제출</th><td>허용 (마감일: 2026.11.09 (월) 오후 9:30)</td></tr>
                <tr><th>배점</th><td>100점</td></tr></table>
            <table class="bbsview"><tr><td><div class="editor_content">학생 제출물</div></td></tr></table>
        </div>
        <table class="bbsview"><tr><td>
            <div class="editor_content"><p>교수자 안내</p><p>두 번째 문단</p>
                <table><tr><th>마감일</th><td>2026.11.08 (일) 오후 9:30</td></tr></table>
            </div>
        </td></tr></table>
        <table>
            <tr><th>제출 방식</th><td>온라인</td></tr>
            <tr><th>제출형태</th><td>글 입력 / 파일첨부</td></tr>
            <tr><th>공개일</th><td>2026.11.01 (일) 오전 10:16</td></tr>
            <tr><th>마감일</th><td>2026.11.05 (목) 오후 11:59 <span>D-1</span></td></tr>
            <tr><th>지각제출</th><td>불허</td></tr>
            <tr><th>배점</th><td>0점</td></tr>
            <tr><th>점수공개</th><td>비공개</td></tr>
        </table>
        """
        enriched = enrich_assignment(detail, item)
        self.assertTrue(enriched.description.startswith("교수자 안내\n두 번째 문단"))
        self.assertNotIn("학생 제출물", enriched.description)
        self.assertEqual(enriched.due_at.isoformat(), "2026-11-05T23:59:00")
        self.assertIsNone(enriched.late_due_at)
        self.assertEqual(enriched.metadata, AssignmentMetadata(
            submission_method="온라인", submission_format="글 입력 / 파일첨부", published_at="2026-11-01T10:16:00+09:00",
            points="0점", score_visibility="비공개",
        ))

    def test_notice_detail_replaces_preview_without_comments(self) -> None:
        preview = parse_notices(
            """<button class='board_list_wrap' data-num='42'>
            <div class='board_title'>중간고사 안내</div><div class='board_text'>미리보기</div></button>""",
            "course-1",
        )[0]
        detail = """
        <div class='view_title'><span class='font_headline2'>중간고사 일정 안내</span></div>
        <div class='editor_content'>시험은 10월 20일 오후 2시에 진행합니다.</div>
        <div class='comment_zone'>댓글 내용은 본문이 아니다.</div>
        """
        notice = enrich_notice(detail, preview)
        self.assertEqual(notice.title, "중간고사 일정 안내")
        self.assertEqual(notice.content, "시험은 10월 20일 오후 2시에 진행합니다.")
        self.assertNotIn("댓글", notice.content or "")


if __name__ == "__main__":
    unittest.main()
