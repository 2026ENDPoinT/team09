// Run after npm run build: electron tests/assignment-browser-ipc.smoke.mjs --headless
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, dialog, ipcMain } from "electron";
import { registerAssignmentWindows } from "../dist-desktop/desktop/assignment-windows.js";
import { allowedLmsRequest, AssignmentWebSession, browserAddress } from "../dist-desktop/desktop/assignment-web-session.js";
import { registerChatActions } from "../dist-desktop/desktop/chat-controller.js";
import { registerScreenActions } from "../dist-desktop/desktop/screen-controller.js";
import { LmsAccess } from "../dist-desktop/desktop/lms-access.js";
import { createLmsConnector } from "../dist-desktop/desktop/lms-connector.js";
import { ScreenData } from "../dist-desktop/desktop/screen-data.js";
import { saveStudentPreferences } from "../dist-desktop/desktop/student-preferences.js";
import { ACTIVITY_PATH, ATTACHMENT_PREVIEW_PATH, COURSE_ENTRY_PATH, COURSE_NOTICE_PATH, COURSE_PAGE_PATHS, ECLASS_ORIGIN, ECLASS_MAIN_PATH, assignmentUrl, courseNoticeUrl } from "../dist-desktop/shared/assignment-browser.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const profile = mkdtempSync(join(tmpdir(), "ast-assignment-browser-"));
const live = process.env.AST_BROWSER_LIVE === "1";
const pdfNotesOnly = process.argv.includes("--pdf-notes-only");
const account = { key: "a".repeat(64) };
const accountPath = join(profile, "accounts", account.key);
const authPath = live ? join(homedir(), "Library/Application Support/Agent for SeoulTech/lms/auth_state.json") : join(accountPath, "lms", "auth_state.json");
if (!live) mkdirSync(dirname(authPath), { recursive: true });
app.setPath("userData", profile);
app.disableHardwareAcceleration();

const targetA = { courseId: "A-test-a", assignmentId: "1001" };
const targetB = { courseId: "A-test-b", assignmentId: "2001" };
const targetC = { courseId: "A-test-a", assignmentId: "1002" };
const targetD = { courseId: "A-test-b", assignmentId: "2002" };
const legacyAnalysis = "## 기존 제출 안내";
const studyGuide = "## 과제 목표\n\n결과물의 요구 사항을 확인해요.\n\n## 풀이에 필요한 배경지식\n\n배열은 여러 값을 순서대로 담는 자료 구조예요.\n\n## 핵심 개념\n\n먼저 문제의 조건을 정리해요.\n\n## 스스로 풀어보기\n\n1. 가장 작은 예시부터 손으로 풀어봐요.\n\n## 내 풀이 점검\n\n- 같은 값이 반복되는 경우를 확인해요.\n\n## 제출 전 확인\n\n- **제출 형식**을 확인해요.";
if (!live) {
  const directory = join(accountPath, "assignment-analysis");
  const id = createHash("sha256").update(JSON.stringify([targetB.courseId, targetB.assignmentId])).digest("hex");
  mkdirSync(directory, { recursive: true });
  writeFileSync(join(directory, id + ".json"), JSON.stringify({ status: "ready", markdown: legacyAnalysis }));
}
const targets = [targetA, targetB, targetC];
const noticeListUrl = ECLASS_ORIGIN + COURSE_NOTICE_PATH;
const noticeDetailPath = "/ilos/cls/st/notice/notice_view_pop.acl";
const noticeImagePath = "/ilosfiles/editor-file/SYNTHETIC/2026/notice.png";
const courseNotice = { id: "1301", course_id: targetB.courseId, course_name: "다른 테스트 강좌", title: "테스트 수업 공지",
  created_at: new Date().toISOString(), url: noticeListUrl };
