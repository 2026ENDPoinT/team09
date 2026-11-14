import assert from "node:assert/strict";
import test from "node:test";
import { campusNoticeTags, classifyCampusNotice } from "../dist-desktop/shared/campus-notice-tags.js";

test("campus notice tags use the ten agreed labels", () => {
  assert.deepEqual(Object.values(campusNoticeTags), [
    "학사·수업", "장학·등록", "취업·진로", "비교과·교육", "공모전·대회",
    "국제교류·어학", "연구·대학원", "학생생활·복지", "행사·문화", "시설·전산",
  ]);
});

test("specific notice topics classify without generic recruitment or audience tags", () => {
  const examples = [
    ["학부 수강 신청 및 정정 안내", ["academic"]],
    ["연계융합전공 이수 신청 안내", ["academic"]],
    ["학내 시험 및 평가 관련 부정행위(AI활용 포함) 예방 및 주의사항 안내", ["academic"]],
    ["외국인·대학원생 장학금 신청 안내", ["scholarship"]],
    ["국가근로장학 장학생 선발", ["scholarship"]],
    ["복학생 등록 안내", ["scholarship"]],
    ["로스쿨 특강 참가자 모집", ["career"]],
    ["창업 지원 사업 참여자 모집", ["career"]],
    ["3D프린터 장비 교육 안내", ["learning"]],
    ["학교 소개 영상 공모전", ["competition"]],
    ["일본어 클리닉 참가 신청", ["international"]],
    ["로컬 메이트 참가자 추가 모집", ["international", "events"]],
    ["해외 인턴 참가자 모집", ["career", "international"]],
    ["대학원 학위논문 심사 일정", ["research"]],
    ["[전체대학원] 2026학년도 2학기 논문제출연기신청서 제출 안내", ["research"]],
    ["학위청구논문 심사 세부일정 및 작성 요령 안내", ["research"]],
    ["기숙사 입사 신청 안내", ["studentLife"]],
    ["학생상담센터 마음나눔 카페 참여자 모집", ["studentLife"]],
    ["학생 예비군 훈련 일정 안내", ["studentLife"]],
    ["개교 기념 음악회", ["events"]],
    ["Ｃｈｒｏｍｅ／ＰＨＰ 취약점 안내", ["systems"]],
    ["신청 및 지원 안내", []],
    ["재학생 참가자 추가 모집 공고", []],
  ];

  for (const [title, expected] of examples) {
    assert.deepEqual(classifyCampusNotice(title, ""), expected, title);
  }
});

test("body topics can resolve broad titles or add one directly related category", () => {
  assert.deepEqual(classifyCampusNotice("참가자 추가 모집", "사업명: 해외 연수\n대상: 장학생"), ["international"]);
  assert.deepEqual(classifyCampusNotice("모집 안내", "문의: 취업진로센터\n학교 소개 영상 공모전을 엽니다."), ["competition"]);
  assert.deepEqual(classifyCampusNotice("영상 공모전 안내", "○ 프로그램명: 일본어 회화 워크숍\n문의: 정보 보안팀"), ["competition", "international"]);
  assert.deepEqual(classifyCampusNotice("일본어 클리닉 신청 안내", "지원 대상: 장학생\n선발은 취업 여부와 무관합니다."), ["international"]);
  assert.deepEqual(classifyCampusNotice("교환학생 모집 안내", "해외 현장실습과 함께 진행하는 프로그램입니다.\n참가 대상은 장학생입니다."), ["international", "career"]);
});

test("strong title matches win over body cues and the result has at most two tags", () => {
  assert.deepEqual(classifyCampusNotice("로컬 메이트 참가자 추가 모집", "행사명: 영상 공모전"), ["international", "events"]);
  assert.deepEqual(classifyCampusNotice("로컬 메이트 영상 공모전 참가 신청", "프로그램명: 대학원 연구 세미나"), ["competition", "international"]);
});
