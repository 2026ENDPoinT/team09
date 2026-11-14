import assert from "node:assert/strict";
import test from "node:test";
import { LmsAccess } from "../dist-desktop/desktop/lms-access.js";
import { createLmsConnector } from "../dist-desktop/desktop/lms-connector.js";
import { ACTIVITY_PATH, ECLASS_ORIGIN, assignmentIdFromUrl, assignmentTarget, assignmentUrl, parseCourseBrowserPage } from "../dist-desktop/shared/assignment-browser.js";

test("only official assignment routes supply browser context", () => {
  assert.equal(assignmentIdFromUrl(assignmentUrl("1001")), "1001");
  assert.equal(assignmentIdFromUrl("https://eclass.seoultech.ac.kr/ilos/cls/st/report/report_view_form.acl?RT_SEQ=1001"), "1001");
  for (const url of ["https://other.example/?m=report&n=1001", assignmentUrl("../invalid"), assignmentUrl("1001").replace("m=report", "m=discuss")]) {
    assert.equal(assignmentIdFromUrl(url), undefined);
  }
  assert.equal(assignmentTarget({ assignmentId: "1001", courseId: "../other" }), undefined);
});

test("course windows reject forged routes and activity identifiers", () => {
  assert.deepEqual(parseCourseBrowserPage({ kind: "attendance" }), { kind: "attendance" });
  assert.deepEqual(parseCourseBrowserPage({ kind: "open_board", boardId: "forum_01" }), { kind: "open_board", boardId: "forum_01" });
  assert.equal(parseCourseBrowserPage({ kind: "constructor" }), undefined);
  assert.equal(parseCourseBrowserPage({ kind: "open_board", boardId: "4&another=3" }), undefined);
  const url = ACTIVITY_PATH + "?m=lecture_material&n=1001";
  const activity = { kind: "activity", activityId: "1001", url };
  assert.deepEqual(parseCourseBrowserPage(activity), { ...activity, url: ECLASS_ORIGIN + url });
  for (const invalid of [
    { ...activity, activityId: "1002" }, { ...activity, url: url + "&n=1002" },
    { ...activity, url: url.replace("lecture_material", "report_submit") },
    { ...activity, url: "https://other.example" + url },
  ]) assert.equal(parseCourseBrowserPage(invalid), undefined);
});

test("a browser cannot change course during an in-flight MCP read", async () => {
  const access = new LmsAccess();
  access.browserCourse = "previous-course";
  let finishRead;
  let started;
  const entered = new Promise((resolve) => { started = resolve; });
  const read = access.connectorRead(() => new Promise((resolve) => { finishRead = resolve; started(); }));
  await entered;
  assert.equal(access.browserCourse, undefined);
  let browserEntered = false;
  const browser = access.acquire().then((release) => { browserEntered = true; release(); });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(browserEntered, false);
  finishRead("read complete");
  await Promise.all([read, browser]);
  assert.equal(browserEntered, true);
});

test("closed windows cancel queued reads before Python starts and shutdown cannot reconnect", async () => {
  // These nonexistent paths make any accidental client startup observable without using a real session.
  const access = new LmsAccess();
  const connector = createLmsConnector("/synthetic-fixture", "/synthetic-profile", access);
  const release = await access.acquire();
  const abort = new AbortController();
  const queued = connector.callTool("get_assignment_workspace", { assignment_id: "1001" }, { timeout: 1000, signal: abort.signal });
  abort.abort();
  release();
  await assert.rejects(queued, { name: "AbortError" });

  const releaseAgain = await access.acquire();
  const next = connector.callTool("get_assignment_workspace", { assignment_id: "1001" }, { timeout: 1000 });
  connector.close();
  releaseAgain();
  await assert.rejects(next, /종료하고/);
  assert.throws(() => connector.getClient(), /종료하고/);
});
