import assert from "node:assert/strict";
import test from "node:test";
import { ReadCache, StaleReadError } from "../dist-desktop/desktop/data-cache.js";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const lms = { lane: "lms", private: true };
const campus = { lane: "campus" };

test("prefetch, tab opening and refresh share in-flight work; refresh replaces cached data", async () => {
  const cache = new ReadCache();
  const first = deferred();
  let calls = 0;
  const load = () => { calls++; return first.promise; };
  const warm = cache.read("week", load, { ...lms, background: true });
  const visible = cache.read("week", load, lms);
  const refreshDuringLoad = cache.read("week", load, { ...lms, force: true });
  assert.equal(warm, visible);
  assert.equal(visible, refreshDuringLoad);
  assert.equal(calls, 1);
  first.resolve({ entries: ["first"] });
  assert.deepEqual(await visible, { entries: ["first"] });
  assert.deepEqual(await cache.read("week", () => assert.fail("cache miss"), lms), { entries: ["first"] });
  const next = deferred();
  const refreshing = cache.read("week", () => next.promise, { ...lms, force: true });
  assert.equal(cache.read("week", () => assert.fail("duplicate"), lms), refreshing);
  next.resolve({ entries: ["updated"] });
  await refreshing;
  assert.deepEqual(await cache.read("week", () => assert.fail("cache miss"), lms), { entries: ["updated"] });
});

test("login-required, ordinary errors and failed transports remain retryable", async () => {
  const cache = new ReadCache();
  for (const status of ["login_required", "error"]) {
    await cache.read("briefing", async () => ({ status }), lms);
    assert.deepEqual(await cache.read("briefing", async () => ({ status: "ok", value: status }), lms), { status: "ok", value: status });
    cache.resetPrivate();
  }
  await assert.rejects(cache.read("briefing", async () => { throw new Error("network"); }, lms), /network/);
  assert.deepEqual(await cache.read("briefing", async () => ({ status: "ok" }), lms), { status: "ok" });
});

test("a refresh failure preserves the last successful value until the session is rejected", async () => {
  const cache = new ReadCache();
  const old = { entries: ["previous"] };
  await cache.read("week", async () => old, lms);
  await cache.read("week", async () => ({ status: "error" }), { ...lms, force: true });
  assert.deepEqual(await cache.read("week", () => assert.fail("last success was lost"), lms), old);
  await cache.read("week", async () => ({ status: "login_required" }), { ...lms, force: true });
  assert.deepEqual(await cache.read("week", async () => ({ entries: ["fresh"] }), lms), { entries: ["fresh"] });
});

test("TTL starts on completion and expired data reloads", async () => {
  let clock = 0;
  const cache = new ReadCache({ ttlMs: 300, now: () => clock });
  const gate = deferred();
  const request = cache.read("menu", () => gate.promise, { lane: "dorm" });
  clock = 100;
  gate.resolve({ version: 1 });
  await request;
  clock = 399;
  assert.deepEqual(await cache.read("menu", () => assert.fail("too early"), { lane: "dorm" }), { version: 1 });
  clock = 400;
  assert.deepEqual(await cache.read("menu", async () => ({ version: 2 }), { lane: "dorm" }), { version: 2 });
});

test("account reset discards old private results and queued work but retains public data", async () => {
  const cache = new ReadCache();
  await cache.read("public", async () => ({ value: "public" }), campus);
  const old = deferred();
  const first = cache.read("week", () => old.promise, lms);
  const firstRejected = assert.rejects(first, StaleReadError);
  const queued = cache.read("briefing", () => assert.fail("old queued loader ran"), lms);
  const queuedRejected = assert.rejects(queued, StaleReadError);
  cache.resetPrivate();
  await Promise.all([firstRejected, queuedRejected]);
  let nextStarted = false;
  const fresh = cache.read("week", async () => { nextStarted = true; return { account: "new" }; }, lms);
  assert.equal(nextStarted, false, "old loader must retain the serial LMS lane until completion");
  old.resolve({ account: "old" });
  assert.deepEqual(await fresh, { account: "new" });
  assert.deepEqual(await cache.read("week", () => assert.fail("new cache lost"), lms), { account: "new" });
  assert.deepEqual(await cache.read("public", () => assert.fail("public cache lost"), campus), { value: "public" });
});

test("foreground reads pass queued prefetches and public lanes run independently", async () => {
  const cache = new ReadCache();
  const order = [];
  const hold = deferred();
  const first = cache.read("active", () => { order.push("active"); return hold.promise; }, lms);
  const background = cache.read("warm", async () => { order.push("warm"); return {}; }, { ...lms, background: true });
  const visible = cache.read("visible", async () => { order.push("visible"); return {}; }, lms);
  await cache.read("public", async () => { order.push("public"); return {}; }, campus);
  assert.deepEqual(order, ["active", "public"]);
  hold.resolve({});
  await Promise.all([first, background, visible]);
  assert.deepEqual(order, ["active", "public", "visible", "warm"]);
});

test("a foreground subscriber promotes an already queued background request", async () => {
  const cache = new ReadCache();
  const order = [];
  const hold = deferred();
  const first = cache.read("active", () => hold.promise, campus);
  const earlier = cache.read("earlier", async () => { order.push("earlier"); return {}; }, { ...campus, background: true });
  const promoted = cache.read("clicked", async () => { order.push("clicked"); return {}; }, { ...campus, background: true });
  assert.equal(cache.read("clicked", () => assert.fail("duplicated clicked request"), campus), promoted);
  hold.resolve({});
  await Promise.all([first, earlier, promoted]);
  assert.deepEqual(order, ["clicked", "earlier"]);
});

test("resetAll prevents old public work from overwriting a new request and private scopes cannot collide", async () => {
  const cache = new ReadCache();
  const old = deferred();
  const stale = cache.read("shared", () => old.promise, campus);
  const rejected = assert.rejects(stale, StaleReadError);
  cache.resetAll();
  await rejected;
  const fresh = cache.read("shared", async () => "new", campus);
  old.resolve("old");
  assert.equal(await fresh, "new");
  assert.equal(await cache.read("shared", async () => "private", lms), "private");
  assert.equal(await cache.read("shared", () => assert.fail("public overwritten"), campus), "new");
});

test("least recently read entries are evicted at the bounded memory limit", async () => {
  const cache = new ReadCache({ maxEntries: 2 });
  await cache.read("a", async () => "a", campus);
  await cache.read("b", async () => "b", campus);
  await cache.read("a", () => assert.fail("a evicted too early"), campus);
  await cache.read("c", async () => "c", campus);
  assert.equal(await cache.read("a", () => assert.fail("recent a evicted"), campus), "a");
  assert.equal(await cache.read("b", async () => "b reloaded", campus), "b reloaded");
});
