import assert from "node:assert/strict";
import test from "node:test";
import { answerClassQuestion, classQuestion } from "../dist-desktop/desktop/chat-class-guidance.js";

const friday = "2026-11-13";
const weekEnd = "2026-11-14";
const upcoming = { date: friday, course_name: "예시 강좌", start_time: "12:00", end_time: "13:00", room: "예시관 310호" };
const earlier = { date: friday, course_name: "앞 수업", start_time: "11:00", end_time: "11:45", room: "예시관 201호" };
const week = (entries, week_end = weekEnd) => ({ structuredContent: { entries, week_end } });
const seoulTime = (time, date = friday) => new Date(`${date}T${time}+09:00`);

function answer(intent, time, entries, date = friday) {
  return answerClassQuestion(intent, async () => week(entries), new AbortController().signal, seoulTime(time, date));
}

test("direct class questions use the timetable route while other requests stay in normal chat", () => {
  for (const question of ["나 지금 어느 수업 들으러 가야해?", "지금 강의실 어디야?", "수업 들으러 어디 가야 돼?", "지금 무슨 수업이야?"]) {
    assert.equal(classQuestion(question), "now", question);
  }
  assert.equal(classQuestion("다음 수업은 어디로 가야 해?"), "next");
  for (const question of ["지금 어디 가야 해?", "다음 수업 과제 알려줘", "수업 공지 알려줘", "다음 수업 뭐야? 그리고 식단도 알려줘"]) {
    assert.equal(classQuestion(question), undefined, question);
  }
});

test("the room comes first up to and including exactly two hours", async () => {
  const normal = await answer("now", "11:36:00", [upcoming]);
  assert.match(normal, /^\*\*예시관 310호\*\*로 가면 돼요\. 24분 뒤인 12시에/);
  const exactlyTwoHours = await answer("now", "10:00:00", [upcoming]);
  assert.match(exactlyTwoHours, /^\*\*예시관 310호\*\*로 가면 돼요\. 2시간 뒤인/);
  const beyondTwoHours = await answer("now", "09:59:59", [upcoming]);
  assert.match(beyondTwoHours, /^지금 진행 중인 수업은 없어요\./);
  assert.doesNotMatch(beyondTwoHours, /가면 돼요/);
});

test("a current class has priority, and its end time is exclusive", async () => {
  const current = await answer("now", "11:36:00", [upcoming, earlier]);
  assert.match(current, /지금은 \*\*앞 수업\*\* 수업 시간이에요/);
  const next = await answer("next", "11:36:00", [earlier, upcoming]);
  assert.match(next, /^\*\*예시관 310호\*\*로 가면 돼요/);
  const afterEnd = await answer("now", "11:45:00", [upcoming, earlier]);
  assert.match(afterEnd, /15분 뒤인 12시에/);
});

test("the time is still available when the room cannot be confirmed", async () => {
  const text = await answer("now", "11:36:00", [{ ...upcoming, room: null }]);
  assert.match(text, /^24분 뒤인 12시에 .*시작해요\. 시간표에서 강의실은 확인되지 않아요\./);
});

test("an imminent class can be found after the Seoul week boundary", async () => {
  const dates = [];
  const nextSunday = "2026-11-15";
  const text = await answerClassQuestion("now", async (date) => {
    dates.push(date);
    return date === weekEnd ? week([]) : week([
      { ...upcoming, date: nextSunday, start_time: "00:15", end_time: "01:00" },
    ], "2026-11-21");
  }, new AbortController().signal, seoulTime("23:45:00", weekEnd));
  assert.deepEqual(dates, [weekEnd, nextSunday]);
  assert.match(text, /30분 뒤인 11월 15일 0시 15분에/);
});

test("login and read failures are shown without guessing a class", async () => {
  const signal = new AbortController().signal;
  const now = seoulTime("11:36:00");
  const login = await answerClassQuestion("now", async () => ({ status: "login_required" }), signal, now);
  assert.match(login, /내 강의실에서 로그인 확인/);
  const failed = await answerClassQuestion("now", async () => { throw new Error("connection"); }, signal, now);
  assert.match(failed, /시간표를 확인하지 못했어요/);
});
