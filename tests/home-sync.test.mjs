import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import { AccountScreenCache } from "../dist-desktop/desktop/account-screen-cache.js";
import { HomeSync } from "../dist-desktop/desktop/home-sync.js";
import { BackgroundReadDeferred, LmsAccess } from "../dist-desktop/desktop/lms-access.js";

const roster = {
  regular: 1, non_regular: 0,
  courses: [{ id: "A-test", name: "테스트 수업", professor: null, category: "regular" }],
};
const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", dateStyle: "short" }).format(new Date());
const timetable = { on_date: today, week_start: today, week_end: today, timezone: "Asia/Seoul", entries: [
  { course_id: "A-test", course_name: "테스트 수업", date: today, weekday: "금", start_time: "09:00", end_time: "10:00", room: "101" },
] };
const notice = { id: "1", course_id: "A-test", course_name: "", title: "첫 공지", created_at: new Date(Date.now() - 60_000).toISOString() };

function index(version) {
  return {
    assignments: [
      { id: "1", title: "과제 하나", submitted: false, signature: "same" },
      ...(version > 1 ? [{ id: "2", title: "새 과제", submitted: false, signature: "added" }] : []),
    ],
    notices: [version > 1 ? { ...notice, title: "수정 공지" } : notice],
    counts: { assignment: version }, learning_activity: { completed: 0, total: version }, signature: String(version),
  };
}

test("saved home is account-scoped, refreshes timetable and lists first, then reads only changed assignments", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "ast-home-cache-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  let version = 1;
  let calls = [];
  let snapshots = [];
  const read = async (name, args) => {
    calls.push([name, args]);
    if (name === "get_course_timetable") return timetable;
    if (name === "get_home_course_index") return index(version);
    if (name === "get_course_notice") return { body_html: "<p>수정 공지 본문</p>", attachments: [] };
    return {
      assignments: args.assignment_ids.map((id) => ({ id, due_at: today + "T23:59:00+09:00", submitted: false, submitted_at: null })),
      stats: { counts: { files: 1 }, attendance: { present: 2 }, total_posts: null },
    };
  };
  const diskA = new AccountScreenCache(join(root, "a"));
  const first = new HomeSync(roster, diskA, read, () => false, () => snapshots.push(first.snapshot()));
  await first.refresh();
  first.stop();
  await diskA.flush();
  assert.deepEqual(calls.map(([name]) => name), ["get_course_timetable", "get_home_course_index", "get_home_course_details"]);
  assert.equal(snapshots[0].timetable.entries.length, 1);
  const firstAssignments = snapshots.find((value) => value.briefing?.pending_assignments.length);
  assert.equal(firstAssignments.briefing.pending_assignments[0].due_at, today + "T23:59:00+09:00");
  assert.equal(first.snapshot().changes.length, 0);

  calls = [];
  snapshots = [];
  const second = new HomeSync(roster, new AccountScreenCache(join(root, "a")), read, () => false, () => snapshots.push(second.snapshot()));
  t.after(() => second.stop());
  await second.ready;
  assert.equal(second.snapshot().briefing.pending_assignments[0].due_at, today + "T23:59:00+09:00");
  const other = new HomeSync(roster, new AccountScreenCache(join(root, "b")), read, () => false, () => {});
  await other.ready;
  assert.equal(other.snapshot().briefing, null);
  assert.equal(other.snapshot().timetable, null);
  await second.refresh();
  assert.deepEqual(calls.map(([name]) => name), ["get_course_timetable", "get_home_course_index"]);
  calls = [];
  version = 2;
  await second.refresh();
  assert.deepEqual(calls[2][1].assignment_ids, ["2"]);
  assert.equal(calls[3][0], "get_course_notice");
  assert.deepEqual(second.snapshot().changes.map(({ title }) => title), ["새 과제", "수정 공지"]);
  assert.equal(second.snapshot().briefing.pending_assignments.length, 2);
  calls = [];
  await second.refresh();
  assert.deepEqual(calls.map(([name]) => name), ["get_course_timetable", "get_home_course_index"]);
});

test("saved deadlines stay visible across partial batches and a failed refresh retries the old deadline", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "ast-home-deadlines-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const disk = new AccountScreenCache(root);
  const oldDue = today + "T23:59:00+09:00";
  const newDue = today + "T22:00:00+09:00";
  const secondCourse = { ...roster.courses[0], id: "B-test", name: "다른 테스트 수업" };
  const courses = { ...roster, regular: 2, courses: [...roster.courses, secondCourse] };
  const read = (version, failSecond = false) => async (name, { course_id, assignment_ids }) => {
    if (name === "get_course_timetable") return timetable;
    if (name === "get_home_course_index") {
      const data = index(1);
      return { ...data, assignments: data.assignments.map((item) => ({ ...item, signature: String(version) })) };
    }
    if (course_id === secondCourse.id && failSecond) return { assignments: [], stats: null };
    return { assignments: assignment_ids.map((id) => ({ id, due_at: version === 1 ? oldDue : newDue,
      submitted: false, submitted_at: null, signature: String(version) })), stats: null };
  };
  const initial = new HomeSync(courses, disk, read(1), () => false, () => {});
  await initial.refresh();
  initial.stop();
  await disk.flush();

  const values = (home) => home.snapshot().briefing.pending_assignments.map(({ due_at }) => due_at);
  const snapshots = [];
  let failSecond = true;
  const sync = new HomeSync(courses, new AccountScreenCache(root), (...args) => read(2, failSecond)(...args),
    () => false, () => snapshots.push(values(sync)));
  t.after(() => sync.stop());
  await sync.ready;
  assert.deepEqual(values(sync), [oldDue, oldDue]);
  await sync.refresh();
  const firstUpdate = snapshots.findIndex(([due]) => due === newDue);
  assert.ok(firstUpdate > 0);
  assert.ok(snapshots.slice(0, firstUpdate).every(([a, b]) => a === oldDue && b === oldDue));
  assert.deepEqual(values(sync), [newDue, oldDue]);
  assert.equal(sync.snapshot().error?.status, "error");

  failSecond = false;
  await sync.refresh();
  assert.deepEqual(values(sync), [newDue, newDue]);
  assert.equal(sync.snapshot().error, undefined);
});

test("the scheduled refresh waits for ongoing work and resumes after it ends", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "ast-home-pause-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  let busy = true;
  const calls = [];
  const disk = new AccountScreenCache(root);
  const sync = new HomeSync({ ...roster, courses: [] }, disk, async (name, _args, background) => {
    calls.push([name, background]);
    return timetable;
  }, () => busy, () => {}, 25);
  t.after(() => sync.stop());
  await sync.refresh();
  await delay(75);
  assert.deepEqual(calls, [["get_course_timetable", false]], "initial load proceeds, periodic load pauses");
  busy = false;
  for (let tries = 0; tries < 30 && calls.length < 2; tries++) await delay(50);
  assert.deepEqual(calls[1], ["get_course_timetable", true]);
  sync.stop();
  await disk.flush();
});

test("a queued background read rechecks activity under the LMS lock", async () => {
  const access = new LmsAccess();
  const release = await access.acquire();
  access.browserCourse = "A-test";
  let busy = false;
  let ran = false;
  const queued = access.connectorRead(async () => { ran = true; }, () => !busy);
  busy = true;
  release();
  await assert.rejects(queued, BackgroundReadDeferred);
  assert.equal(ran, false);
  assert.equal(access.browserCourse, "A-test");
});