const noticeOriginalUrl = courseNoticeUrl(courseNotice.id).href;
const courseNoticeLink = "https://example.test/course-notice";
const backgroundPath = "/ilos/co/activity_continue_update.acl";
const blockedPagePath = "/ilos/cls/st/qna/activity_qna_list_form.acl";
const attendanceListPath = "/ilos/cls/st/attend/attendance_list.acl";
const attendanceWritePath = "/ilos/cls/st/attend/attendance_smart_update.acl";
const lectureUrl = `${ECLASS_ORIGIN}${ACTIVITY_PATH}?m=lecture_weeks&n=701`;
const learningFormPath = "/ilos/cls/st/online/online_learning_form.acl";
const learningFramePath = "/ilos/cls/st/online/online_learning.acl";
const learningSessionPath = "/ilos/cls/st/online/online_view_hisno.acl";
const learningAuthPath = "/ilos/secondauth/session_secondary_auth_check.acl";
const playerScriptPath = "/ilos/player/video-js-7.20.3/video.js";
const subtitlePath = "/ilosfiles/contents-subtitle/10/20/30.vtt";
const timestampWritePath = "/ilos/cls/st/online/online_timestamp_insert.acl";
const previewUrl = ECLASS_ORIGIN + ATTACHMENT_PREVIEW_PATH + "?FPP=fixture";
const viewerUrl = "https://synapv.seoultech.ac.kr/SynapDocViewServer/view/fixture";
const requiredMethods = ["재귀 함수를", "이진 탐색을", "선택 정렬을"];
const assignments = new Map(targets.map((target, index) => [
  target.assignmentId, {
    ...target, title: "테스트 과제 " + (index + 1), courseName: "테스트 강좌 " + target.courseId,
    dueAt: new Date(Date.now() + (index === 0 ? -30 : 7 + index) * 86_400_000).toISOString(),
    submissionMethod: "온라인", submissionFormat: "글 입력 / 파일첨부", publishedAt: "2026-11-09T10:16:00+09:00",
    points: "0점", scoreVisibility: "비공개",
    description: `제출 방법: e-Class에 업로드\n파일 형식: .cpp 파일로 제출\n반드시 ${requiredMethods[index]} 사용해야 합니다.`,
    attachments: [{ id: String(3001 + index), name: `테스트 안내 ${index + 1}.pdf` }],
  },
]));
const textAttachment = { id: "3091", name: "테스트 추가 안내.txt" };
const previewText = "첨부 바로 열기 테스트\n<script>document.body.dataset.executed = 'yes'</script>";
assignments.get(targetA.assignmentId).attachments.push(textAttachment);
function fixturePdf() {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = objects.map((object, index) => {
    const offset = pdf.length;
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
    return offset;
  });
  const xref = pdf.length;
  pdf += "xref\n0 4\n0000000000 65535 f \n";
  for (const offset of offsets) pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  return Buffer.from(pdf + `trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
}
assignments.set(targetD.assignmentId, { ...assignments.get(targetB.assignmentId), ...targetD, title: "테스트 과제 4" });
const mockCalls = [];
const assignmentLookups = [];
const attachmentReads = [];
const attachmentDownloads = [];
const analysisRequests = [];
const summaryLookups = [];
const assignmentChatTools = ["list_assignments", "get_pending_assignments", "get_upcoming_deadlines", "get_assignment_summary", "get_post", "read_attachment"];
const guidanceQuestion = "이 과제 어캐 제출해야함?";
const solveQuestion = "첨부파일 확인해서 풀이 진행해줘.";
const fixtureProblem = "정수 배열을 선택 정렬로 오름차순으로 정렬하세요.";
const fixtureSolution = "매 단계에서 남은 원소 중 최솟값을 찾아 현재 위치의 원소와 바꿔요.";
let manager;
let mainWindow;
let realConnector;
let retryServer;
let savedBrowserLogin = false;
let initialWorkspaceRequested = false;
let initialCourseRequested = false;
let initialAssetRequested = false;
let nextWorkspaceReply;
let blockedRequestsReachedServer = 0;
let finishInitialWorkspace;
let finishInitialCourse;
let finishInitialAsset;
let finishInitialAnalysis;
const initialWorkspace = new Promise((resolve) => { finishInitialWorkspace = resolve; });
const initialCourse = new Promise((resolve) => { finishInitialCourse = resolve; });
const initialAsset = new Promise((resolve) => { finishInitialAsset = resolve; });
const initialAnalysis = new Promise((resolve) => { finishInitialAnalysis = resolve; });
const waitFor = async (check, label, timeout = 7_000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await new Promise((resolve) => setTimeout(resolve, 45));
  }
  throw new Error("Timed out: " + label);
};
const run = (win, code) => win.webContents.executeJavaScript(code);
const viewOf = (win) => win.contentView.children.find((child) => child.webContents && child.webContents !== win.webContents);
const assignmentWindows = () => BrowserWindow.getAllWindows().filter((win) => win !== mainWindow);
const browserState = (win) => run(win, "window.assignmentBrowser?.getAssignmentBrowser()");
const command = (win, value) => run(win, `window.assignmentBrowser.commandAssignmentBrowser(${JSON.stringify(value)})`);
const navigate = (win, url) => run(win, `window.assignmentBrowser.navigateAssignmentBrowser(${JSON.stringify(url)})`);
const openChat = (win) => run(win, "document.querySelector('.assignment-chat-orb[aria-expanded=false]')?.click()");
const send = async (win, question) => {
  await openChat(win);
  await waitFor(() => run(win, "!!document.querySelector('.chat-composer textarea')"), "chat composer is mounted");
  await run(win, `(() => {
    const el = document.querySelector('.chat-composer textarea');
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, ${JSON.stringify(question)});
    el.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await waitFor(() => run(win, "!!document.querySelector('.chat-composer button[type=submit]:enabled')"), "chat enabled");
  await run(win, "document.querySelector('.chat-composer').requestSubmit()");
};
const overview = { status: "ok", overview: { regular: 0, non_regular: 0, courses: [] } };
const mockTool = async (name, args) => {
  if (name === "get_assignment_attachment_file") {
    attachmentDownloads.push(args);
    const assignment = assignments.get(args.assignment_id);
    assert.equal(args.course_id, assignment?.courseId);
    const file = assignment.attachments.find(({ id }) => id === args.attachment_id);
    assert.ok(file);
    const text = file === textAttachment;
    const bytes = text ? Buffer.from(previewText) : fixturePdf();
    return { ...args, status: "ok", name: file.name, mime: text ? "text/plain" : "application/pdf", size_bytes: bytes.length, base64: bytes.toString("base64") };
  }
  if (name === "get_assignment_workspace") {
    assignmentLookups.push(name);
    if (args.assignment_id === targetA.assignmentId && !initialWorkspaceRequested) {
      initialWorkspaceRequested = true;
      await initialWorkspace;
    }
    const assignment = assignments.get(args.assignment_id);
    if (nextWorkspaceReply?.assignmentId === args.assignment_id) {
      const { respond } = nextWorkspaceReply;
      nextWorkspaceReply = undefined;
      return respond();
    }
    if (assignment && (!args.course_id || args.course_id === assignment.courseId)) return { status: "ok", assignment };
    return { status: "error", message: "테스트 과제 없음" };
  }
  if (name === "confirm_browser_login") {
    savedBrowserLogin = args.login_id === "fixture-student" &&
      args.cookies.some(({ name, value }) => name === "fixture_login" && value === "fixture-renewed-session");
    return savedBrowserLogin ? { status: "authenticated", message: "테스트 로그인", account_key: account.key }
      : { status: "login_required", message: "테스트 로그인" };
  }
  if (name === "get_course_overview") return overview;
  if (name === "get_course_notice" && args.course_id === courseNotice.course_id && args.notice_id === courseNotice.id) return {
    body_html: `<p>테스트 공지 본문</p><a href="${courseNoticeLink}">공지 본문 신청 링크</a><button type="button" class="course-notice-image-source">본문 이미지 · e-Class에서 확인 ↗</button>`,
    attachments: [{ id: "4201", name: "테스트 공지 첨부.pdf" }],
  };
  if (name === "get_course_briefing") return {
    as_of: "2026-11-12T12:00:00+09:00", completed_assignments: [], recent_notices: [courseNotice],
    pending_assignments: [{ id: targetA.assignmentId, course_id: targetA.courseId, course_name: "테스트 강좌",
      title: "테스트 과제 1", submitted: false, due_at: null }],
  };
  if (name === "get_campus_briefing") return { as_of: "2026-11-12T12:00:00+09:00", notices: [] };
  return { status: "error", message: "테스트에서 사용하지 않는 도구" };
};

async function main() {
  try {
    await app.whenReady();
    app.dock?.hide();
    app.on("window-all-closed", () => {});
    const access = new LmsAccess();
    assert.equal(browserAddress("javascript:alert(1)"), undefined);
    assert.equal(browserAddress("file:///tmp/fixture"), undefined);
    assert.equal(allowedLmsRequest(new URL(ECLASS_ORIGIN + "/ilos/cls/st/report/report_submit.acl"), "POST", "xhr"), false);
    assert.equal(allowedLmsRequest(new URL(ECLASS_ORIGIN + "/ilos/cls/st/discuss/discuss_detail_delete.acl"), "GET", "mainFrame"), false);
    assert.equal(allowedLmsRequest(new URL(ECLASS_ORIGIN + noticeImagePath), "GET", "mainFrame"), false);
    assert.equal(allowedLmsRequest(new URL(ECLASS_ORIGIN + noticeImagePath), "GET", "image"), true);
    const web = new AssignmentWebSession(access, "ast-assignment-browser-test");
    let connector;
    if (live) {
      realConnector = createLmsConnector(root, dirname(authPath), access);
      connector = realConnector;
    } else {
      const fixtureCookies = [{ name: "fixture_login", value: "fixture-session", domain: "eclass.seoultech.ac.kr", path: "/", expires: -1 }];
      writeFileSync(authPath, JSON.stringify({ cookies: fixtureCookies }), { mode: 0o600 });
      connector = {
        access, requestTool: mockTool,
        getClient: async () => ({ listTools: async () => ({ tools: assignmentChatTools.map((name) => ({
          name, inputSchema: { type: "object", properties: {} },
        })) }) }),
        callTool: async (name, args) => {
          assignmentLookups.push(name);
          if (name === "read_attachment") {
            attachmentReads.push(args);
            assert.equal(args.kind, "assignment");
            const item = assignments.get(args.post_id);
            assert.equal(args.course_id, item?.courseId);
            const attachment = item.attachments.find(({ id }) => id === args.attachment_id);
            assert.ok(attachment, "only a verified attachment from the current assignment is read");
            return { structuredContent: { filename: attachment.name, pages: [fixtureProblem], next_page: null, truncated: false } };
          }
          if (name === "get_post") {
            const item = assignments.get(args.post_id);
            assert.equal(item?.courseId, args.course_id);
            return { structuredContent: { kind: "assignment", title: item.title, content: item.description } };
          }
          assert.equal(name, "get_assignment_summary");
          summaryLookups.push(args);
          return { structuredContent: { status: "ok", as_of: new Date().toISOString(), assignments: [{ id: targetB.assignmentId, course_id: targetB.courseId,
            title: "테스트 과제 2", due_at: assignments.get(targetB.assignmentId).dueAt, submitted: false,
            url: assignmentUrl(targetB.assignmentId) }] } };
        },
      };
      let serverCourse;
      web.session.protocol.handle("https", async (request) => {
        const url = new URL(request.url);
        if ([backgroundPath, blockedPagePath, attendanceWritePath, timestampWritePath].includes(url.pathname)) {
          blockedRequestsReachedServer++;
          return new Response("This route should be blocked");
        }
        if (url.href === "https://example.test/loading-probe.js") {
          initialAssetRequested = true;
          await initialAsset;
          return new Response("", { headers: { "content-type": "text/javascript" } });
        }
        if (url.hostname === "example.test") return new Response(
          '<input type="file" aria-label="테스트 파일"><a href="https://example.test/next">다음</a>',
          { headers: { "content-type": "text/html" } });
        if (url.pathname === COURSE_ENTRY_PATH) {
          serverCourse = new URLSearchParams(await request.text()).get("KJKEY");
          mockCalls.push(["enter", serverCourse]);
          if (!initialCourseRequested) {
            initialCourseRequested = true;
            await initialCourse;
          }
          return Response.json({ isError: false });
        }
        if (url.href === lectureUrl) {
          return new Response(`<form id="watch-form" method="post" action="${learningFormPath}">
            <input name="_KJKEY" type="hidden" value="${serverCourse}"><button type="button" id="watch">영상</button>
            </form><script>
              document.getElementById('watch').onclick = async () => {
                if (confirm('출석 인정 기간이 지났어요. 계속 볼까요?')) {
                  const auth = await fetch('${learningAuthPath}', {method: 'POST'});
                  if (auth.ok) document.getElementById('watch-form').submit();
                }
              };
            </script>`, { headers: { "content-type": "text/html; charset=utf-8" } });
        }
        if (url.pathname === learningFormPath && request.method === "POST") {
          const course = new URLSearchParams(await request.text()).get("_KJKEY");
          if (course !== targetB.courseId || course !== serverCourse) return new Response("wrong course", { status: 403 });
          return new Response(`<script src="${playerScriptPath}"></script><script>
            fetch('${learningSessionPath}', {method: 'POST'}).then(response => {
              if (response.ok && window.playerScriptLoaded) {
                const frame = document.createElement('iframe');
                frame.src = '${learningFramePath}';
                document.body.append(frame);
              }
            });
          </script>`, { headers: { "content-type": "text/html; charset=utf-8" } });
        }
        if (url.pathname === learningAuthPath && request.method === "POST") return Response.json({ isError: false });
        if (url.pathname === learningSessionPath && request.method === "POST" && serverCourse === targetB.courseId) {
          return Response.json({ isError: false });
        }
        if (url.pathname === playerScriptPath) return new Response("window.playerScriptLoaded = true;", { headers: { "content-type": "text/javascript" } });
        if (url.pathname === learningFramePath && serverCourse === targetB.courseId) {
          return new Response(`<body><video></video><script>
            fetch('${subtitlePath}').then(response => { if (response.ok) document.body.dataset.subtitles = 'ready'; });
            fetch('${timestampWritePath}', {method: 'POST'}).catch(() => { document.body.dataset.write = 'blocked'; });
          </script></body>`, { headers: { "content-type": "text/html" } });
        }
        if (url.pathname === subtitlePath) return new Response("WEBVTT\n\n", { headers: { "content-type": "text/vtt" } });
        if (url.pathname === ACTIVITY_PATH) {
          const item = assignments.get(url.searchParams.get("n"));
          mockCalls.push(["view", serverCourse, item?.assignmentId]);
          if (!item || item.courseId !== serverCourse) return new Response("wrong course", { status: 403 });
          const link = assignmentUrl(targetC.assignmentId);
          const pendingAsset = item.assignmentId === targetA.assignmentId ? '<script async src="https://example.test/loading-probe.js"></script>' : "";
          return new Response(`<h1>${item.title}</h1><a href="${link}">다른 과제</a>
            <a id="preview" href="${previewUrl}" target="_blank">미리보기</a>
            <a id="external" href="https://example.test/next" target="_blank">새 탭 링크</a>
            <p style="height:1000px">테스트 페이지</p>${pendingAsset}
            <script>fetch('${backgroundPath}', { method: 'POST' })
              .then(() => { document.body.dataset.background = 'allowed'; }, () => { document.body.dataset.background = 'blocked'; });</script>`,
            { headers: { "content-type": "text/html; charset=utf-8" } });
        }
        if (url.href === previewUrl && request.method === "GET" && serverCourse === targetA.courseId) return Response.redirect(viewerUrl);
        if (url.href === viewerUrl) return new Response("<title>문서 미리보기</title><h1>테스트 문서</h1>",
          { headers: { "content-type": "text/html; charset=utf-8" } });
        if (url.pathname === COURSE_NOTICE_PATH) {
          const cookies = await web.session.cookies.get({ url: ECLASS_ORIGIN, name: "fixture_login" });
          if (serverCourse !== courseNotice.course_id || cookies[0]?.value !== "fixture-session") {
            return Response.redirect(ECLASS_ORIGIN + "/ilos/main/member/login_form.acl");
          }
          mockCalls.push(["notice", serverCourse]);
          return new Response(`<h1>테스트 강좌 공지 목록</h1><div id="notice_view_pop"></div><script>
            function noticeViewPop(id) {
              const request = new XMLHttpRequest();
              request.open('POST', ${JSON.stringify(noticeDetailPath)}, false);
              request.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
              request.send(new URLSearchParams({ ARTL_NUM: id, encoding: 'utf-8' }).toString());
              if (request.status === 200) document.getElementById('notice_view_pop').innerHTML = request.responseText;
            }
          </script>`, { headers: { "content-type": "text/html; charset=utf-8" } });
        }
        if (url.pathname === noticeDetailPath && request.method === "POST") {
          const id = new URLSearchParams(await request.text()).get("ARTL_NUM");
          mockCalls.push(["notice-detail", serverCourse, id]);
          if (serverCourse !== courseNotice.course_id || id !== courseNotice.id) return new Response("wrong notice", { status: 404 });
          return new Response('<article class="editor_content">테스트 공지 원문</article>', { headers: { "content-type": "text/html; charset=utf-8" } });
        }
        if (url.pathname === COURSE_PAGE_PATHS.attendance) {
          mockCalls.push(["attendance", serverCourse]);
          return new Response(`<h1>테스트 출석</h1><p id="attendance"></p><script>
            fetch('${attendanceListPath}', { method: 'POST' }).then(response => response.text())
              .then(text => { document.getElementById('attendance').textContent = text; });
            fetch('${attendanceWritePath}', { method: 'POST' }).catch(() => { document.body.dataset.write = 'blocked'; });
          </script>`, { headers: { "content-type": "text/html; charset=utf-8" } });
        }
        if (url.pathname === attendanceListPath && request.method === "POST") return new Response(serverCourse);
        if (url.pathname.endsWith("/login_form.acl")) return new Response(
          `<form method="post" action="${ECLASS_ORIGIN}/ilos/lo/login.acl"><input type="hidden" name="usr_id" value="fixture-student"><button>테스트 로그인</button></form>`,
          { headers: { "content-type": "text/html" } });
        if (url.pathname === "/ilos/lo/login.acl") {
          // Model the cookie issued by a successful server login (no real credentials).
          await web.session.cookies.set({ url: ECLASS_ORIGIN, name: "fixture_login", value: "fixture-renewed-session", path: "/", secure: true, httpOnly: true });
          return new Response(null, { status: 303, headers: { location: ECLASS_ORIGIN + ECLASS_MAIN_PATH,
            "set-cookie": "fixture_login=fixture-renewed-session; Path=/; Secure; HttpOnly" } });
        }
        if (url.pathname === ECLASS_MAIN_PATH) return new Response(`
          <h1>테스트 수강과목</h1><div id="progress">불러오는 중</div>
          <script>
            fetch('/ilos/main/main_lecture_progress_view.acl', { method: 'POST' })
              .then(response => response.text())
              .then(progress => { document.getElementById('progress').textContent = progress; });
          </script>`, { headers: { "content-type": "text/html" } });
        if (request.method === "POST" && url.pathname === "/ilos/main/main_lecture_progress_view.acl") {
          return new Response("진행 주 11 / 16 주");
        }
        return new Response("unknown", { status: 404 });
      });
      globalThis.fetch = async (_url, init) => {
        const body = JSON.parse(init.body);
        const pdfEvidence = body.input.find(({ content }) => typeof content === "string" && content.startsWith("저장된 PDF 참고 자료\n"));
        const userMessages = body.input.filter(({ role }) => role === "user").filter((item) => item !== pdfEvidence);
        const current = userMessages.at(-1).content;
        const reference = userMessages.at(-2)?.content;
        const referenceLabel = "현재 과제 참고 자료\n";
        let output;
        if (typeof reference === "string" && reference.startsWith(referenceLabel)) {
          const data = JSON.parse(reference.slice(referenceLabel.length));
          const expected = assignments.get(data.assignmentId);
          assert.ok(expected, "the model receives the open assignment even after its deadline");
          for (const key of ["assignmentId", "courseId", "title", "courseName", "description", "dueAt", "attachments"]) {
            assert.deepEqual(data[key], expected[key]);
          }
          const number = targets.findIndex(({ assignmentId }) => assignmentId === expected.assignmentId) + 1;
          assert.ok(!body.instructions.includes(expected.description.split("\n").at(-1)));
          const fileOutput = body.input.find(({ type }) => type === "function_call_output");
          if (current === guidanceQuestion || current === "응" || current === solveQuestion) {
            assert.equal(data.assignmentId, targetC.assignmentId);
            assert.ok(body.tools.some(({ name }) => name === "open_assignment_pdf"));
            assert.match(pdfEvidence?.content ?? "", /선택 정렬로 오름차순/);
            if (current === "응" || current === solveQuestion) {
              assert.match(body.instructions, /현재 과제의 풀이/);
              assert.ok(userMessages.slice(0, -2).some(({ content }) => content === guidanceQuestion));
              assert.match(pdfEvidence?.content ?? "", /선택 정렬로 오름차순/);
            }
            assert.equal(fileOutput, undefined, "saved PDF notes are enough for the guidance and follow-up");
            const text = current === "응" || current === solveQuestion ? fixtureSolution : JSON.stringify({
              answer: "선택 정렬을 사용해 코드를 작성하고 예제로 확인한 다음, .cpp 파일을 e-Class에 올려요.", can_offer_solution: true,
            });
            output = [{ type: "message", role: "assistant", content: [{ type: "output_text", text }] }];
            return Response.json({ status: "completed", output });
          }
          assert.ok(body.tools.every(({ name }) => ["read_attachment", "open_assignment_pdf"].includes(name)));
          assert.equal(fileOutput, undefined);
          if (current === "그럼 반드시 써야 해?") {
            assert.ok(userMessages.slice(0, -2).some(({ content }) => content === "제출 조건을 정리해줘"));
          }
          if ((number === 2 && current !== "이거 과제 어려워보여?") || number === 3) assert.deepEqual(userMessages.slice(0, -2), []);
          const answer = current === "이거 과제 어려워보여?" ? (
            assert.match(pdfEvidence?.content ?? "", /도식에서 두 항목의 흐름이 보여요/),
            "PDF 1쪽 기준으로 난이도는 중간이에요."
          ) : `과제 ${number} 답변. ${data.description.split("\n").at(-1)} 마감 ${data.dueAt}. 첨부 ${data.attachments[0].name}.`;
          const text = body.text?.format ? JSON.stringify({ answer, can_offer_solution: false }) : answer;
          output = [{ type: "message", role: "assistant", content: [{ type: "output_text", text }] }];
        } else {
          assert.fail("The main-window assignment summary must not call the model");
        }
        return Response.json({ status: "completed", output });
      };
    }

    const verifyMain = (event) => assert.equal(event.senderFrame, mainWindow.webContents.mainFrame);
    const screenData = new ScreenData(mockTool, () => manager?.sessionChanged());
    const windowOptions = {
      rendererPath: join(root, "dist/assignment-browser.html"), preload: join(root, "dist-desktop/desktop/preload.cjs"),
      ...(live ? { authPath } : { activeDirectory: () => screenData.account && accountPath }),
      apiKey: live ? "" : "fixture-no-real-key", connector, screenData, verifyMain, web, show: false,
      analysisFetch: async (url, init) => {
        assert.equal(url, "https://api.openai.com/v1/responses");
        const request = JSON.parse(init.body);
        assert.equal(request.store, false);
        assert.equal(request.stream, true);
        const [instructions, file] = request.input[0].content;
        const metadata = JSON.parse(instructions.text);
        const assignment = [...assignments.values()].find(({ title }) => title === metadata.title);
        assert.ok(assignment);
        assert.equal(metadata.instructorDescription, assignment.description);
        for (const key of ["dueAt", "publishedAt", "submissionMethod", "submissionFormat", "points", "scoreVisibility"]) {
          assert.equal(metadata[key], assignment[key]);
        }
        assert.deepEqual(metadata.pdfSources.map(({ originalName }) => originalName), [assignment.attachments[0].name]);
        assert.equal(file.type, "input_file");
        assert.equal(file.file_data, `data:application/pdf;base64,${fixturePdf().toString("base64")}`);
        analysisRequests.push(assignment.assignmentId);
        const text = JSON.stringify({ markdown: studyGuide, documents: [{
          inputFile: metadata.pdfSources[0].inputFile, overview: "테스트 PDF 기초", coverage: "complete",
          sections: [{ from: 1, to: 1, text: assignment.assignmentId === targetC.assignmentId ? fixtureProblem : assignment.description,
            visuals: "도식에서 두 항목의 흐름이 보여요." }],
        }] });
        const response = { status: "completed", output: [{ type: "message", content: [{ type: "output_text", text }] }] };
        if (assignment.assignmentId !== targetA.assignmentId) return Response.json(response);

        const encoder = new TextEncoder();
        return new Response(new ReadableStream({
          async start(controller) {
            const push = (event) => controller.enqueue(encoder.encode("data: " + JSON.stringify(event) + "\n\n"));
            const split = text.indexOf("## 핵심 개념");
            push({ type: "response.output_text.delta", delta: text.slice(0, split) });
            await initialAnalysis;
            push({ type: "response.output_text.delta", delta: text.slice(split) });
            push({ type: "response.completed", response });
            controller.close();
          },
        }), { headers: { "Content-Type": "text/event-stream" } });
      },
    };
    manager = registerAssignmentWindows(windowOptions);
    registerChatActions({
      apiKey: "fixture-no-real-key", getClient: connector.getClient, callTool: connector.callTool,
      window: () => mainWindow, verifySender: verifyMain, confirmedLmsSession: () => screenData.confirmedSessionRevision,
      otherChat: manager.chat, openAssignment: manager.open, openBrowser: manager.openBrowser, openCourseNotice: manager.openCourseNotice,
    });
    registerScreenActions(screenData, connector.requestTool, verifyMain, undefined, undefined, manager.openCourseNoticeLink, manager.openCoursePage, manager.openBrowser);
    screenData.warm(live ? undefined : account);
    if (live) {
      const courses = (await (await connector.getClient()).callTool({ name: "list_courses", arguments: {} })).structuredContent.result;
      const course = courses.find(({ name }) => name.replaceAll(" ", "").includes("프로그래밍입문(2)"));
      assert.ok(course, "fixture target course available");
      const posts = (await connector.callTool("list_posts", { kind: "assignment", course_id: course.id }, { timeout: 25_000 })).structuredContent.result;
      const post = posts.find(({ title }) => title.includes("10주차"));
      assert.ok(post, "fixture target assignment available");
      await manager.open({ courseId: course.id, assignmentId: post.id });
      const win = assignmentWindows()[0];
      try {
        await waitFor(async () => (await browserState(win))?.assignmentState === "ready", "real assignment and panel", 50_000);
        const actual = await viewOf(win).webContents.executeJavaScript(`({
          main: location.origin === ${JSON.stringify(ECLASS_ORIGIN)},
          assignment: new URL(location.href).searchParams.get('m') === 'report',
          rendered: !!document.querySelector('.view_title, .activity_title, #submit_form'),
          noBridge: window.ast === undefined
        })`);
        assert.deepEqual(actual, { main: true, assignment: true, rendered: true, noBridge: true });
        assert.equal((await browserState(win)).assignment.assignmentId, post.id);
        console.log("PASS: real e-Class assignment page and verified assignment panel opened using the saved session");
      } catch (error) {
        const state = await browserState(win);
        const view = viewOf(win);
        console.error("LIVE STATUS", state?.assignmentState, state?.assignmentMessage, state?.error,
          "VIEW", view && new URL(view.webContents.getURL() || "about:blank").pathname);
        throw error;
      }
      return;
    }

    mainWindow = new BrowserWindow({ show: false, webPreferences: {
      preload: join(root, "dist-desktop/desktop/preload.cjs"), sandbox: true, contextIsolation: true, nodeIntegration: false,
    } });
    await saveStudentPreferences({ residence: "none", departmentId: "computer" });
    await mainWindow.loadFile(join(root, "dist/index.html"));
    await waitFor(() => run(mainWindow, "document.querySelector('.ast-entry-shell')?.dataset.entry === 'open'"), "workspace restored from verified fixture session");
    assert.equal(manager.openBrowser(), true);
    const blank = await waitFor(() => assignmentWindows()[0], "empty AST browser window");
    await waitFor(async () => (await browserState(blank))?.initialLoad === false, "blank address field is ready");
    assert.equal(await run(blank, "document.querySelector('.assignment-address-preview').disabled"), false);
    blank.destroy();
    assert.equal(manager.openBrowser(new URL("https://example.test/files")), true);
    const external = await waitFor(() => assignmentWindows()[0], "AST browser window for an ordinary URL");
    await waitFor(async () => (await browserState(external))?.url === "https://example.test/files" &&
      !((await browserState(external))?.loading), "ordinary URL loaded in AST");
    assert.equal(await viewOf(external).webContents.executeJavaScript("location.hostname"), "example.test");
    assert.equal(await run(external, "document.querySelector('.assignment-summary') === null"), true);
    external.destroy();
    await run(mainWindow, "document.querySelector('.sketch-deadlines .sketch-link').click()");
    await waitFor(() => run(mainWindow, "!!document.querySelector('.briefing-assignment-link')"), "briefing assignment link");
    await run(mainWindow, "document.querySelector('.briefing-assignment-link').click()");
    const first = await waitFor(() => assignmentWindows()[0], "first assignment window");
    await waitFor(() => initialCourseRequested, "course selection starts before assignment analysis");
    assert.equal(initialWorkspaceRequested, false);
    assert.equal(initialAssetRequested, false);
    finishInitialCourse();
    await waitFor(() => initialAssetRequested, "initial page is waiting on an asset");
    const site = viewOf(first);
    const overlay = first.contentView.children.at(-1);
    assert.notEqual(overlay, site, "the loading surface is above the website");
    const overlayContents = overlay.webContents;
    await waitFor(() => overlayContents.getURL().endsWith("/web-loading/index.html") && overlay.getBounds().width > 0, "loading screen is in place");
    assert.deepEqual(overlay.getBounds(), site.getBounds());
    assert.equal((await browserState(first)).initialLoad, true);
    const [revealing, spriteUrl, duration, timing, background, ink, markHeight] = await overlayContents.executeJavaScript(`(() => {
      const screen = document.querySelector('.web-loading-screen');
      const mark = document.querySelector('.web-loading-mark');
      const style = getComputedStyle(mark);
      const markBounds = mark.getBoundingClientRect();
      const screenBounds = screen.getBoundingClientRect();
      return [screen.classList.contains('is-revealing'), style.maskImage.slice(5, -2),
        style.animationDuration, style.animationTimingFunction, getComputedStyle(screen).backgroundColor, style.color,
        (screenBounds.bottom - markBounds.top - markBounds.height / 2) / screenBounds.height];
    })()`);
    assert.equal(revealing, false);
    assert.match(spriteUrl, /ast-wordmark-[\w-]+\.png$/);
    assert.equal(duration, "1.1s");
    assert.equal(timing, "steps(11)");
    assert.equal(background, "rgba(255, 255, 255, 0.95)");
    assert.equal(ink, "rgb(38, 50, 47)");
    assert.ok(Math.abs(markHeight - .7) < .002, "the logo is centered at 70% from the bottom");
    const glowMoves = await overlayContents.executeJavaScript(`(() => {
      const screen = document.querySelector('.web-loading-screen');
      const glow = screen.getAnimations({ subtree: true }).find((animation) => animation.animationName === 'web-loading-glow');
      if (!glow || glow.playState !== 'running' || glow.effect.getTiming().iterations !== Infinity) return false;
      // Seek explicitly because hidden Electron windows may not advance compositor frames.
      glow.pause();
      glow.currentTime = 0;
      const start = getComputedStyle(screen, '::before').transform;
      glow.currentTime = glow.effect.getTiming().duration;
      const end = getComputedStyle(screen, '::before').transform;
      glow.currentTime = 0;
      glow.play();
      return start !== 'none' && start !== end;
    })()`);
    assert.equal(glowMoves, true, "the background glow changes position and repeats during loading");
    assert.equal(initialWorkspaceRequested, false, "assignment analysis does not delay loading the page");
    finishInitialAsset();
    await waitFor(() => initialWorkspaceRequested, "panel begins its lookup after the page loads");
    assert.equal(await overlayContents.executeJavaScript("getComputedStyle(document.querySelector('.web-loading-screen')).maskImage.startsWith('linear-gradient(135deg')"), true);
    await waitFor(() => overlayContents.isDestroyed(), "reveal removes the overlay and releases website input");
    const pendingPanel = await browserState(first);
    assert.equal(pendingPanel.assignmentState, "loading");
    assert.equal(pendingPanel.assignment, null);
    assert.equal(await site.webContents.executeJavaScript("document.querySelector('h1')?.textContent"), assignments.get(targetA.assignmentId).title);
    assert.equal(pendingPanel.url, assignmentUrl(targetA.assignmentId));
    assert.equal(first.contentView.children.at(-1), site);
    finishInitialWorkspace();
    await waitFor(async () => (await browserState(first))?.assignment?.assignmentId === targetA.assignmentId, "first verified assignment fills the panel");
    await waitFor(() => site.webContents.executeJavaScript("document.body.dataset.background === 'blocked'"), "background POST stays blocked");
    assert.equal((await browserState(first)).error, null, "a background block does not set a navigation error");
    assert.equal(await run(first, "!!document.querySelector('.assignment-browser-status')"), false);
    assert.equal(blockedRequestsReachedServer, 0);
    await waitFor(() => analysisRequests.includes(targetA.assignmentId), "PDF is analyzed in the background");
    assert.equal((await browserState(first)).analysis.status, "loading");
    const submission = await run(first, "document.querySelector('.assignment-summary-header').innerText");
    assert.match(submission, /마감일.*제출 방식\s*온라인.*제출 형태\s*글 입력 \/ 파일첨부/s);
    assert.doesNotMatch(submission, /공개일|배점|점수 공개/);
    assert.match(submission, /테스트 안내 1\.pdf/);
    const instructorDetails = ".assignment-instructor";
    assert.equal(await run(first, `document.querySelector('${instructorDetails}').open`), false);
    assert.equal(await run(first, "document.querySelector('.assignment-summary-header').nextElementSibling.matches('.assignment-analysis')"), true);
    await run(first, `document.querySelector('${instructorDetails} summary').click()`);
    const professorInfo = await run(first, `document.querySelector('${instructorDetails}').innerText`);
    assert.match(professorInfo, /공개일.*배점\s*0점.*점수 공개\s*비공개/s);
    assert.match(professorInfo, /파일 형식.*\.cpp/);
    await run(first, `document.querySelector('${instructorDetails} summary').click()`);
    const initialWebWidth = site.getBounds().width;
    assert.ok(initialWebWidth > 0 && initialWebWidth < first.getContentSize()[0] / 3, "the LMS view is a narrow left column");
    const explanationFillsPane = () => run(first, `(() => {
      const panel = document.querySelector('.assignment-side').getBoundingClientRect();
      const divider = document.querySelector('.assignment-divider').getBoundingClientRect();
      const scroll = document.querySelector('.assignment-explanation-scroll');
      const card = document.querySelector('.assignment-info-card').getBoundingClientRect();
      return Math.abs(panel.left - divider.right) < 1 && Math.abs(panel.right - innerWidth) < 1 &&
        Math.abs(scroll.clientHeight - panel.height) < 1 && scroll.scrollWidth <= scroll.clientWidth &&
        scroll.clientWidth - card.width <= 56;
    })()`);
    assert.equal(await explanationFillsPane(), true, "the explanation and its card fill the right pane with only the intended inset");
    await waitFor(() => run(first, "document.querySelector('.assignment-analysis-markdown h3')?.textContent === '과제 목표'"),
      "the first Markdown section appears before the response completes");
    assert.equal((await browserState(first)).analysis.status, "loading");
    assert.equal(await run(first, "document.querySelector('.assignment-analysis-markdown').getAttribute('aria-busy')"), "true");
    finishInitialAnalysis();
    await waitFor(() => run(first, "document.querySelector('.assignment-analysis-markdown').getAttribute('aria-busy') === 'false'"),
      "the completed PDF study guide replaces the streamed text");
    assert.deepEqual(await run(first, "[...document.querySelectorAll('.assignment-analysis-markdown h3')].map(({textContent}) => textContent)"),
      ["과제 목표", "풀이에 필요한 배경지식", "핵심 개념", "스스로 풀어보기", "내 풀이 점검", "제출 전 확인"]);
    const analysisFontSize = "getComputedStyle(document.querySelector('.assignment-analysis-markdown .chat-answer-text')).fontSize";
    assert.equal(await run(first, analysisFontSize), "15px");
    await run(mainWindow, "document.querySelector('.ast-other-nav button:last-child').click()");
    const fontControl = "document.querySelector('#assignment-font-size')";
    await waitFor(() => run(mainWindow, `${fontControl}?.value === '15' && !${fontControl}.disabled`), "the Settings page shows the default assignment font");
    await run(mainWindow, `(() => {
      const select = ${fontControl};
      select.value = '19';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await waitFor(async () => await run(first, analysisFontSize) === "19px", "saving the font updates the already open explanation");
    assert.deepEqual(JSON.parse(readFileSync(join(accountPath, "assignment-appearance.json"), "utf8")), { fontSize: 19 });
    await run(mainWindow, `[...document.querySelectorAll('.app-nav button')].find(({ textContent }) => textContent.trim() === '홈 화면').click()`);
    await waitFor(() => run(mainWindow, "!!document.querySelector('.sketch-deadlines .sketch-link')"), "return to the dashboard");
    await run(mainWindow, "document.querySelector('.sketch-deadlines .sketch-link').click()");
    await waitFor(() => run(mainWindow, "!!document.querySelector('.briefing-assignment-link')"), "return to the briefing assignment link");
    assert.equal(await viewOf(first).webContents.executeJavaScript("window.ast === undefined && typeof require === 'undefined'"), true);
    await run(mainWindow, "document.querySelector('.briefing-assignment-link').click()");
    assert.equal(assignmentWindows().length, 1);

    const originalTab = (await browserState(first)).activeTabId;
    const initialAssignmentVisits = mockCalls.filter(([kind, , id]) => kind === "view" && id === targetA.assignmentId).length;
    const downloadsBeforeUnverified = attachmentDownloads.length;
    assert.equal((await run(first, `window.assignmentBrowser.openAssignmentAttachment(${originalTab}, "${targetA.courseId}", "${targetA.assignmentId}", "unverified")`)).status, "error");
    assert.equal(attachmentDownloads.length, downloadsBeforeUnverified);
    const clickTab = (id) => run(first, `document.querySelectorAll('.assignment-tab-select')[${id}].click()`);
    await site.webContents.executeJavaScript("document.querySelector('#preview').click()");
    await waitFor(async () => {
      const state = await browserState(first);
      return state?.url === viewerUrl && !state.loading && state.tabs.some(({ title }) => title === "문서 미리보기");
    }, "attachment popup follows the viewer redirect in a new tab");
    const preview = await browserState(first);
    assert.equal(preview.tabs.length, 2);
    assert.equal(preview.assignmentState, "none");
    assert.equal(assignmentWindows().length, 1);
    await clickTab(0);
    await waitFor(async () => (await browserState(first))?.activeTabId === originalTab, "the original assignment tab is selectable");
    assert.equal((await browserState(first)).assignment?.assignmentId, targetA.assignmentId);
    await site.webContents.executeJavaScript("document.querySelector('#external').click()");
    await waitFor(async () => (await browserState(first))?.tabs.length === 3, "multiple links retain independent tabs");
    await clickTab(1);
    assert.equal((await browserState(first)).url, viewerUrl);
    await run(first, "document.querySelectorAll('.assignment-tab-close')[2].click()");
    await waitFor(async () => (await browserState(first))?.tabs.length === 2, "an inactive tab can be closed");
    await run(first, "document.querySelectorAll('.assignment-tab-close')[1].click()");
    await waitFor(async () => (await browserState(first))?.activeTabId === originalTab, "closing the active preview restores the assignment tab");

    await run(mainWindow, "document.querySelector('.briefing-course-notice summary').click()");
    await waitFor(() => run(mainWindow, "!!document.querySelector('.briefing-course-notice .course-notice-files button')"), "course notice attachment action");
    await run(mainWindow, "document.querySelector('.briefing-course-notice .course-notice-files button').click()");
    const noticeWindow = await waitFor(() => assignmentWindows().find((win) => win !== first), "course notice opens in AST");
    await waitFor(async () => (await browserState(noticeWindow))?.url === noticeOriginalUrl &&
      !(await browserState(noticeWindow)).initialLoad, "course notice finishes loading");
    assert.equal(viewOf(noticeWindow).webContents.session, viewOf(first).webContents.session);
    assert.deepEqual(mockCalls.slice(-3), [["enter", targetB.courseId], ["notice", targetB.courseId], ["notice-detail", targetB.courseId, courseNotice.id]]);
    assert.equal(await viewOf(noticeWindow).webContents.executeJavaScript("document.querySelector('#notice_view_pop .editor_content')?.textContent"), "테스트 공지 원문");
    assert.equal(await run(noticeWindow, "!!document.querySelector('.assignment-side')"), false);
    await viewOf(noticeWindow).webContents.executeJavaScript("document.querySelector('#notice_view_pop').replaceChildren()");
    await run(mainWindow, "document.querySelector('.course-notice-image-source').click()");
    await waitFor(() => viewOf(noticeWindow).webContents.executeJavaScript("!!document.querySelector('#notice_view_pop .editor_content')"), "the image fallback reopens the same notice");
    assert.equal(assignmentWindows().length, 2);
    assert.equal(await run(mainWindow, `window.ast.openCourseNoticeOriginal('${targetB.courseId}', '999999')`), false);
    assert.equal(await run(mainWindow, `window.ast.openCourseNoticeLink('${targetB.courseId}', '${noticeOriginalUrl}')`), true);
    assert.equal(await run(mainWindow, `window.ast.openCourseNoticeLink(${JSON.stringify(targetB.courseId)}, ${JSON.stringify(ECLASS_ORIGIN + backgroundPath)})`), false);
    await run(mainWindow, "document.querySelector('.briefing-course-notice .course-notice-body a').click()");
    const linkedWindow = await waitFor(() => assignmentWindows().find((win) => win !== first && win !== noticeWindow), "the course notice body opens a browser window");
    await waitFor(() => viewOf(linkedWindow).webContents.getURL() === courseNoticeLink, "the course notice body link loads in AST");
    linkedWindow.destroy();
    noticeWindow.destroy();

    const courseRevision = screenData.confirmedSessionRevision;
    const openAttendance = (revision) => run(mainWindow, `window.ast.openCoursePage('${targetB.courseId}', {kind: 'attendance'}, ${revision})`);
    assert.equal(await openAttendance(courseRevision - 1), false, "an earlier session cannot open a course page");
    assert.equal(await openAttendance(courseRevision), true);
    const attendanceWindow = await waitFor(() => assignmentWindows().find((win) => win !== first), "attendance opens in a course window");
    await waitFor(() => viewOf(attendanceWindow).webContents.executeJavaScript(
      `document.querySelector('#attendance')?.textContent === '${targetB.courseId}' && document.body.dataset.write === 'blocked'`), "the attendance list loads for the requested course while writes stay blocked");
    assert.equal((await browserState(attendanceWindow)).error, null);
    assert.equal(await run(attendanceWindow, "!!document.querySelector('.assignment-side')"), false);
    assert.equal(await openAttendance(courseRevision), true);
    assert.equal(assignmentWindows().length, 2, "opening the same course and page focuses the existing window");
    assert.equal(blockedRequestsReachedServer, 0);
    attendanceWindow.destroy();

    assert.equal(await manager.openCoursePage(targetB.courseId, { kind: "activity", activityId: "701", url: lectureUrl }), true);
    const lectureWindow = await waitFor(() => assignmentWindows().find((win) => win !== first), "lecture opens in a course window");
    const lecture = viewOf(lectureWindow).webContents;
    await waitFor(() => lecture.executeJavaScript("!!document.getElementById('watch')"), "the lecture details load");
    const lectureDebugger = lecture.debugger;
    lectureDebugger.attach("1.3");
    await lectureDebugger.sendCommand("Page.enable");
    const prompts = [];
    lectureDebugger.on("message", (_event, method, data) => {
      if (method !== "Page.javascriptDialogOpening") return;
      prompts.push(data.type);
      void lectureDebugger.sendCommand("Page.handleJavaScriptDialog", { accept: prompts.length === 2 });
    });
    await lecture.executeJavaScript("document.getElementById('watch').click()", true);
    assert.equal(lecture.getURL(), lectureUrl, "cancel keeps the lecture details open");
    void lecture.executeJavaScript("document.getElementById('watch').click()", true).catch(() => {});
    await waitFor(() => lecture.executeJavaScript(`(() => {
      const player = document.querySelector('iframe')?.contentDocument;
      return !!player?.querySelector('video') && player.body.dataset.subtitles === 'ready' && player.body.dataset.write === 'blocked';
    })()`).catch(() => false), "confirm opens the player, loads captions and still blocks unrelated writes");
    assert.deepEqual(prompts, ["confirm", "confirm"]);
    assert.equal((await browserState(lectureWindow)).url, ECLASS_ORIGIN + learningFormPath);
    assert.equal(blockedRequestsReachedServer, 0);
    lectureWindow.destroy();

    await send(mainWindow, "남은 과제 알려줘");
    await waitFor(() => run(mainWindow, "!!document.querySelector('.chat-sources button')"), "chat assignment source");
    if (!live) assert.deepEqual(summaryLookups, [{}]);
    assert.equal(await run(mainWindow, "document.querySelector('.chat-sources').open"), false);
    await run(mainWindow, "document.querySelector('.chat-sources summary').click()");
    assert.equal(await run(mainWindow, "document.querySelector('.chat-sources').open"), true);
    assert.equal(await run(mainWindow, "document.querySelectorAll('.chat-inline-source').length"), 1);
    assert.equal(await run(mainWindow, "document.querySelector('.chat-deadline-badge').textContent"), "D-8");
    await run(mainWindow, "document.querySelector('.chat-inline-source').click()");
    const second = await waitFor(() => assignmentWindows().find((win) => win !== first), "second assignment window");
    await waitFor(async () => (await browserState(second))?.assignment?.assignmentId === targetB.assignmentId, "second verified assignment");
    await waitFor(async () => (await browserState(second)).assignmentFontSize === 19, "a new assignment window uses the saved font size");
    const upgradeButton = "document.querySelector('.assignment-study-upgrade button')";
    await waitFor(() => run(second, `${upgradeButton}?.textContent.trim() === '학습 가이드로 업데이트'`), "old analysis offers a study guide update");
    assert.equal(analysisRequests.includes(targetB.assignmentId), false, "opening an old analysis does not re-run the AI request");
    await run(second, `${upgradeButton}.click()`);
    await waitFor(() => run(second, "document.querySelector('.assignment-analysis-markdown h3')?.textContent === '과제 목표'"), "requesting the study guide replaces the old analysis");
    assert.equal(await run(second, `!${upgradeButton}`), true);
    assert.equal(viewOf(first).webContents.session, viewOf(second).webContents.session);
    const lookupsBeforeQuestions = assignmentLookups.length;
    const getOrb = "document.querySelector('.assignment-chat-orb')";
    const orbBounds = await run(first, `${getOrb}.getBoundingClientRect().toJSON()`);
    const absorptionTargetsOrb = await run(first, `(() => {
      const orb = ${getOrb};
      const spotlight = document.querySelector('.assignment-chat-spotlight');
      const from = spotlight.getBoundingClientRect();
      const to = orb.getBoundingClientRect();
      orb.click();
      const motion = spotlight.getAnimations().find(({ effect }) => effect.getKeyframes().some(({ transform }) => transform));
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return !motion;
      if (!motion) return false;
      const end = motion.effect.getKeyframes().at(-1);
      const transform = new DOMMatrixReadOnly(end.transform);
      return Math.abs(from.x + from.width / 2 + transform.m41 - to.x - to.width / 2) < 1 &&
        Math.abs(from.y + from.height / 2 + transform.m42 - to.y - to.height / 2) < 1 &&
        transform.a < 1 && transform.d < 1 && Number(end.opacity) === 0;
    })()`);
    assert.equal(absorptionTargetsOrb, true, "Spotlight shrinks and fades toward the floating button when motion is enabled");
    await waitFor(() => run(first, `${getOrb}.getAttribute('aria-expanded') === 'true'`), "the floating button opens the chat");
    const panelUnfoldsUp = await run(first, `(() => {
      const panel = document.querySelector('.assignment-chat-panel');
      const unfold = panel.getAnimations().find(({ effect }) => effect.getKeyframes().some(({ clipPath }) => clipPath));
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return !unfold;
      return !!unfold?.effect.getKeyframes()[0]?.clipPath?.startsWith('inset(100%');
    })()`);
    assert.equal(panelUnfoldsUp, true, "the chat starts clipped at the bottom and opens upward when motion is enabled");
    await waitFor(() => run(first, "!document.querySelector('.assignment-chat-spotlight')"), "Spotlight leaves after opening with the floating button");
    const [openOrbBounds, panelBounds] = await run(first, `[${getOrb}.getBoundingClientRect().toJSON(),
      document.querySelector('.assignment-chat-panel').getBoundingClientRect().toJSON()]`);
    assert.deepEqual(openOrbBounds, orbBounds, "the floating button keeps its visible position while the chat is open");
    assert.ok(panelBounds.height > 0 && panelBounds.bottom <= orbBounds.top, "the chat expands above the floating button");
    const chatDebugger = first.webContents.debugger;
    const chatBounds = () => run(first, "document.querySelector('.assignment-chat-panel').getBoundingClientRect().toJSON()");
    chatDebugger.attach("1.3");
    try {
      for (const [corner, delta] of [["top-left", -8], ["bottom-right", 8]]) {
        const before = await chatBounds();
        const point = await run(first, `(() => {
          const grip = document.querySelector('.assignment-chat-resize[data-corner="${corner}"]');
          const { x, y, width, height } = grip.getBoundingClientRect();
          return { x: x + width / 2, y: y + height / 2 };
        })()`);
        const destination = { x: point.x + delta, y: point.y + delta };
        await chatDebugger.sendCommand("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", buttons: 1, clickCount: 1 });
        await chatDebugger.sendCommand("Input.dispatchMouseEvent", { type: "mouseMoved", ...destination, button: "left", buttons: 1 });
        await chatDebugger.sendCommand("Input.dispatchMouseEvent", { type: "mouseReleased", ...destination, button: "left", buttons: 0, clickCount: 1 });
        await waitFor(async () => {
          const after = await chatBounds();
          return after.width > before.width && after.height > before.height;
        }, `dragging the ${corner} corner resizes both dimensions`);
        const after = await chatBounds();
        const fixed = corner === "top-left" ? ["right", "bottom"] : ["left", "top"];
        for (const axis of fixed) assert.equal(after[axis], before[axis],
          `${corner} retains ${axis}: ${JSON.stringify({ before, after })}`);
        assert.equal(await run(first, "document.querySelector('.assignment-floating-chat').hasAttribute('data-resizing')"), false);
      }
    } finally {
      chatDebugger.detach();
    }
    await run(first, `${getOrb}.click()`);
    await waitFor(() => run(first, `(() => {
      const panel = document.querySelector('.assignment-chat-panel');
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return panel.hidden;
      return !panel.hidden && panel.inert && panel.getAnimations().some((animation) =>
        animation.playbackRate < 0 && animation.effect.getKeyframes().some(({ clipPath }) => clipPath));
    })()`), "the chat visibly folds back before being hidden");
    if (!await run(first, "matchMedia('(prefers-reduced-motion: reduce)').matches")) {
      await waitFor(() => run(first, `document.querySelector('.assignment-chat-spotlight[inert]')?.getAnimations().some((animation) =>
        animation.playbackRate < 0 && animation.effect.getKeyframes().some(({ transform }) => transform))`),
        "Spotlight expands out of the floating button");
    }
    await waitFor(() => run(first, "!!document.querySelector('.assignment-chat-spotlight:not([inert])') && !!document.querySelector('.assignment-chat-panel[hidden]')"),
      "the floating button closes the chat and restores Spotlight");
    assert.deepEqual(await run(first, `${getOrb}.getBoundingClientRect().toJSON()`), orbBounds, "the floating button stays visible during both transitions");
    await run(first, `(() => {
      const form = document.querySelector('.assignment-chat-spotlight');
      const input = form.querySelector('input');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '제출 조건을 정리해줘');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      form.requestSubmit();
    })()`);
    await waitFor(() => run(first, "!!document.querySelector('.assignment-chat-panel:not([hidden])') && !document.querySelector('.assignment-chat-spotlight')"),
      "Spotlight opens the chat and hides the quick composer");
    await send(second, "필수 조건 알려줘");
    const firstAnswer = await waitFor(() => run(first,
      "[...document.querySelectorAll('.chat-answer-text')].find(el => el.textContent.includes('과제 1 답변'))?.textContent"), "first contextual answer");
    assert.match(firstAnswer, /재귀 함수를.*테스트 안내 1\.pdf/);
    assert.ok(firstAnswer.includes(assignments.get(targetA.assignmentId).dueAt));
    await run(first, "document.querySelector('.assignment-chat-close').click()");
    await waitFor(() => run(first, "!!document.querySelector('.assignment-chat-spotlight:not([inert])') && !document.querySelector('.assignment-chat-panel:not([hidden])')"),
      "closing the chat restores Spotlight");
    const assignmentDebugger = first.webContents.debugger;
    assignmentDebugger.attach("1.3");
    try {
      await assignmentDebugger.sendCommand("Emulation.setEmulatedMedia", {
        features: [{ name: "prefers-reduced-motion", value: "reduce" }],
      });
      assert.equal(await run(first, "matchMedia('(prefers-reduced-motion: reduce)').matches"), true);
      await run(first, `${getOrb}.click()`);
      await waitFor(() => run(first, "!!document.querySelector('.assignment-chat-panel:not([hidden]):not([inert])')"),
        "the chat can open with reduced motion");
      await run(first, `${getOrb}.click()`);
      assert.equal(await run(first, "!!document.querySelector('.assignment-chat-panel[hidden]') && !!document.querySelector('.assignment-chat-spotlight:not([inert])')"),
        true, "with reduced motion both controls switch immediately");
    } finally {
      await assignmentDebugger.sendCommand("Emulation.setEmulatedMedia", { features: [] });
      assignmentDebugger.detach();
    }
    await waitFor(() => run(second, "document.querySelector('.chat-messages .chat-answer-text')?.textContent.includes('과제 2 답변')"), "second contextual answer");
    const downloadsBeforeDifficulty = attachmentDownloads.length;
    await send(second, "이거 과제 어려워보여?");
    await waitFor(() => run(second, "document.querySelector('.chat-messages .chat-turn:last-child .chat-answer-text')?.textContent.includes('난이도는 중간')"), "casual difficulty question uses PDF notes");
    assert.equal(attachmentDownloads.length, downloadsBeforeDifficulty);
    if (pdfNotesOnly) {
      console.log("PASS: the first analysis saves PDF text and visuals and the chat answers from those notes without redownloading the PDF");
      return;
    }
    assert.doesNotMatch(await run(first, "document.querySelector('.chat-messages').textContent"), /과제 2 답변/);
    await run(first, "document.querySelectorAll('.assignment-files button')[1].click()");
    await waitFor(async () => (await browserState(first))?.attachmentPreview?.name === textAttachment.name, "selected attachment opens inline");
    assert.equal(await run(first, "document.querySelector('.assignment-attachment-bar button[aria-controls]') === null"), true);
    const inlinePreview = first.contentView.children.at(-1).webContents;
    assert.notEqual(inlinePreview.session, site.webContents.session);
    assert.equal(await inlinePreview.executeJavaScript("document.body.innerText.trim()"), previewText);
    assert.equal(await inlinePreview.executeJavaScript("typeof window.ast === 'undefined' && !document.body.dataset.executed"), true);
    assert.equal((await browserState(first)).activeTabId, originalTab);
    assert.equal((await browserState(first)).assignment.assignmentId, targetA.assignmentId);
    assert.deepEqual(attachmentDownloads.filter(({ attachment_id }) => attachment_id === textAttachment.id), [
      { course_id: targetA.courseId, assignment_id: targetA.assignmentId, attachment_id: textAttachment.id },
    ]);
    assert.equal(mockCalls.filter(([kind, , id]) => kind === "view" && id === targetA.assignmentId).length, initialAssignmentVisits);
    await send(first, "그럼 반드시 써야 해?");
    await waitFor(() => run(first, "document.querySelectorAll('.chat-messages .chat-answer-text').length === 2"), "chat retains its history while the attachment is visible");
    const savedPath = join(profile, "attachment-copy.txt");
    const chooseSavePath = dialog.showSaveDialog;
    dialog.showSaveDialog = async () => ({ canceled: false, filePath: savedPath });
    try {
      const savePreview = await browserState(first);
      assert.equal(await run(first, `window.assignmentBrowser.downloadAssignmentAttachment(${originalTab}, ${JSON.stringify(savePreview.attachmentPreview.id)})`), true);
    } finally {
      dialog.showSaveDialog = chooseSavePath;
    }
    assert.equal(readFileSync(savedPath, "utf8"), previewText);
    await run(first, "document.querySelector('.assignment-files button').click()");
    await waitFor(async () => (await browserState(first))?.attachmentPreview?.name === assignments.get(targetA.assignmentId).attachments[0].name,
      "selected PDF replaces the first attachment");
    assert.equal(inlinePreview.isDestroyed(), true);
    const pdfFrame = "document.querySelector('.assignment-pdf-frame:not([hidden])')";
    const pdfUrl = (await browserState(first)).tabs.find(({ id }) => id === originalTab).pdf.url;
    await waitFor(() => first.webContents.mainFrame.framesInSubtree.some(({ url }) => url === pdfUrl), "PDF frame loads");
    const pdfPreview = first.webContents.mainFrame.framesInSubtree.find(({ url }) => url === pdfUrl);
    assert.equal(await pdfPreview.executeJavaScript("document.contentType"), "application/pdf");
    await waitFor(() => first.webContents.mainFrame.framesInSubtree.some(({ url }) => url.startsWith("chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/")),
      "Chromium's PDF viewer renders inside the frame");
    const pdfToggle = "document.querySelector('.assignment-attachment-bar button[aria-controls=assignment-explanation]')";
    const pdfFillsWindow = async () => {
      const [width, height] = first.getContentSize();
      const bounds = await run(first, `${pdfFrame}.getBoundingClientRect().toJSON()`);
      return bounds.x === 0 && bounds.width === width && bounds.y + bounds.height === height &&
        await run(first, "document.querySelector('#assignment-explanation').hidden && !document.querySelector('.assignment-divider')");
    };
    await waitFor(pdfFillsWindow, "PDF opens across the whole assignment window by default");
    await run(first, `${pdfToggle}.click()`);
    await waitFor(() => explanationFillsPane(), "the explanation can be restored alongside the same PDF");
    const pdfBounds = await run(first, `${pdfFrame}.getBoundingClientRect().toJSON()`);
    assert.ok(pdfBounds.width < first.getContentSize()[0], "the PDF viewer shrinks to the split");
    const orbStart = await run(first, `${getOrb}.getBoundingClientRect().toJSON()`);
    const pdfPoint = { x: Math.round(pdfBounds.width * .55), y: Math.round(pdfBounds.height * .65 + pdfBounds.y) };
    const chatWasOpen = await run(first, `${getOrb}.getAttribute('aria-expanded') === 'true'`);
    if (chatWasOpen) {
      await run(first, `${getOrb}.click()`);
      await waitFor(() => run(first, "!!document.querySelector('.assignment-chat-panel[hidden]')"), "chat is closed before testing the PDF overlay");
    }
    const overlayDebugger = first.webContents.debugger;
    overlayDebugger.attach("1.3");
    try {
      const start = { x: Math.round(orbStart.x + orbStart.width / 2), y: Math.round(orbStart.y + orbStart.height / 2) };
      await overlayDebugger.sendCommand("Input.dispatchMouseEvent", { type: "mousePressed", ...start, button: "left", buttons: 1, clickCount: 1 });
      await overlayDebugger.sendCommand("Input.dispatchMouseEvent", { type: "mouseMoved", ...pdfPoint, button: "left", buttons: 1 });
      await overlayDebugger.sendCommand("Input.dispatchMouseEvent", { type: "mouseReleased", ...pdfPoint, button: "left", buttons: 0, clickCount: 1 });
      await waitFor(() => run(first, `document.elementFromPoint(${pdfPoint.x}, ${pdfPoint.y})?.closest('.assignment-chat-orb') === ${getOrb}`),
        "the agent can be dragged from the explanation onto the PDF");
      await overlayDebugger.sendCommand("Input.dispatchMouseEvent", { type: "mousePressed", ...pdfPoint, button: "left", buttons: 1, clickCount: 1 });
      await overlayDebugger.sendCommand("Input.dispatchMouseEvent", { type: "mouseReleased", ...pdfPoint, button: "left", buttons: 0, clickCount: 1 });
      await waitFor(() => run(first, `${getOrb}.getAttribute('aria-expanded') === 'true'`), "clicking the agent over the PDF opens chat");
    } finally { overlayDebugger.detach(); }
    assert.equal(await run(first, "document.querySelectorAll('.chat-messages .chat-answer-text').length"), 2);
    await run(first, `${pdfToggle}.click()`);
    await waitFor(pdfFillsWindow, "the PDF can be expanded again");
    assert.equal(await run(first, `document.elementFromPoint(${pdfPoint.x}, ${pdfPoint.y})?.closest('.assignment-chat-orb') === ${getOrb}`), true,
      "the orb stays available over the full-width PDF");
    assert.equal(await run(first, `document.elementFromPoint(10, ${pdfPoint.y}) === ${pdfFrame}`), true,
      "uncovered parts of the PDF remain interactive");
    const pdfViewer = first.webContents.mainFrame.framesInSubtree.find(({ url }) => url.startsWith("chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/"));
    await waitFor(() => pdfViewer.executeJavaScript("document.querySelector('pdf-viewer')?.loadState_ === 'success'"), "Chromium successfully renders the PDF");
    await run(first, "document.querySelector('.assignment-attachment-bar button').click()");
    await waitFor(async () => !(await browserState(first)).attachmentPreview, "closing inline preview reveals the same assignment");
    await waitFor(() => run(first, "!document.querySelector('.assignment-pdf-frame')"), "closing the preview removes the PDF frame");
    assert.equal(site.webContents.getURL(), assignmentUrl(targetA.assignmentId));
    await waitFor(() => site.getBounds().width === initialWebWidth, "returning from PDF restores the narrow LMS column");
    assert.deepEqual(assignmentLookups.slice(lookupsBeforeQuestions), [], "assignment questions use the loaded context without LMS lookups");

    const chromeDebugger = first.webContents.debugger;
    const toolbarHeight = () => run(first, "document.querySelector('.assignment-toolbar').getBoundingClientRect().height");
    const centerOf = (selector) => run(first, `(() => {
      const { x, y, width, height } = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
      return { x: x + width / 2, y: y + height / 2 };
    })()`);
    const mouse = (type, point, extra = {}) => chromeDebugger.sendCommand("Input.dispatchMouseEvent", { type, ...point, ...extra });
    const click = async (point) => {
      await mouse("mouseMoved", point);
      await mouse("mousePressed", point, { button: "left", buttons: 1, clickCount: 1 });
      await mouse("mouseReleased", point, { button: "left", buttons: 0, clickCount: 1 });
    };
    const key = async (value, windowsVirtualKeyCode, text) => {
      const event = { key: value, code: value, windowsVirtualKeyCode };
      await chromeDebugger.sendCommand("Input.dispatchKeyEvent", { type: "keyDown", text, ...event });
      await chromeDebugger.sendCommand("Input.dispatchKeyEvent", { type: "keyUp", ...event });
    };
    const activeTab = await centerOf('.assignment-tab-select[aria-current="page"]');
    const previewSelector = ".assignment-address-preview";
    chromeDebugger.attach("1.3");
    try {
      await mouse("mouseMoved", { x: activeTab.x + 260, y: activeTab.y });
      await waitFor(async () => await toolbarHeight() === 0, "toolbar is hidden away from the current tab");
      await mouse("mouseMoved", activeTab);
      await waitFor(async () => await toolbarHeight() === 30 &&
        Math.abs(site.getBounds().y - await run(first, "document.querySelector('.assignment-toolbar').getBoundingClientRect().bottom")) <= 1,
      "hovering the current tab reveals the compact toolbar above the native view");
      assert.equal(await run(first, "document.querySelector('.assignment-address-preview').textContent"), assignmentUrl(targetA.assignmentId));
      await click(await centerOf(previewSelector));
      await waitFor(async () => await toolbarHeight() === 52, "clicking the address expands the editor");
      assert.deepEqual(await run(first, `(() => {
        const input = document.querySelector('.assignment-address-editor input');
        return [document.activeElement === input, input.value];
      })()`), [true, assignmentUrl(targetA.assignmentId)]);
      await key("Backspace", 8);
      await waitFor(() => run(first, "document.querySelector('.assignment-address-editor input').value === ''"), "the address can be cleared");
      await chromeDebugger.sendCommand("Input.insertText", { text: "https://example.test/files" });
      await waitFor(() => run(first, "document.querySelector('.assignment-address-editor input').value === 'https://example.test/files'"), "a replacement address can be entered");
      await key("Enter", 13, "\r");
    } finally { chromeDebugger.detach(); }
    await waitFor(async () => (await browserState(first))?.url === "https://example.test/files" && (await browserState(first)).assignmentState === "none", "browser navigates to the file selection fixture");
    assert.equal(await viewOf(first).webContents.executeJavaScript("!!document.querySelector('input[type=file]')"), true);
    const fileContents = viewOf(first).webContents;
    const samplePath = join(profile, "sample.txt");
    writeFileSync(samplePath, "synthetic test file; never uploaded");
    fileContents.debugger.attach("1.3");
    try {
      const { root: document } = await fileContents.debugger.sendCommand("DOM.getDocument");
      const { nodeId } = await fileContents.debugger.sendCommand("DOM.querySelector", { nodeId: document.nodeId, selector: "input[type=file]" });
      await fileContents.debugger.sendCommand("DOM.setFileInputFiles", { nodeId, files: [samplePath] });
      assert.equal(await fileContents.executeJavaScript("document.querySelector('input[type=file]').files[0].name"), "sample.txt");
    } finally { fileContents.debugger.detach(); }
    const beforeReload = mockCalls.length;
    chromeDebugger.attach("1.3");
    try {
      await mouse("mouseMoved", activeTab);
      await waitFor(async () => await toolbarHeight() === 30, "submitted address returns to the compact toolbar");
      assert.equal(await run(first, "document.querySelector('.assignment-address-preview').textContent"), "https://example.test/files");
      await click(await centerOf('.assignment-navigation-button[aria-label="새로고침"]'));
      await mouse("mouseMoved", { x: activeTab.x + 260, y: activeTab.y });
      await waitFor(async () => await toolbarHeight() === 0, "leaving the toolbar and the current tab hides the controls");
    } finally { chromeDebugger.detach(); }
    await waitFor(async () => !(await browserState(first)).loading && await fileContents.executeJavaScript("document.querySelector('input[type=file]')?.files.length === 0"), "reload replaces document");
    await waitFor(() => first.contentView.children.at(-1) === site, "reload's transition releases the page view");
    assert.equal(mockCalls.length, beforeReload, "external browsing does not select an LMS course");
    await command(first, "back");
    await waitFor(async () => (await browserState(first))?.assignment?.assignmentId === targetA.assignmentId, "back restores matching assignment");
    await waitFor(async () => (await browserState(first))?.analysis?.status === "ready", "back restores the stored assignment analysis");
    assert.deepEqual(analysisRequests.filter((id) => id === targetA.assignmentId), [targetA.assignmentId]);
    await openChat(first);
    await waitFor(() => run(first, "document.querySelector('.chat-messages .chat-answer-text')?.textContent.includes('과제 1 답변')"), "same assignment chat restored");
    await command(first, "forward");
    await waitFor(async () => {
      const state = await browserState(first);
      return state?.url === "https://example.test/files" && state.assignmentState === "none" && !state.loading;
    }, "forward navigation");
    await command(first, "back");
    await waitFor(async () => (await browserState(first))?.assignment?.assignmentId === targetA.assignmentId, "back again");
    await viewOf(first).webContents.executeJavaScript("document.querySelector('a').click()");
    await waitFor(async () => (await browserState(first))?.assignment?.assignmentId === targetC.assignmentId, "native assignment link updates context");
    assert.equal(await run(first, "window.ast.getChatTranscript().then(state=>state.turns.length)"), 0);
    const lookupsBeforeSwitchedQuestion = assignmentLookups.length;
    await send(first, "제출 조건을 정리해줘");
    const switchedAnswer = await waitFor(() => run(first,
      "[...document.querySelectorAll('.chat-answer-text')].find(el => el.textContent.includes('과제 3 답변'))?.textContent"), "switched assignment answer");
    assert.match(switchedAnswer, /선택 정렬을.*테스트 안내 3\.pdf/);
    assert.ok(switchedAnswer.includes(assignments.get(targetC.assignmentId).dueAt));
    assert.deepEqual(assignmentLookups.slice(lookupsBeforeSwitchedQuestion), [], "the switched assignment also answers without LMS lookups");
    await send(first, guidanceQuestion);
    const guide = await waitFor(() => run(first,
      "[...document.querySelectorAll('.chat-answer-text')].find(el => el.textContent.includes('풀이도 해볼까요?'))?.textContent"), "assignment guidance and offer");
    assert.match(guide, /코드를 작성하고 예제로 확인한 다음.*e-Class/);
    assert.ok(!guide.includes(fixtureSolution));
    await send(first, "응");
    await waitFor(() => run(first,
      `[...document.querySelectorAll('.chat-answer-text')].some(el => el.textContent.includes(${JSON.stringify(fixtureSolution)}))`), "affirmative reply solves the same assignment");
    await send(first, solveQuestion);
    await waitFor(() => run(first,
      `[...document.querySelectorAll('.chat-answer-text')].filter(el => el.textContent.includes(${JSON.stringify(fixtureSolution)})).length === 2`),
    "a natural solve request uses the current PDF before answering");
    assert.deepEqual(attachmentReads, [], "saved PDF notes avoid repeating text extraction");
    assert.equal(analysisRequests.filter((id) => id === targetC.assignmentId).length, 1);
    assert.doesNotMatch(await run(second, "document.querySelector('.chat-messages').textContent"), /풀이도 해볼까요|최솟값/);
    assert.equal((await browserState(second)).assignment.assignmentId, targetB.assignmentId);
    assert.ok(mockCalls.some((entry) => entry[0] === "view" && entry[1] === targetB.courseId && entry[2] === targetB.assignmentId));
    await manager.open(targetA);
    await waitFor(async () => (await browserState(first))?.assignment?.assignmentId === targetA.assignmentId, "reopening restores original assignment");
    assert.equal(assignmentWindows().length, 2);

    await navigate(first, ECLASS_ORIGIN + blockedPagePath);
    await waitFor(() => run(first, "document.querySelector('.assignment-browser-status')?.textContent.includes('공식 브라우저')"), "blocked main-frame navigation shows guidance");
    assert.equal((await browserState(first)).canRetryNavigation, false);
    assert.equal(blockedRequestsReachedServer, 0);

    let interrupt = true;
    retryServer = createServer((request, response) => {
      if (interrupt) request.socket.destroy();
      else response.end("Retry succeeded");
    });
    await new Promise((resolve, reject) => {
      retryServer.once("error", reject);
      retryServer.listen(0, "127.0.0.1", resolve);
    });
    const interruptedUrl = `http://127.0.0.1:${retryServer.address().port}/interrupted`;
    await navigate(first, interruptedUrl);
    await waitFor(() => run(first, "document.querySelector('.assignment-browser-status button')?.textContent === '다시 시도'"), "temporary network error offers retry");
    interrupt = false;
    await run(first, "document.querySelector('.assignment-browser-status button').click()");
    await waitFor(async () => {
      const state = await browserState(first);
      return state?.url === interruptedUrl && !state.error && !state.loading &&
        await site.webContents.executeJavaScript("document.body.textContent === 'Retry succeeded'");
    }, "retry loads the failed address without reopening the window");
    await manager.open(targetA);
    await waitFor(async () => (await browserState(first))?.assignment?.assignmentId === targetA.assignmentId, "restore assignment after retry");

    const dividerBefore = await run(first, "Number(document.querySelector('.assignment-divider').getAttribute('aria-valuenow'))");
    const divider = await run(first, "(() => { const r=document.querySelector('.assignment-divider').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()");
    first.webContents.debugger.attach("1.3");
    try {
      await first.webContents.debugger.sendCommand("Input.dispatchMouseEvent", { type: "mousePressed", ...divider, button: "left", buttons: 1, clickCount: 1 });
      await first.webContents.debugger.sendCommand("Input.dispatchMouseEvent", { type: "mouseMoved", x: divider.x + 80, y: divider.y, button: "left", buttons: 1 });
      await first.webContents.debugger.sendCommand("Input.dispatchMouseEvent", { type: "mouseReleased", x: divider.x + 80, y: divider.y, button: "left", buttons: 0, clickCount: 1 });
      await waitFor(() => run(first, `Number(document.querySelector('.assignment-divider').getAttribute('aria-valuenow')) > ${dividerBefore}`), "pointer resizes divider");
    } finally { first.webContents.debugger.detach(); }

    first.setContentSize(1050, 630);
    const webView = viewOf(first);
    await waitFor(() => webView.getBounds().height > 450 && webView.getBounds().height < 630, "view fits resized window");
    const before = await run(first, "document.querySelector('.assignment-web-page').getBoundingClientRect().width");
    await waitFor(() => Math.abs(webView.getBounds().width - before) <= 1, "view matches resized shell width");
    assert.equal(await explanationFillsPane(), true, "the explanation fills the resized window");
    await run(first, "document.querySelector('.assignment-divider').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))");
    try {
      await waitFor(() => webView.getBounds().width < before - 1, "split resize reaches web view");
    } catch (error) {
      console.error("SPLIT", before, webView.getBounds(), await run(first, "[document.querySelector('.assignment-divider').getAttribute('aria-valuenow'), getComputedStyle(document.querySelector('.assignment-workspace')).gridTemplateColumns, document.querySelector('.assignment-web-page').getBoundingClientRect().width]"));
      throw error;
    }
    const webContents = webView.webContents;
    first.destroy();
    await waitFor(() => webContents.isDestroyed(), "closed view is destroyed");
    assert.equal(second.isDestroyed(), false);

    await navigate(second, ECLASS_ORIGIN + ECLASS_MAIN_PATH);
    await waitFor(() => viewOf(second).webContents.executeJavaScript(
      "document.querySelector('#progress')?.textContent === '진행 주 11 / 16 주'"), "home renders course progress from its read-only POST");
    assert.equal((await browserState(second)).error, null);
    await command(second, "back");
    await waitFor(async () => (await browserState(second))?.assignment?.assignmentId === targetB.assignmentId, "home back restores original assignment");

    await web.session.cookies.remove(ECLASS_ORIGIN, "fixture_login");
    await command(second, "login");
    await waitFor(() => viewOf(second).webContents.getURL().endsWith("login_form.acl"), "official login navigation");
    await viewOf(second).webContents.executeJavaScript("document.querySelector('form').requestSubmit()");
    await waitFor(async () => (await browserState(second))?.assignment?.assignmentId === targetB.assignmentId, "login restores original assignment");
    assert.equal(savedBrowserLogin, true);

    nextWorkspaceReply = { assignmentId: targetD.assignmentId, respond: () => ({ status: "error", message: "모의 원문 조회 실패" }) };
    await manager.open(targetD);
    const panelRetry = await waitFor(() => assignmentWindows().find((win) => win !== second), "page opens with a deferred panel");
    const panelSite = viewOf(panelRetry).webContents;
    await waitFor(async () => (await browserState(panelRetry))?.assignmentMessage === "모의 원문 조회 실패", "panel shows a retryable lookup error");
    assert.equal(panelSite.getURL(), assignmentUrl(targetD.assignmentId));
    assert.equal((await browserState(panelRetry)).error, null, "a panel error leaves the site available");
    const loadedViews = mockCalls.filter(([kind, , id]) => kind === "view" && id === targetD.assignmentId).length;
    let finishPanelRetry;
    const delayedReply = new Promise((resolve) => { finishPanelRetry = resolve; });
    nextWorkspaceReply = { assignmentId: targetD.assignmentId, respond: () => delayedReply };
    try {
      await run(panelRetry, "[...document.querySelectorAll('.assignment-side button')].find(b => b.textContent.trim() === '과제 정보 다시 불러오기').click()");
      await waitFor(() => nextWorkspaceReply === undefined, "the panel retry starts without navigating");
      assert.equal(mockCalls.filter(([kind, , id]) => kind === "view" && id === targetD.assignmentId).length, loadedViews);
      await navigate(panelRetry, "https://example.test/next");
      await waitFor(async () => (await browserState(panelRetry))?.assignmentState === "none", "leaving the assignment clears its pending panel");
    } finally { finishPanelRetry({ status: "ok", assignment: assignments.get(targetD.assignmentId) }); }
    await waitFor(async () => panelSite.getURL() === "https://example.test/next", "new page is committed");
    assert.equal((await browserState(panelRetry)).assignment, null, "a late reply cannot populate a different page");
    panelRetry.destroy();

    await manager.open({ assignmentId: "9999" });
    const unavailable = await waitFor(() => assignmentWindows().find((win) => win !== second), "unavailable assignment window");
    await waitFor(async () => (await browserState(unavailable))?.assignmentState === "unavailable", "unavailable assignment");
    await waitFor(() => unavailable.contentView.children.at(-1) === viewOf(unavailable), "opening overlay clears when no page can load");
    unavailable.destroy();

    const revision = screenData.confirmedSessionRevision;
    const prepare = (request) => run(mainWindow, `window.ast.prepareAssignment(${JSON.stringify(targetD)}, ${request}, ${revision})`);
    const showPrepared = (request) => run(mainWindow, `window.ast.showPreparedAssignment(${request})`);
    assert.equal(await prepare(1), true);
    const canceled = assignmentWindows().find((win) => win !== second);
    assert.equal(canceled.isVisible(), false);
    await run(mainWindow, "window.ast.cancelPreparedAssignment(1)");
    assert.equal(canceled.isDestroyed(), true, "canceling releases the hidden window");
    assert.equal(await showPrepared(1), false);

    assert.equal(await prepare(2), true);
    const staged = assignmentWindows().find((win) => win !== second);
    let showCalls = 0;
    staged.show = () => { showCalls++; };
    staged.focus = () => {};
    windowOptions.show = true;
    const stageLoads = () => mockCalls.filter(([kind, , id]) => kind === "view" && id === targetD.assignmentId).length;
    await waitFor(async () => (await browserState(staged))?.assignment?.assignmentId === targetD.assignmentId,
      "the correct course is selected and the assignment loads in the hidden window");
    assert.equal(staged.isVisible(), false);
    assert.equal(showCalls, 0, "ready-to-show does not display a prepared window");
    assert.equal(staged.contentView.children.at(-1), viewOf(staged), "a page loaded in the background is ready to display");
    const loadsBeforeShow = stageLoads();
    assert.equal(await showPrepared(2), true);
    await waitFor(() => showCalls === 1, "the explicit show displays the prepared window");
    assert.equal(stageLoads(), loadsBeforeShow, "showing the window reuses the loaded page");
    assert.equal(await showPrepared(2), false, "the show request is consumed");
    windowOptions.show = false;
    staged.destroy();
    console.log("PASS: handwriting and first page reveal, silent background blocks, main-frame guidance and retry, unavailable cleanup, briefing and chat links, assignment guidance and same-assignment solution, independent course/chat/navigation, hover toolbar, history/reload, file selection, divider drag, resize, cleanup, login resume");
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    finishInitialWorkspace();
    finishInitialCourse();
    finishInitialAsset();
    retryServer?.close();
    manager?.close();
    mainWindow?.destroy();
    await realConnector?.close();
    rmSync(profile, { recursive: true, force: true });
    app.exit(process.exitCode ?? 0);
  }
}
void main();
