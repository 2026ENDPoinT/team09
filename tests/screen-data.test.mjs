import assert from "node:assert/strict";
import test from "node:test";
import { ScreenData } from "../dist-desktop/desktop/screen-data.js";

const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
function today() {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts();
  return ["year", "month", "day"].map((kind) => parts.find((part) => part.type === kind).value).join("-");
}
function shift(iso, delta) {
  const date = new Date(iso + "T00:00:00Z");
  date.setUTCDate(date.getUTCDate() + delta);
  return date.toISOString().slice(0, 10);
}
function reply(tool, args, version = 1) {
  if (tool === "get_course_timetable") return {
    on_date: args.on_date, week_start: args.on_date, week_end: shift(args.on_date, 6), timezone: "Asia/Seoul", entries: [], version,
  };
  if (tool === "get_course_overview") return { status: "ok", overview: { regular: 0, non_regular: 0, courses: [] }, version };
  if (tool === "get_course_briefing") return { as_of: today() + "T12:00:00+09:00", pending_assignments: [], completed_assignments: [], recent_notices: [], version };
  if (tool === "get_campus_briefing") return { as_of: today() + "T12:00:00+09:00", notices: [], unavailable: [], version };
  if (tool === "list_campus_notices") return { board: args.board, notices: [], next_page: args.start_page + args.pages, version };
  if (tool === "get_dorm_menu") {
    const start = shift(args.on_date, -(new Date(args.on_date + "T00:00:00Z").getUTCDay() + 6) % 7);
    return {
      dorm: args.dorm, dorm_name: args.dorm, period: "week", on_date: args.on_date, week_start: start, week_end: shift(start, 6),
      days: Array.from({ length: 7 }, (_, i) => ({ date: shift(start, i), weekday: "월화수목금토일"[i], meals: { breakfast: "검증", lunch: "검증", dinner: "검증" }, notes: [] })),
      source_url: "https://housing.seoultech.ac.kr/livng/dining/", version,
    };
  }
  throw new Error("Unexpected fixture tool " + tool);
}
function fixture(requestOverride) {
  const calls = [];
  const notifications = [];
  const complete = deferred();
  const data = new ScreenData(async (tool, args, timeout) => {
    calls.push({ tool, args, timeout });
    return requestOverride ? requestOverride(tool, args) : reply(tool, args);
  }, (state) => {
    notifications.push(state);
    if (state.state === "ready" || state.state === "partial") complete.resolve(state);
  });
  return { data, calls, notifications, complete: complete.promise };
}

test("login warmup loads all fourteen screen datasets without opening any tab", async () => {
  const { data, calls, notifications, complete } = fixture();
  data.warm();
  const last = await complete;
  assert.equal(last.state, "ready");
  assert.equal(last.completed, 14);
  assert.equal(last.total, 14);
  assert.equal(calls.length, 15);
  const counts = Object.fromEntries([...new Set(calls.map((call) => call.tool))].map((tool) => [tool, calls.filter((call) => call.tool === tool).length]));
  assert.deepEqual(counts, {
    get_course_timetable: 4, get_course_overview: 1, get_course_briefing: 1,
    list_campus_notices: 5, get_campus_briefing: 1, get_dorm_menu: 3,
  });
  assert.ok(calls.filter((call) => call.tool === "list_campus_notices").every((call) => call.args.start_page === 1 && call.args.pages === 3));
  assert.deepEqual(notifications.filter((state) => state.state !== "idle").map((state) => state.completed), Array.from({ length: 15 }, (_, i) => i));
});

test("opening first views during warmup joins existing jobs and reuses their results", async () => {
  const gate = deferred();
  const { data, calls, complete } = fixture(async (tool, args) => { await gate.promise; return reply(tool, args); });
  data.warm();
  const views = [data.timetable(), data.overview(), data.courseBriefing(), data.campusBriefing(), data.campusList("notice", 1), data.dorm("kb", "today")];
  gate.resolve();
  const values = await Promise.all(views);
  await complete;
  assert.ok(values.every((value) => !("status" in value) || value.status === "ok"));
  assert.equal(calls.length, 15);
  await Promise.all([data.timetable(), data.overview(), data.courseBriefing(), data.campusBriefing(), data.campusList("notice", 1), data.dorm("kb", "week")]);
  assert.equal(calls.length, 15);
});

test("weekly dorm result supplies today's meals without a second school query", async () => {
  const { data, calls } = fixture();
  const week = await data.dorm("surim", "week");
  const day = await data.dorm("surim", "today");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].args.period, "week");
  assert.equal(week.days.length, 7);
  assert.equal(day.days.length, 1);
  assert.equal(day.period, "today");
  assert.equal(day.days[0].date, today());
  assert.deepEqual(day.days[0], week.days.find((entry) => entry.date === today()));
  assert.equal((await data.dorm("surim", "week")).days.length, 7, "deriving today must not mutate cached week");
});

