// Run after npm run build: electron tests/screen-refresh-ipc.smoke.mjs --headless
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, ipcMain, session } from "electron";
import { shiftTimetableDate, timetableWeekStart } from "../dist-desktop/shared/timetable-week.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const profile = mkdtempSync(join(tmpdir(), "ast-refresh-ipc-"));
app.setPath("userData", profile);
app.disableHardwareAcceleration();
const today = new Intl.DateTimeFormat("sv-SE", { dateStyle: "short", timeZone: "Asia/Seoul" }).format(new Date());
const monday = timetableWeekStart(today);
const date = shiftTimetableDate(monday, 3);
const week = { week_start: shiftTimetableDate(monday, -1), week_end: shiftTimetableDate(monday, 5), on_date: date };
const timetableWeek = { ...week, week_start: monday, week_end: shiftTimetableDate(monday, 6) };
const asOf = date + "T12:00:00+09:00";
const notice = (title) => ({
  board: "notice", board_id: "1", id: "1", title, published_at: date, department: null,
  pinned: false, has_attachments: false, url: "https://www.seoultech.ac.kr/service/info/notice?do=commonview&bnum=1&bidx=1",
});
const screenCases = [
  {
    label: "시간표 및 캘린더", channel: "course-timetable", forceIndex: 1,
    value: (name) => ({ ...timetableWeek, timezone: "Asia/Seoul", entries: [
      { course_id: "fixture", course_name: name, professor: "예시 교수", date, weekday: "목요일", start_time: "10:30", end_time: "12:00", room: "검증 강의실", room_source: "syllabus" },
      { course_id: "overlap", course_name: "겹치는 수업", date, weekday: "목요일", start_time: "11:00", end_time: "12:00", room: null },
      { course_id: "sunday", course_name: "일요일 수업", date: timetableWeek.week_end, weekday: "일요일", start_time: "19:15", end_time: "20:00", room: "검증 강의실" },
    ] }),
  },
  {
    label: "기숙사 식단", channel: "dorm-menu", forceIndex: 2,
    value: (name) => ({ ...week, dorm: "kb", dorm_name: "KB학사", period: "week", days: [
      { date, weekday: "목요일", meals: { breakfast: name, lunch: null, dinner: null }, notes: [] },
    ] }),
  },
  {
    label: "대학생활 공지", channel: "list-campus-notices", forceIndex: 2,
    value: (name) => ({ board: "notice", notices: [notice(name)], next_page: null }),
  },
  {
    label: "오늘의 캠퍼스", channel: "course-briefing", forceIndex: 0,
    value: (name) => ({ as_of: asOf, pending_assignments: [
      { id: "1", course_id: "fixture", course_name: "검증 강의", title: name + " 과제", due_at: date + "T23:59:00+09:00", submitted: false },
    ], completed_assignments: [], recent_notices: [] }),
  },
];
const pending = new Map();
const data = new Map();
let noticeRevision = 1;
const calendarBriefing = screenCases.find(({ channel }) => channel === "course-briefing").value("캘린더 마감");
const openedAssignments = [];
let currentScreen;
let window;
const run = (code) => window.webContents.executeJavaScript(code);
const waitFor = async (check, message) => {
  for (let i = 0; i < 100; i++) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 35));
  }
  assert.fail(message);
};
const activeText = () => run("document.querySelector('.ast-main main > div:not([hidden])')?.textContent ?? ''");
const open = (name) => {
  currentScreen = name;
  if (name === "오늘의 캠퍼스") return run("document.querySelector('.ast-wordmark').click()")
    .then(() => waitFor(() => run("!!document.querySelector('.sketch-deadlines .sketch-link')"), "home is visible"))
    .then(() => run("document.querySelector('.sketch-deadlines .sketch-link').click()"));
  return run(`[...document.querySelectorAll('.app-nav button')].find(b=>b.textContent.replace('↗', '').trim()===${JSON.stringify(name)}).click()`);
};
const refresh = () => run("[...document.querySelectorAll('.ast-main main > div:not([hidden]) button')].find(b=>b.textContent==='새로고침').click()");
const failed = { status: "error", message: "테스트 조회 오류" };

