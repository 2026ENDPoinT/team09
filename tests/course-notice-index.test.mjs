import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { AccountScreenCache } from "../dist-desktop/desktop/account-screen-cache.js";
import { CourseNoticeIndex } from "../dist-desktop/desktop/course-notice-index.js";

const course = { id: "course-a", name: "예시 수업", professor: null, category: "regular" };
const otherCourse = { ...course, id: "course-b", name: "다른 수업" };
const notice = (id, title = "수업 공지 " + id) => ({ id, title, created_at: null, content: "목록 미리보기" });
const body = (id, text = "전체 본문 " + id) => ({ id, text, body_html: `<p>${text}</p>` });
const error = { status: "error", message: "조회 실패" };

test("fills all listed pages once, preserves bodies across restarts and only refreshes changed or missing bodies", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "ast-course-notice-index-"));
  t.after(() => rm(root, { force: true, recursive: true }));
  let firstPage = [notice("1"), notice("2")];
  let secondPage = [notice("3"), notice("4")];
  let failSecondPage = false;
  let failBody;
  const reads = [];
  const read = async (tool, { course_id, page, notice_ids }) => {
    assert.equal(course_id, course.id);
    if (tool === "get_course_notice_page") {
      if (page === 2 && failSecondPage) return error;
      return { notices: page === 1 ? firstPage : secondPage, has_next: page === 1 };
    }
    assert.equal(tool, "get_course_notice_bodies");
    reads.push({ page, ids: notice_ids });
    return { bodies: notice_ids.filter((id) => id !== failBody).map((id) => body(id)) };
  };
  const disk = new AccountScreenCache(root);
  const first = new CourseNoticeIndex([course], disk, read, Promise.resolve());
  t.after(() => first.stop());
  await first.refresh();
  assert.deepEqual(reads.splice(0), [{ page: 1, ids: ["1", "2"] }, { page: 2, ids: ["3", "4"] }]);
  assert.equal((await first.snapshot()).entries.length, 4);
  first.stop();
  await disk.flush();

  const restarted = new CourseNoticeIndex([course], new AccountScreenCache(root), read, Promise.resolve());
  t.after(() => restarted.stop());
  assert.equal((await restarted.snapshot()).entries.find(({ notice }) => notice.id === "4").body.text, "전체 본문 4");
  await restarted.refresh();
  assert.deepEqual(reads, []);

  firstPage = [notice("5"), notice("1", "바뀐 제목")];
  secondPage = [notice("2"), notice("4")];
  failSecondPage = true;
  failBody = "5";
  await restarted.refresh();
  assert.deepEqual(reads.splice(0), [{ page: 1, ids: ["5", "1"] }]);
  assert.ok(restarted.entry(course.id, "3"), "a failed page cannot remove saved notices");
  assert.equal((await restarted.snapshot()).partial, true);

  failSecondPage = false;
  failBody = undefined;
  await restarted.refresh();
  assert.deepEqual(reads, [{ page: 1, ids: ["5"] }]);
  assert.equal(restarted.entry(course.id, "2").notice.page, 2);
  assert.equal(restarted.entry(course.id, "3"), undefined, "a complete scan reconciles removed notices");
  assert.equal((await restarted.snapshot()).partial, false);

  const withdrawn = new CourseNoticeIndex([otherCourse], disk, read, Promise.resolve());
  t.after(() => withdrawn.stop());
  assert.deepEqual((await withdrawn.snapshot()).entries, [], "only the current roster can restore notices");
  const otherAccount = new CourseNoticeIndex([course], new AccountScreenCache(join(root, "other")), read, Promise.resolve());
  t.after(() => otherAccount.stop());
  assert.deepEqual((await otherAccount.snapshot()).entries, [], "another account does not inherit course notices");
});

test("manual refresh can start before the home finishes, and an expired session removes its search results", async (t) => {
  let signedIn = true;
  const read = async (tool) => !signedIn ? { status: "login_required", message: "다시 로그인해 주세요." }
    : tool === "get_course_notice_page" ? { notices: [notice("1")], has_next: false } : { bodies: [body("1")] };
  const index = new CourseNoticeIndex([course], undefined, read, new Promise(() => {}));
  t.after(() => index.stop());
  void index.refresh();
  await index.snapshot();
  await index.refresh(true);
  assert.equal((await index.snapshot()).entries.length, 1);
  signedIn = false;
  await index.refresh(true);
  const snapshot = await index.snapshot();
  assert.equal(snapshot.error.status, "login_required");
  assert.deepEqual(snapshot.entries, []);
  assert.equal(index.entry(course.id, "1"), undefined);
});

test("scheduled refresh includes new notices without opening the screen", async (t) => {
  let hasNewNotice = false;
  const reads = [];
  const index = new CourseNoticeIndex([course], undefined, async (tool, { notice_ids }) => {
    if (tool === "get_course_notice_page") {
      return { notices: hasNewNotice ? [notice("2"), notice("1")] : [notice("1")], has_next: false };
    }
    reads.push(...notice_ids);
    return { bodies: notice_ids.map((id) => body(id)) };
  }, Promise.resolve(), 20);
  t.after(() => index.stop());
  await index.refresh();
  hasNewNotice = true;
  for (let tries = 0; tries < 100 && !index.entry(course.id, "2")?.body; tries++) await delay(10);
  assert.equal(index.entry(course.id, "2")?.body?.text, "전체 본문 2");
  assert.deepEqual(reads, ["1", "2"]);
});