test("Monday–Sunday timetable combines source weeks across a year boundary and reuses cached weeks", async () => {
  const { data, calls } = fixture((tool, args) => ({ ...reply(tool, args), entries: [0, 1, 6].map((offset) => ({ date: shift(args.on_date, offset) })) }));
  const first = await data.timetable("2025-12-29");
  const second = await data.timetable("2026-01-04");
  assert.deepEqual(calls.map(({ args }) => args.on_date), ["2025-12-28", "2026-01-04"]);
  assert.equal(first.on_date, "2025-12-29");
  assert.equal(second.on_date, "2026-01-04");
  assert.equal(second.week_start, "2025-12-29");
  assert.equal(second.week_end, "2026-01-04");
  assert.deepEqual(first.entries.map(({ date }) => date), ["2025-12-29", "2026-01-03", "2026-01-04"]);
  assert.deepEqual(second.entries, first.entries);
  const next = await data.timetable("2026-01-05");
  assert.equal(next.week_start, "2026-01-05");
  assert.deepEqual(calls.map(({ args }) => args.on_date), ["2025-12-28", "2026-01-04", "2026-01-11"]);
  assert.equal((await data.timetable("2026-02-30")).status, "error");
  assert.equal(calls.length, 3);
});

test("forced refresh replaces a cached partial result with a new result", async () => {
  let attempts = 0;
  const { data, calls } = fixture(async (tool, args) => ({ ...reply(tool, args), version: ++attempts, unavailable: attempts === 1 ? ["notice"] : [] }));
  assert.equal((await data.campusBriefing()).version, 1);
  assert.equal((await data.campusBriefing()).version, 1);
  const refreshed = await data.campusBriefing({ force: true });
  assert.equal(refreshed.version, 2);
  assert.deepEqual(refreshed.unavailable, []);
  assert.equal(calls.length, 2);
});

test("one failing background task produces partial readiness and all other jobs finish", async () => {
  const { data, calls, complete } = fixture(async (tool, args) => {
    if (tool === "get_course_briefing") throw new Error("fixture outage");
    return reply(tool, args);
  });
  data.warm();
  const last = await complete;
  assert.equal(last.state, "partial");
  assert.equal(last.completed, 14);
  assert.equal(calls.length, 15);
  assert.equal((await data.dorm("kb", "today")).days.length, 1);
});

test("relogin drops in-flight private data, blocks unauthenticated reads and preserves public cache", async () => {
  const old = deferred();
  let privateCalls = 0;
  const { data, calls, complete } = fixture(async (tool, args) => {
    if (tool === "get_course_overview" && ++privateCalls === 1) return old.promise;
    return reply(tool, args, 2);
  });
  await data.dorm("kb", "week");
  const before = data.overview();
  data.invalidateSession();
  assert.equal((await before).status, "error");
  assert.equal((await data.courseBriefing()).status, "login_required");
  assert.equal(calls.filter((call) => call.tool === "get_course_briefing").length, 0);
  data.warm();
  old.resolve(reply("get_course_overview", {}, 1));
  await complete;
  const latest = await data.overview();
  assert.equal(latest.version, 2);
  assert.equal(calls.filter((call) => call.tool === "get_dorm_menu" && call.args.dorm === "kb").length, 1);
  assert.ok(data.status.sessionRevision > 0);
});

test("login's request timer starts only after the previous private read leaves the LMS lane", async () => {
  const gate = deferred();
  const { data } = fixture(async () => gate.promise);
  const oldRead = data.overview();
  data.invalidateSession();
  assert.equal((await oldRead).status, "error");
  let authenticationStarted = false;
  const auth = data.authenticate(async () => {
    authenticationStarted = true;
    return { status: "authenticated" };
  });
  assert.equal(authenticationStarted, false);
  gate.resolve(reply("get_course_overview", {}));
  assert.equal((await auth).status, "authenticated");
  assert.equal(authenticationStarted, true);
});

test("shutdown discards queued warmup work and never starts another loader when active reads finish", async () => {
  const gate = deferred();
  const { data, calls, notifications } = fixture(async (tool, args) => {
    await gate.promise;
    return reply(tool, args);
  });
  data.warm();
  assert.deepEqual(calls.map(({ tool }) => tool), ["get_course_overview", "list_campus_notices", "get_dorm_menu"]);
  const started = calls.length;
  const notificationsBeforeShutdown = notifications.length;
  data.shutdown();
  gate.resolve();
  // Flush the active reads and the rejected queued jobs, including warmup finally callbacks.
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls.length, started, "queued background jobs must not restart MCP while quitting");
  assert.equal(notifications.length, notificationsBeforeShutdown, "obsolete warmup progress must stay suppressed");
  assert.equal((await data.overview()).status, "error");
  assert.equal((await data.dorm("kb", "today")).status, "error");
  assert.equal(calls.length, started, "new reads must remain blocked after shutdown");
});