async function main() {
  try {
    await app.whenReady();
    app.dock?.hide();
    session.defaultSession.webRequest.onBeforeRequest({ urls: ["http://*/*", "https://*/*"] }, (_, callback) => callback({ cancel: true }));
    ipcMain.handle("ast:chat-config", () => ({ model: "fixture", usdKrw: 1400, hasApiKey: false }));
    ipcMain.handle("ast:chat-transcript", () => ({ turns: [], storageError: false }));
    ipcMain.handle("ast:prefetch-status", () => ({ state: "ready", completed: 14, total: 14, sessionRevision: 1 }));
    ipcMain.handle("ast:astra-login-status", () => ({ state: "authenticated", message: "검증 세션" }));
    ipcMain.handle("ast:home-snapshot", () => null);
    ipcMain.handle("ast:student-preferences", () => ({ residence: "none", departmentId: "computer" }));
    ipcMain.handle("ast:course-notice-settings", () => ({ includeNonRegular: false }));
    ipcMain.handle("ast:assignment-settings", () => ({ includeOverdue: true, overdueDays: 7 }));
    ipcMain.handle("ast:chat-composing", () => {});
    ipcMain.handle("ast:course-overview", () => ({ status: "ok", overview: { regular: 0, non_regular: 0, courses: [] } }));
    ipcMain.handle("ast:campus-briefing", () => ({ as_of: asOf, notices: [] }));
    ipcMain.handle("ast:sync-campus-notice-index", () => {});
    ipcMain.handle("ast:campus-notice-index", (_event, afterRevision) => afterRevision === noticeRevision ? null : ({
      revision: noticeRevision, notices: data.get("list-campus-notices").notices, entries: {}, listedBoards: ["notice"],
      pages: { notice: { lastPage: 1, nextPage: null, listedAt: Date.now() } }, loading: false, partial: false,
    }));
    ipcMain.handle("ast:assignment-open", (_event, target) => { openedAssignments.push(target); return true; });
    for (const { channel, forceIndex, value } of screenCases) {
      data.set(channel, value("기존 자료"));
      ipcMain.handle("ast:" + channel, (_event, ...args) => {
        if (channel === "course-briefing" && currentScreen === "시간표 및 캘린더") return calendarBriefing;
        return args[forceIndex] ? new Promise((resolve) => pending.set(channel, resolve)) : data.get(channel);
      });
    }
    window = new BrowserWindow({ show: false, width: 900, webPreferences: {
      preload: join(root, "dist-desktop/desktop/preload.cjs"), contextIsolation: true, sandbox: true, nodeIntegration: false,
    } });
    await window.loadFile(join(root, "dist/index.html"));
    await waitFor(() => run("document.querySelector('.ast-entry-shell')?.dataset.entry === 'open'"), "app did not open");

    for (const { channel, label, value } of screenCases) {
      await open(label);
      await waitFor(async () => (await activeText()).includes("기존 자료"), label + " first data");
      if (channel === "list-campus-notices") {
        await run("[...document.querySelectorAll('[aria-label=\"공지 게시판\"] button')].find(button => button.textContent === '대학공지사항').click()");
      }
      if (label === "시간표 및 캘린더") {
        const layout = await run(`(() => {
          const days = [...document.querySelectorAll('.timetable-day')];
          const thursday = days[3];
          const grid = thursday.querySelector('ul').getBoundingClientRect();
          const [first, second] = [...thursday.querySelectorAll('li')].map((slot) => slot.getBoundingClientRect());
          const scroll = document.querySelector('.timetable-scroll');
          return {
            headings: days.map((day) => day.querySelector('h3 span').textContent),
            details: thursday.querySelector('.timetable-class-content').title,
            top: Math.round(first.top - grid.top), height: Math.round(first.height),
            hourHeight: document.querySelector('.timetable-hour').getBoundingClientRect().height,
            adjacent: Math.abs(first.right - second.left) < 1,
            sunday: days[6].textContent, lastHour: document.querySelector('.timetable-hour:last-child').textContent,
            scrollable: scroll.scrollWidth > scroll.clientWidth,
          };
        })()`);
        assert.deepEqual(layout.headings, ["월", "화", "수", "목", "금", "토", "일"]);
        assert.match(layout.details, /예시 교수.*검증 강의실.*강의계획서 기준/);
        assert.equal(layout.hourHeight, 52);
        assert.ok(Math.abs(layout.top - layout.hourHeight * 1.5) <= 1);
        assert.ok(Math.abs(layout.height - layout.hourHeight * 1.5) <= 1);
        assert.equal(layout.adjacent, true);
        assert.match(layout.sunday, /일요일 수업/);
        assert.equal(layout.lastHour, "19:00");
        assert.equal(layout.scrollable, true);
        await waitFor(async () => (await activeText()).includes("캘린더 마감 과제"), "timetable loads assignment deadlines");
        const selectView = (index) => run(`document.querySelectorAll('.timetable-views button')[${index}].click()`);
        await selectView(1);
        await waitFor(() => run("!!document.querySelector('.timetable-month-day[data-today]') && document.querySelector('.timetable-refresh:enabled') !== null"),
          "monthly calendar marks today");
        await run("document.querySelector('.timetable-month-date[aria-current=date]').click()");
        await waitFor(() => run("!!document.querySelector('.timetable-day [aria-current=date]') && document.querySelector('.timetable-refresh:enabled') !== null"),
          "selecting a date returns to its week");
        await run("document.querySelector('.timetable-deadline-cell button').click()");
        await waitFor(() => openedAssignments.length === 1, "timetable opens the assignment");
        assert.deepEqual(openedAssignments[0], { assignmentId: "1", courseId: "fixture" });
      }
      await refresh();
      await waitFor(() => pending.has(channel), label + " refresh starts");
      const duringRefresh = await activeText();
      assert.match(duringRefresh, /기존 자료/);
      assert.match(duringRefresh, /불러오는 중/);
      pending.get(channel)(failed);
      pending.delete(channel);
      await waitFor(async () => (await activeText()).includes(failed.message), label + " shows refresh error");
      assert.match(await activeText(), /기존 자료/);

      await refresh();
      await waitFor(() => pending.has(channel), label + " refresh retries");
      assert.match(await activeText(), /기존 자료/);
      data.set(channel, value("최신 자료"));
      if (channel === "list-campus-notices") noticeRevision++;
      pending.get(channel)(data.get(channel));
      pending.delete(channel);
      await waitFor(async () => (await activeText()).includes("최신 자료"), label + " replaces data after success");
      assert.doesNotMatch(await activeText(), /기존 자료|테스트 조회 오류/);
    }

    console.log("PASS: timetable, dorm, notices, briefing preserve displayed data during refresh and failure, then replace on success");
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    window?.destroy();
    rmSync(profile, { recursive: true, force: true });
    app.exit(process.exitCode ?? 0);
  }
}
void main();
