import assert from "node:assert/strict";
import test from "node:test";
import { campusNoticeApplication } from "../dist-desktop/shared/campus-notice-application.js";

test("application fields preserve the original application period and eligible group", () => {
  assert.deepEqual(campusNoticeApplication([
    "1. 신청기간 : 2026. 11. 16.(월) ~ 2026. 11. 27.(금) 18:00",
    "2. 지원 대상 : 서울과학기술대학교 재학생 및 휴학생",
    "3. 결과 발표 : 2026. 12. 1.",
  ].join("\n")), {
    deadline: "2026. 11. 16.(월) ~ 2026. 11. 27.(금) 18:00",
    audience: "서울과학기술대학교 재학생 및 휴학생",
  });
  assert.deepEqual(campusNoticeApplication([
    "■ 신청 마감",
    "2026년 11월 27일 오후 6시까지",
    "■ 모집 대상: 1~3학년 재학생 모집 인원: 30명",
  ].join("\n")), {
    deadline: "2026년 11월 27일 오후 6시까지",
    audience: "1~3학년 재학생",
  });
});

test("selection, event and publication dates do not become application deadlines", () => {
  assert.deepEqual(campusNoticeApplication([
    "게시일: 2026. 11. 10.",
    "운영 기간: 11. 20. ~ 11. 30.",
    "면접 일시: 11월 24일",
    "신청 일시: 11. 13. 10:00",
    "선발 결과 발표: 11. 25.",
    "신청 기간: 11. 20. ~",
    "지원 대상: 붙임 파일 확인",
  ].join("\n")), {});
  assert.deepEqual(campusNoticeApplication("신청 마감: 결과 발표 11월 26일\n지원 대상: 11월 26일 발표"), {});
  assert.deepEqual(campusNoticeApplication("신청 마감:\n합격자 발표: 11월 26일"), {});
  assert.deepEqual(campusNoticeApplication("신청 마감: 11.20. 또는 11.27.\n지원 대상: 지원자"), {});
});

test("a deadline or audience can appear independently and conflicting values are omitted", () => {
  assert.deepEqual(campusNoticeApplication("접수 마감: 11.27.(금) 18:00까지"), { deadline: "11.27.(금) 18:00까지" });
  assert.deepEqual(campusNoticeApplication("참가 자격: 전국 대학 재학생"), { audience: "전국 대학 재학생" });
  assert.deepEqual(campusNoticeApplication("모집 기간: 정원 충원 시까지"), { deadline: "정원 충원 시까지" });
  assert.deepEqual(campusNoticeApplication("신청 마감: 11.20.\n신청 마감: 11.27.\n지원 대상: 재학생"), { audience: "재학생" });
});
