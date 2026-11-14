import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { CampusNoticeIndex } from "../dist-desktop/desktop/campus-notice-index.js";
import { ScreenData } from "../dist-desktop/desktop/screen-data.js";
import { campusNoticeKey, campusNoticeLink } from "../dist-desktop/shared/campus-notices.js";
import { departmentNoticeSources } from "../dist-desktop/shared/seoultech-department-notices.js";

const notice = (id, title = "프로그램 공지") => ({
  board: "notice", board_id: "4691", id, title, published_at: "2026-11-13", department: "예시 부서",
  pinned: false, has_attachments: false, url: `https://www.seoultech.ac.kr/service/info/notice?do=commonview&bnum=4691&bidx=${id}`,
});
const detail = (item) => ({ ...item, content: "교환학생과 함께하는 문화 체험 행사예요.", attachments: [], images: [] });
const page = (board, notices = [], next_page = null) => ({ board, notices, next_page });

async function settled(read) {
  for (let attempt = 0; attempt < 100; attempt++) {
    const snapshot = await read();
    if (!snapshot.loading) return snapshot;
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail("The notice index did not finish.");
}

test("public board and detail records are shared by search, browsing, and restarted profiles", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "ast-notice-index-"));
  t.after(() => rm(directory, { force: true, recursive: true }));
  const item = notice("1");
  const browsed = notice("2");
  const calls = [];
  const request = async (tool, args) => {
    calls.push([tool, args]);
    if (tool === "get_campus_notice") return detail(args.notice_id === item.id ? item : browsed);
    assert.equal(tool, "list_campus_notices");
    if (args.board !== "notice") return page(args.board);
    return args.start_page === 1 ? page("notice", [item], 4) : page("notice", [browsed]);
  };
  const options = { directory: () => directory, busy: () => false, publicDirectory: directory };
  const screen = new ScreenData(request, () => {}, options);
  screen.syncCampusNoticeIndex();
  screen.syncCampusNoticeIndex();
  const [, body] = await Promise.all([screen.campusList("notice", 1), screen.campusDetail("notice", "4691", "1")]);
  assert.equal(body.content, detail(item).content);
  let snapshot = await settled(() => screen.campusNoticeIndex());
  assert.equal(calls.filter(([name]) => name === "list_campus_notices").length, 5);
  assert.equal(calls.filter(([name]) => name === "get_campus_notice").length, 1);
  assert.ok(snapshot.entries[campusNoticeKey(item)].tags.includes("international"));
  assert.equal(snapshot.pages.notice.nextPage, 4);
  assert.equal(await screen.campusNoticeIndex(snapshot.revision), null);

  await screen.campusList("notice", 4);
  snapshot = await settled(() => screen.campusNoticeIndex());
  assert.equal(snapshot.pages.notice.lastPage, 4);
  assert.equal(snapshot.pages.notice.nextPage, null);
  assert.deepEqual(snapshot.notices.map(({ id }) => id), ["1", "2"]);
  assert.equal(calls.filter(([name]) => name === "get_campus_notice").length, 2);
  await screen.shutdown();

  const restarted = new ScreenData(async () => assert.fail("Warm notice search must not refetch."), () => {}, options);
  const saved = await restarted.campusNoticeIndex();
  assert.deepEqual(saved.entries, snapshot.entries);
  restarted.syncCampusNoticeIndex();
  const reused = await settled(() => restarted.campusNoticeIndex());
  assert.deepEqual(reused.entries, snapshot.entries);
  assert.equal(reused.partial, false);
  await restarted.shutdown();
});

test("forced lists reindex changes only and stale-body failures retain searchable text with partial coverage", async (t) => {
  const item = notice("1");
  const removed = notice("2");
  const added = notice("3");
  const error = { status: "error", message: "fixture failure" };
  let rows = [item, removed];
  let now = Date.parse("2026-11-13T08:00:00+09:00");
  let detailFailure = false;
  const reads = [];
  const index = new CampusNoticeIndex(
    async (board) => page(board, board === "notice" ? rows : []),
    async (location) => {
      reads.push(location.id);
      return detailFailure ? error : detail(rows.find(({ id }) => id === location.id));
    },
    undefined, () => now,
  );
  t.after(() => index.stop());
  index.sync();
  let snapshot = await settled(() => index.snapshot());
  assert.deepEqual(reads, ["1", "2"]);
  index.sync(true);
  snapshot = await settled(() => index.snapshot());
  assert.deepEqual(reads, ["1", "2"], "A forced list refresh preserves fresh unchanged details.");

  rows = [{ ...item, title: "수강신청 정정 안내" }, added];
  index.sync(true);
  snapshot = await settled(() => index.snapshot());
  assert.deepEqual(reads, ["1", "2", "1", "3"]);
  assert.deepEqual(snapshot.notices.map(({ id }) => id), ["1", "3"]);
  assert.ok(snapshot.entries[campusNoticeKey(item)].tags.includes("academic"));
  assert.ok(!snapshot.entries[campusNoticeKey(removed)]);

  now += 25 * 60 * 60_000;
  detailFailure = true;
  index.sync();
  snapshot = await settled(() => index.snapshot());
  assert.equal(snapshot.partial, true);
  assert.equal(snapshot.entries[campusNoticeKey(item)].detail.title, "수강신청 정정 안내");
});

test("bounded older pages keep the last browse cursor and clear beyond a shortened board", async (t) => {
  let shortened = false;
  const index = new CampusNoticeIndex(
    async (board, start) => page(board, [notice(String(start))], shortened ? null : start === 1 ? 4 : start + 1),
    async () => assert.fail("Browsing without an active index does not start a detail scan."),
  );
  t.after(() => index.stop());
  await index.list("notice", 1);
  for (let start = 4; start <= 20; start++) await index.list("notice", start);
  let snapshot = await index.snapshot();
  assert.equal(snapshot.notices.length, 16, "Retain the head and fifteen extra page slices.");
  assert.deepEqual(snapshot.notices.slice(0, 2).map(({ id }) => id), ["1", "6"]);
  assert.equal(snapshot.pages.notice.nextPage, 21);

  shortened = true;
  await index.list("notice", 1, true);
  snapshot = await index.snapshot();
  assert.deepEqual(snapshot.notices.map(({ id }) => id), ["1"]);
  assert.equal(snapshot.pages.notice.nextPage, null);
});

test("department snapshots follow the saved affiliation and reuse public bodies after a restart", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "ast-affiliation-index-"));
  t.after(() => rm(directory, { force: true, recursive: true }));
  const { college, department } = departmentNoticeSources("computer");
  const selected = [college.id, department.id];
  const { college: fallback, department: missing } = departmentNoticeSources("open-information");
  assert.equal(fallback, college);
  assert.equal(missing, undefined);
  const item = (source) => ({
    ...notice("7"), board: source.id, board_id: source.boardIds[0],
    url: `${source.listUrl}?do=commonview&bnum=${source.boardIds[0]}&bidx=7`,
  });
  const items = new Map([college, department].map((source) => [source.id, item(source)]));
  const calls = [];
  const options = { directory: () => directory, busy: () => false, publicDirectory: directory };
  const screen = new ScreenData(async (tool, args) => {
    calls.push([tool, args.source_id]);
    const row = items.get(args.source_id);
    assert.ok(row);
    if (tool === "get_department_notice") return detail(row);
    assert.equal(tool, "list_department_notices");
    return page(row.board, [row]);
  }, () => {}, options);
  screen.syncCampusNoticeIndex(false, selected);
  const full = await settled(() => screen.campusNoticeIndex(undefined, selected));
  assert.deepEqual(full.listedBoards, selected);
  assert.equal(Object.keys(full.entries).length, 2, "identical article IDs in different boards have distinct cache keys");
  assert.ok(full.entries[campusNoticeKey(item(department))].tags.includes("international"));
  assert.equal((await screen.campusNoticeIndex()).notices.length, 0);
  const fallbackOnly = await screen.campusNoticeIndex(full.revision, [college.id]);
  assert.deepEqual(fallbackOnly.notices.map((row) => row.board), [college.id]);
  assert.equal(calls.length, 4);
  await screen.shutdown();

  let unexpectedReads = 0;
  const restarted = new ScreenData(async () => { unexpectedReads++; throw new Error("Unexpected read"); }, () => {}, options);
  restarted.syncCampusNoticeIndex(false, selected);
  const warm = await settled(() => restarted.campusNoticeIndex(undefined, selected));
  assert.deepEqual(warm.entries, full.entries);
  assert.equal(warm.partial, false);
  assert.equal(unexpectedReads, 0);
  await restarted.shutdown();
});

test("department original links use known boards, including the architecture archive", () => {
  const { department } = departmentNoticeSources("computer");
  const article = `${department.listUrl}?do=commonview&bnum=${department.boardIds[0]}&bidx=123`;
  assert.equal(campusNoticeLink(article)?.href, article);
  assert.equal(campusNoticeLink(`${department.listUrl}?do=commonview&bnum=0&bidx=123`), null);
  assert.equal(campusNoticeLink(article + "&next=https://example.org"), null);
  const archive = "https://archidesign.seoultech.ac.kr/kr/info/notice.php?bgu=view&idx=1220";
  assert.equal(campusNoticeLink(archive)?.href, archive);
});
