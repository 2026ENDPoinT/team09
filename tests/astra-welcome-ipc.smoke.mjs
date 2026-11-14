// Run after npm run build: electron tests/astra-welcome-ipc.smoke.mjs --headless
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, ipcMain, session } from "electron";
import { registerScreenActions } from "../dist-desktop/desktop/screen-controller.js";
import { registerStudyFontSettings } from "../dist-desktop/desktop/study-font-settings.js";
import { ScreenData } from "../dist-desktop/desktop/screen-data.js";
import { createChatSession } from "../dist-desktop/desktop/chat-controller.js";
import { ChatTranscript } from "../dist-desktop/desktop/chat-transcript.js";
import { createChatWorkspace } from "../dist-desktop/desktop/chat-workspace.js";
import { registerChatWorkspace } from "../dist-desktop/desktop/chat-workspace-ipc.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const profile = mkdtempSync(join(tmpdir(), "ast-welcome-ipc-"));
app.setPath("userData", profile);
app.disableHardwareAcceleration();

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

async function main() {
  let window;
  let screens;
  let login;
  let chat;
  let closing = false;
  try {
    await app.whenReady();
    app.dock?.hide();
    session.defaultSession.webRequest.onBeforeRequest({ urls: ["http://*/*", "https://*/*"] }, (_, callback) => callback({ cancel: true }));
    const chatHistory = deferred();
    ipcMain.handle("ast:chat-config", () => ({ model: "fixture", usdKrw: 1400, hasApiKey: false }));
    ipcMain.handle("ast:chat-composing", () => {});
    const keyA = "a".repeat(64);
    const keyB = "b".repeat(64);
    const directoryFor = (key) => join(profile, "accounts", key);
    const activeDirectory = () => screens.account && directoryFor(screens.account.key);
    for (const [key, question] of [[keyA, "첫 번째 계정 채팅"], [keyB, "두 번째 계정 채팅"]]) {
      const directory = directoryFor(key);
      mkdirSync(directory, { recursive: true });
      assert.equal(new ChatTranscript(join(directory, "chat-history.json")).append({
        id: key, question, answer: "### 테스트 답변\n1. 첫 번째 단계\n2. 두 번째 단계\n> *마감 안내*",
        state: "done", results: [], sources: [],
      }), true);
    }
    ipcMain.handle("ast:chat-transcript", async () => {
      await chatHistory.promise;
      return chat.snapshot();
    });
    const verification = deferred();
    const overview = deferred();
    const timetable = deferred();
    const briefing = deferred();
    const courseActivities = deferred();
    const otherScreens = deferred();
    const lmsReads = [];
    let captured = false;
    let opened = 0;
    let rechecks = 0;
    let confirmations = 0;
    let backgroundReads = 0;
    let returningTimetable;
    let returningOverview;
    let returningBriefing;
    let profileReads = 0;
    let pendingProfile;
    const coursePageOpens = [];
    const assignmentOpens = [];
    const assignmentPrepares = [];
    const preparedAssignmentCancels = [];
    const preparedAssignmentShows = [];
    const activityUrl = "https://eclass.seoultech.ac.kr/ilos/cls/st/activity/activity_form.acl?m=lecture_material&n=51";
    const notice = (id, title, page) => ({ id, title, page, course_id: "1", course_name: "테스트 강의",
      created_at: `2026-09-${id.padStart(2, "0")}T09:00:00+09:00` });
    const newNotices = [notice("8", "첫 번째 강의실 공지", 1), notice("7", "두 번째 강의실 공지", 1),
      notice("6", "세 번째 강의실 공지", 1), notice("5", "네 번째 강의실 공지", 1)];
    const olderNotice = { ...notice("2", "추가 안내", 2), content: "보충 수업은 2층에서 진행해요." };
    const addedNotice = notice("9", "새로 올라온 수업 공지", 1);
    const secondCourse = { id: "2", name: "스페인어(1)", category: "regular", professor: null };
    const secondCourseNotice = { ...notice("4", "스페인어 수업 안내", 1), course_id: secondCourse.id, course_name: secondCourse.name };
    const nonRegularCourse = { id: "3", name: "개인정보 보호와 정보 보안 역량 강화를 위한 비정규 예시 과정", category: "non_regular", professor: null };
    const nonRegularNotice = { ...notice("3", "비정규 과정 안내", 1), course_id: nonRegularCourse.id, course_name: nonRegularCourse.name };
    const otherCourseNotices = new Map([[secondCourse.id, secondCourseNotice], [nonRegularCourse.id, nonRegularNotice]]);
    let noticeAdded = false;
    let listedCourseNotices = 0;
    const indexedBodyReads = [];
    const initialRoster = { regular: 2, non_regular: 1, courses: [
      { id: "1", name: "테스트 강의", category: "regular", professor: null }, secondCourse, nonRegularCourse,
    ] };
    const dormDishes = { kb: "김치찌개", seonglim: "된장국", surim: "미역국" };
    let nextAccount = { account_key: keyA, display_name: "테스트학생", course_roster: initialRoster,
      student_profile: { department: "컴퓨터 공학과", year: 2 } };

    async function request(name, args) {
      if (name === "start_desktop_login") { opened++; return { status: "opened", message: "테스트 창" }; }
      if (name === "get_desktop_login_status") {
        if (args.recheck) rechecks++;
        return { status: captured ? "captured" : "pending", message: "테스트 창에서 로그인해 주세요." };
      }
      if (name === "confirm_desktop_login") {
        assert.deepEqual(args, { use_saved: false });
        confirmations++;
        await verification.promise;
        return { status: "authenticated", message: "검증 완료", ...nextAccount };
      }
      if (name === "get_student_profile") {
        profileReads++;
        assert.deepEqual(args, {});
        return pendingProfile?.promise ?? {
          display_name: nextAccount.display_name, ...nextAccount.student_profile,
          phone: "010-0000-0000", email: "profile@example.test",
        };
      }
      if (name === "get_course_classroom") {
        assert.deepEqual(args, { course_id: "1" });
        return courseActivities.promise;
      }
      if (name === "get_course_classroom_info") {
        assert.deepEqual(args, { course_id: "1" });
        return { course_code: "123456-31001", meetings: [
          { weekday: "월", start_time: "09:00", end_time: "10:30", room: "예시관 101" },
          { weekday: "수", start_time: "14:00", end_time: "15:30", room: "예시 실습관 202" },
          { weekday: "금", periods: "3 ~ 4", room: null },
        ] };
      }
      if (name === "get_course_recent_notices") {
        assert.deepEqual(args, { course_id: "1" });
        return { notices: newNotices.slice(0, 3) };
      }
      if (name === "get_course_notice_page") {
        if (!args.query) listedCourseNotices++;
        const otherNotice = otherCourseNotices.get(args.course_id);
        if (otherNotice) {
          assert.equal(args.page, 1);
          return { notices: [otherNotice], has_next: false };
        }
        assert.equal(args.course_id, "1");
        assert.ok([1, 2].includes(args.page));
        if (args.query) assert.equal(args.query, "보충 수업");
        const notices = args.page === 2 ? [olderNotice] : args.query ? [] : noticeAdded ? [addedNotice, ...newNotices] : newNotices;
        return { notices, has_next: args.page === 1 };
      }
      if (name === "get_course_notice_bodies") {
        assert.ok(args.course_id === "1" || otherCourseNotices.has(args.course_id));
        indexedBodyReads.push(...args.notice_ids);
        return { bodies: args.notice_ids.map((id) => {
          const text = id === "2" ? "보충 수업 장소는 본문 전용 검색어 세미나실이에요." : `수업 공지 본문 ${id}`;
          return { id, text, body_html: `<p>${text}</p>` };
        }) };
      }
      if (name === "get_course_notice") {
        assert.deepEqual(args, { course_id: "1", notice_id: "2", page: 2 });
        return { body_html: "<p>보충 수업의 전체 공지 본문</p>", attachments: [] };
      }
      backgroundReads++;
      if (name === "get_home_course_index") {
        if (otherCourseNotices.has(args.course_id)) return {
          assignments: [], notices: [], counts: { assignment: 0 }, learning_activity: null, signature: `empty-course-${args.course_id}`,
        };
        lmsReads.push(name);
        return returningOverview ?? overview.promise;
      }
      if (name === "get_home_course_details") {
        if (otherCourseNotices.has(args.course_id)) return { assignments: [], stats: null };
        lmsReads.push(name);
        return returningBriefing?.promise ?? briefing.promise;
      }
      if (name === "get_course_timetable") {
        lmsReads.push(name);
        await (returningTimetable?.promise ?? timetable.promise);
        return { on_date: args.on_date, week_start: args.on_date, week_end: args.on_date, timezone: "Asia/Seoul", entries: [] };
      }
      if (name === "get_dorm_menu") {
        await otherScreens.promise;
        const dish = dormDishes[args.dorm];
        return { dorm: args.dorm, period: "week", on_date: args.on_date, week_start: args.on_date, week_end: args.on_date,
          days: [{ date: args.on_date, weekday: "", meals: { breakfast: dish, lunch: dish, dinner: dish }, notes: [] }] };
      }
      await otherScreens.promise;
      return { status: "error", message: "테스트의 백그라운드 응답" };
    }

    window = new BrowserWindow({ width: 1120, height: 730, show: false, webPreferences: {
      preload: join(root, "dist-desktop/desktop/preload.cjs"), sandbox: true, contextIsolation: true, nodeIntegration: false,
    } });
    const run = (code) => window.webContents.executeJavaScript(code);
    const waitFor = async (check, label) => {
      const deadline = Date.now() + 5000;
      while (Date.now() < deadline) {
        if (await check()) return;
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
      assert.fail(label);
    };
    screens = new ScreenData(request, (status) => {
      login?.sessionChanged();
      chat?.sessionChanged();
      window.webContents.send("ast:prefetch-status", status);
    }, { directory: (account) => directoryFor(account.key), busy: () => false });
    login = registerScreenActions(screens, request,
      (event) => { if (!closing) assert.equal(event.senderFrame, window.webContents.mainFrame); },
      (status) => window.webContents.send("ast:astra-login-status", status), activeDirectory, undefined,
      async (courseId, page) => { coursePageOpens.push({ courseId, page }); return true; });
    registerStudyFontSettings(event => assert.equal(event.senderFrame, window.webContents.mainFrame),
      activeDirectory, () => screens.confirmedSessionRevision);
    ipcMain.handle("ast:assignment-open", (_event, target) => { assignmentOpens.push(target); return true; });
    ipcMain.handle("ast:assignment-prepare", (_event, target, request, revision) => {
      assignmentPrepares.push({ target, request, revision });
      return true;
    });
    ipcMain.handle("ast:assignment-cancel-prepared", (_event, request) => { preparedAssignmentCancels.push(request); });
    ipcMain.handle("ast:assignment-show-prepared", async (_event, request) => {
      const prepared = assignmentPrepares.find((item) => item.request === request);
      const rowSelector = `[data-kind="assignment"][data-activity-id="${prepared?.target.assignmentId}"] > button`;
      const position = await run(`(() => {
        const pane = document.querySelector('.ast-main');
        const row = pane.querySelector(${JSON.stringify(rowSelector)});
        if (!row || pane.scrollTop === 0) return null;
        const bounds = pane.getBoundingClientRect();
        const target = row.getBoundingClientRect();
        return {
          visible: target.top >= bounds.top && target.bottom <= bounds.bottom,
          focused: document.activeElement === row,
          scrolled: pane.dataset.recommendationScrollEnded === 'true',
        };
      })()`);
      preparedAssignmentShows.push({ request, position });
      return true;
    });
    chat = createChatSession({ apiKey: "", getClient: () => { throw new Error("No provider in fixture"); },
      confirmedLmsSession: () => screens.confirmedSessionRevision, activeDirectory, window: () => window });
    const workspace = createChatWorkspace({
      screenData: screens,
      run: registerChatWorkspace(() => window, (event) => assert.equal(event.senderFrame, window.webContents.mainFrame)),
      openCoursePage: async () => false,
      openBrowser: () => false,
    });

    await window.loadFile(join(root, "dist/index.html"));
    await waitFor(() => run("document.querySelector('.astra-login-button')?.textContent === 'ASTRA로 로그인'"), "one branded sign-in button");
    assert.equal(await run("document.querySelectorAll('.astra-welcome button').length"), 1);
    assert.equal(await run("document.querySelector('.ast-workspace').inert"), true);
    assert.equal((await run("window.ast.getStudentProfile(0)")).status, "login_required");
    assert.equal((await run("window.ast.getCourseClassroom('1', 0)")).status, "login_required");
    assert.equal(profileReads, 0, "signed-out requests do not reach e-Class");
    assert.equal(await run("getComputedStyle(document.querySelector('.astra-welcome-mark .ast-wordmark-art')).animationDuration"), "11s");
    const welcomeLayout = () => run(`(() => {
      const background = document.querySelector('.astra-welcome-landscape');
      const { left, top, right, bottom } = background.getBoundingClientRect();
      const landscape = getComputedStyle(background);
      const center = getComputedStyle(document.querySelector('.astra-welcome-center'));
      const mark = document.querySelector('.astra-welcome-mark').getBoundingClientRect();
      const button = document.querySelector('.astra-login-button').getBoundingClientRect();
      const expectedMarkHeight = Math.min(132, Math.max(83, innerHeight * .14));
      return {
        canvasFillsWindow: left === 0 && top === 0 && right === innerWidth && bottom === innerHeight,
        edgeToEdgeHills: landscape.backgroundImage.includes('welcome-hills') &&
          landscape.backgroundSize.endsWith('cover') && landscape.borderWidth === '0px' && landscape.borderRadius === '0px',
        originalLoginPosition: Math.abs(parseFloat(center.top) - innerHeight * .37) < .1,
        originalWordmark: Math.abs(mark.height - expectedMarkHeight) < .1 && Math.abs(mark.width - mark.height * 2) < .1,
        buttonSize: [button.width, button.height].map((size) => Math.round(size * 10) / 10),
      };
    })()`);
    const expectedLayout = {
      canvasFillsWindow: true, edgeToEdgeHills: true, originalLoginPosition: true,
      originalWordmark: true, buttonSize: [212, 50],
    };
    assert.deepEqual(await welcomeLayout(), expectedLayout);
    const originalSize = window.getContentSize();
    window.setContentSize(960, 510);
    await waitFor(() => run("innerWidth === 960 && innerHeight === 510"), "welcome window resized");
    assert.deepEqual(await welcomeLayout(), expectedLayout);
    window.setContentSize(...originalSize);
    await waitFor(() => run(`innerWidth === ${originalSize[0]} && innerHeight === ${originalSize[1]}`), "welcome window restored");
    if (process.env.AST_WELCOME_SNAPSHOT) {
      const { writeFileSync } = await import("node:fs");
      await new Promise((resolve) => setTimeout(resolve, 700));
      const snapshot = await window.capturePage(undefined, { stayHidden: true });
      writeFileSync(process.env.AST_WELCOME_SNAPSHOT, snapshot.toPNG());
    }
    await run("document.querySelector('.astra-login-button').click()");
    await waitFor(() => run("document.querySelector('.astra-login-button').textContent === '로그인 다시 확인'"), "same button offers recheck");
    assert.equal(opened, 1);
    await run("document.querySelector('.astra-login-button').click()");
    await waitFor(() => rechecks > 0, "recheck inspected the existing browser attempt");
    assert.equal(opened, 1);
    assert.deepEqual(lmsReads, []);
    captured = true;
    await waitFor(() => confirmations === 1, "automatic capture starts official verification");
    await waitFor(() => run("document.querySelector('.astra-login-button').textContent === '로그인 중…'"), "detected login enters busy state");
    assert.equal(await run("getComputedStyle(document.querySelector('.astra-welcome-mark .ast-wordmark-art')).animationDuration"), "3.3s");

    assert.equal(await run("window.ast.saveStudentPreferences({ residence: 'kb', departmentId: 'computer' })"), null);
    verification.resolve();
    await waitFor(() => run("document.querySelector('.student-setup h1')?.textContent === '테스트학생님 안녕하세요!'"), "first login greets the verified user");
    assert.equal(await run("getComputedStyle(document.querySelector('.astra-welcome-mark .ast-wordmark-art')).animationDuration"), "11s");
    await waitFor(() => run(`(() => {
      const mark = document.querySelector('.astra-welcome-mark').getBoundingClientRect();
      const card = document.querySelector('.astra-setup-surface').getBoundingClientRect();
      return Math.abs(mark.top - Math.min(88, Math.max(46, innerHeight * .095))) < .5 &&
        card.top - mark.bottom >= 25 && card.width > 212;
    })()`), "logo settles with a larger gap above the setup card");
    assert.equal(await run("document.querySelector('input[name=language]')"), null);
    assert.equal(await run("document.querySelectorAll('input[name=residence]').length"), 6);
    assert.equal(await run("getComputedStyle(document.querySelector('.student-setup h2')).textAlign"), "center");
    assert.equal(await run("document.querySelector('.student-setup-next').disabled"), true);
    window.setContentSize(960, 540);
    await waitFor(() => run("innerWidth === 960 && innerHeight === 540"), "setup at minimum window size");
    assert.equal(await run(`(() => {
      const lastOption = document.querySelector('.student-setup-choices label:last-child').getBoundingClientRect();
      const list = document.querySelector('.student-setup-choices').getBoundingClientRect();
      const next = document.querySelector('.student-setup-next').getBoundingClientRect();
      return lastOption.bottom <= list.bottom && list.bottom < next.top && next.bottom < innerHeight;
    })()`), true);
    window.setContentSize(...originalSize);
    await run("document.querySelector('input[name=residence][value=seonglim]').click()");
    assert.equal(await run("getComputedStyle(document.querySelector('input[name=residence]:checked').parentElement).backgroundColor"), "rgb(6, 105, 214)");
    assert.match(await run("document.querySelector('.student-setup-next').textContent"), /설정 완료/);
    assert.equal(await run("document.querySelector('.student-setup-header p').textContent"), "1 / 1");
    assert.deepEqual(lmsReads, ["get_course_timetable"]);
    assert.ok(backgroundReads > lmsReads.length, "public tabs can load while the LMS lane is busy");
    assert.equal(await run("document.querySelector('.ast-entry-shell').dataset.entry"), "welcome", "first login still waits for setup");
    const revisionA = screens.confirmedSessionRevision;
    assert.equal(await run(`window.ast.saveStudentPreferences({ residence: 'kb', departmentId: 'unknown' }, ${revisionA})`), null);
    await run("document.querySelector('.student-setup-next').click()");
    await waitFor(() => run("document.querySelector('.ast-entry-shell').dataset.entry === 'entering'"), "saving setup starts logo flight while the detailed reads are pending");
    assert.equal(await run("!!document.querySelector('.student-setup-search')"), false, "a unique department skips the department question");
    const savedPreferences = { residence: "seonglim", departmentId: "computer" };
    assert.deepEqual(JSON.parse(readFileSync(join(directoryFor(keyA), "student-preferences.json"), "utf8")), savedPreferences);
    const flight = await run(`(() => {
      const mark = document.querySelector('.astra-welcome-mark');
      const target = document.querySelector('.ast-header-mark').getBoundingClientRect();
      const from = mark.getBoundingClientRect();
      return { x: target.left < from.left, y: target.top < from.top, moving: mark.getAnimations().some(a => a.effect.getKeyframes().some(f => f.transform?.includes('translate'))) };
    })()`);
    assert.deepEqual(flight, { x: true, y: true, moving: true });
    await waitFor(() => run("document.querySelector('.ast-entry-shell').dataset.entry === 'open'"), "home opens while detailed LMS data and chat are pending");
    assert.deepEqual(lmsReads, ["get_course_timetable"]);
    assert.match(await run("document.querySelector('.sketch-courses').textContent"), /테스트 강의/);
    assert.match(await run("document.querySelector('.sketch-next').textContent"), /수업을 확인하고 있어요/);
    assert.doesNotMatch(await run("document.querySelector('.ast-chat-pane').textContent"), /첫 번째 계정 채팅/);
    timetable.resolve();
    await waitFor(() => run("document.querySelector('.sketch-next').textContent.includes('오늘 수업이 없어요.')"), "current timetable fills in");
    assert.deepEqual(lmsReads.slice(0, 2), ["get_course_timetable", "get_home_course_index"]);
    const assignmentFixture = (id, title, days) => ({
      id, title, course_id: "1", course_name: "테스트 강의", submitted: false,
      due_at: new Date(Date.now() + days * 86_400_000).toISOString(),
    });
    const assignments = [
        assignmentFixture("11", "임박한 테스트 과제", 2),
        assignmentFixture("12", "어제 지난 테스트 과제", -1),
        assignmentFixture("13", "오래 지난 테스트 과제", -4),
        assignmentFixture("14", "다음 테스트 과제", 5),
    ];
    const initialOverview = { assignments: assignments.map(({ id, title, submitted }) => ({ id, title, submitted, signature: id })),
      counts: { assignment: 4 }, learning_activity: { completed: 2, total: 3 }, signature: "fixture-index", notices: [{
      id: "1", course_id: "1", course_name: "테스트 강의", title: "첫 화면 공지", created_at: new Date(Date.now() - 60_000).toISOString(),
    }] };
    overview.resolve(initialOverview);
    await waitFor(() => run(`document.querySelector('.sketch-notices[aria-label="최근 공지"]').textContent.includes('첫 화면 공지')`), "briefing fills in");
    assert.match(await run("document.querySelector('.sketch-deadlines').textContent"), /마감 시각을 확인하고 있어요/);
    briefing.resolve({ assignments: assignments.map((item) => ({ ...item, submitted_at: null })),
      stats: { counts: { files: 1 }, attendance: { present: 2 }, total_posts: null } });
    await waitFor(() => run("document.querySelector('.sketch-deadline strong')?.textContent === '임박한 테스트 과제'"), "detail fills in assignment deadlines");
    chatHistory.resolve({ turns: [], storageError: false });
    await waitFor(() => run("document.querySelector('.ast-chat-pane').textContent.includes('첫 번째 계정 채팅')"), "chat history appears independently");
    assert.equal(await run("document.querySelector('.chat-answer-text h4')?.textContent"), "테스트 답변");
    assert.equal(await run("document.querySelectorAll('.chat-answer-text ol > li').length"), 2);
    assert.equal(await run("document.querySelector('.chat-answer-text blockquote em')?.textContent"), "마감 안내");
    assert.equal(await run("getComputedStyle(document.querySelector('.chat-answer-text')).animationName"), "none", "restored chat stays still");
    assert.equal(await run("document.querySelector('.home-dashboard').textContent.includes('불러오는 중')"), false);
    assert.equal(await run("document.querySelector('.ast-workspace').inert"), false);
    assert.equal(await run("!!document.querySelector('.astra-login-button')"), false);
    assert.equal(await run("getComputedStyle(document.querySelector('.ast-header-mark')).visibility"), "visible");
    assert.equal(profileReads, 0, "opening the main app does not request contacts");
    const clickNavigation = async (label) => {
      const button = `[...document.querySelectorAll('.app-nav button')].find(button => button.textContent === ${JSON.stringify(label)})`;
      await run(`${button}.click()`);
      await waitFor(() => run(`${button}.matches('[aria-pressed="true"], [aria-current="page"]')`), `${label} is active`);
    };
    assert.deepEqual(await run(`[...document.querySelectorAll('.ast-navigation .app-nav')].map(nav =>
      nav.innerText.split('\\n').filter(Boolean))`),
    [["홈 화면", "내 강의실", "테스트 강의", "스페인어(1)", "시간표 및 캘린더", "공지 모아보기", "수업 공지", "대학생활 공지"],
      ["기숙사 식단", "내 정보", "설정"]]);
    const openBriefing = async () => {
      await clickNavigation("홈 화면");
      await run("document.querySelector('.sketch-deadlines .sketch-link').click()");
      await waitFor(() => run("document.querySelector('#briefing-title')?.checkVisibility()"), "home assignment link opens the briefing");
    };
    const showAssignmentSettings = () => clickNavigation("설정");
    await openBriefing();
    if (await run("!matchMedia('(prefers-reduced-motion: reduce)').matches")) {
      assert.deepEqual(await run(`[
        getComputedStyle(document.documentElement, '::view-transition-old(ast-screen)').animationDuration,
        getComputedStyle(document.documentElement, '::view-transition-new(ast-screen)').animationDuration,
      ]`), ["0.16s", "0.48s"], "the screen uses the reference exit and entrance timings");
    }
    const assignmentList = () => run("document.querySelector('.briefing-assignment-grid')?.textContent ?? ''");
    await waitFor(async () => (await assignmentList()).includes("임박한 테스트 과제"), "briefing shows an upcoming assignment");
    assert.doesNotMatch(await assignmentList(), /지난 테스트 과제/);
    await showAssignmentSettings();
    await waitFor(() => run("document.querySelector('.assignment-settings')?.checkVisibility()"), "assignment settings opens");
    assert.equal(await run("document.querySelector('.assignment-settings input[type=checkbox]').checked"), false);
    assert.equal(await run("document.querySelector('#assignment-overdue-days')?.disabled"), true);
    await run("document.querySelector('.assignment-settings input[type=checkbox]').click()");
    assert.equal(await run("document.querySelector('#assignment-overdue-days').value"), "7");
    await run(`(() => {
      const input = document.querySelector('#assignment-overdue-days');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '2');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('.assignment-settings button[type=submit]').click();
    })()`);
    await waitFor(() => run("!!document.querySelector('.assignment-settings footer [role=status]')"), "assignment setting saved");
    await openBriefing();
    await waitFor(async () => (await assignmentList()).includes("어제 지난 테스트 과제"), "briefing immediately shows the permitted overdue assignment");
    assert.doesNotMatch(await assignmentList(), /오래 지난 테스트 과제/);
    assert.deepEqual(JSON.parse(readFileSync(join(directoryFor(keyA), "assignment-settings.json"), "utf8")), { includeOverdue: true, overdueDays: 2 });
    await clickNavigation("홈 화면");
    assert.match(await run("document.querySelector('.sketch-overdue')?.textContent"), /D\+1.*어제 지난 테스트 과제/);
    await showAssignmentSettings();
    assert.equal(await run("document.querySelector('#assignment-overdue-days').value"), "2");
    await run("document.querySelector('.assignment-settings input[type=checkbox]').click(); document.querySelector('.assignment-settings button[type=submit]').click()");
    await waitFor(() => run("!!document.querySelector('.assignment-settings footer [role=status]')"), "assignment setting saved");
    await openBriefing();
    await waitFor(async () => !(await assignmentList()).includes("지난 테스트 과제"), "disabling the setting immediately hides overdue assignments");
    await clickNavigation("홈 화면");
    assert.equal(await run("!!document.querySelector('.sketch-overdue')"), false);
    const workspaceStyle = await run(`(() => {
      const sidebar = document.querySelector('.ast-navigation');
      const toggle = document.querySelector('.ast-sidebar-toggle');
      const icon = toggle.querySelector('.ast-sidebar-icon');
      const header = getComputedStyle(document.querySelector('.ast-chrome'));
      const workspace = getComputedStyle(document.querySelector('.ast-main'));
      const glass = getComputedStyle(sidebar);
      const outline = getComputedStyle(document.querySelector('.ast-workspace'), '::after');
      return {
        collapseControls: !!icon && parseFloat(getComputedStyle(icon).borderLeftWidth) > 0 &&
          parseFloat(getComputedStyle(icon, '::before').borderRightWidth) > 0 &&
          !toggle.textContent.trim() && !sidebar.textContent.includes('사이드바 접기'),
        lightHeader: header.backgroundColor === 'rgb(255, 255, 255)',
        outline: outline.borderWidth === '1px' && outline.borderColor === 'rgb(218, 218, 218)' &&
          workspace.borderTopLeftRadius === '12px' && workspace.borderTopRightRadius === '0px',
        gradient: workspace.backgroundImage.includes('rgb(189, 227, 255)') && workspace.backgroundImage.includes('rgb(255, 231, 231)'),
        glass: glass.backdropFilter === 'blur(11px)',
      };
    })()`);
    assert.deepEqual(workspaceStyle, { collapseControls: true, lightHeader: true, outline: true, gradient: true, glass: true });
    const roomySize = [1440, 900];
    window.setContentSize(...roomySize);
    const paneWidths = () => run(`['.ast-navigation', '.ast-main', '.ast-chat-pane'].map((selector) => Math.round(document.querySelector(selector).getBoundingClientRect().width))`);
    await waitFor(async () => (await paneWidths()).reduce((sum, width) => sum + width, 0) === 1440 && (await paneWidths())[0] === 158,
      "workspace has room to resize both panes");
    const [initialSidebar, , initialChat] = await paneWidths();
    const dragDivider = async (pane, delta) => {
      const point = await run(`(() => {
        const { x, y, width, height } = document.querySelector('.ast-pane-divider--${pane}').getBoundingClientRect();
        return { x: Math.round(x + width / 2), y: Math.round(y + height / 2) };
      })()`);
      const send = (type, x, buttons) => window.webContents.debugger.sendCommand("Input.dispatchMouseEvent",
        { type, x, y: point.y, button: "left", buttons, clickCount: 1 });
      assert.equal(await run(`document.elementFromPoint(${point.x}, ${point.y})?.classList.contains('ast-pane-divider--${pane}')`), true, `pointer hits ${pane} divider at ${JSON.stringify(point)}`);
      await send("mousePressed", point.x, 1);
      await waitFor(() => run(`document.querySelector('.ast-pane-divider--${pane}').dataset.dragging === 'true'`), `${pane} divider captures pointer`);
      await send("mouseMoved", point.x + delta, 1);
      await waitFor(async () => (await paneWidths())[pane === "sidebar" ? 0 : 2] !== (pane === "sidebar" ? initialSidebar : initialChat), `${pane} drag changes width`);
      await send("mouseReleased", point.x + delta, 0);
    };
    window.webContents.debugger.attach();
    try {
      await dragDivider("sidebar", 120);
      assert.equal((await paneWidths())[0], initialSidebar + 120, "drag widens sidebar");
      await dragDivider("chat", -100);
      assert.equal((await paneWidths())[2], initialChat + 100, "drag widens chat");
    } finally {
      window.webContents.debugger.detach();
    }
    const adjustedWidths = await paneWidths();
    window.webContents.debugger.attach();
    try {
      const point = await run(`(() => {
        const rect = document.querySelector('.ast-sidebar-toggle').getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
      })()`);
      for (const type of ["mousePressed", "mouseReleased"]) {
        await window.webContents.debugger.sendCommand("Input.dispatchMouseEvent", { type, ...point, button: "left", clickCount: 1 });
      }
      const toggleOutline = () => run(`(() => {
        const toggle = document.querySelector('.ast-sidebar-toggle');
        toggle.focus();
        return getComputedStyle(toggle).outlineStyle;
      })()`);
      assert.equal(await toggleOutline(), "none", "a pointer click leaves no focus outline");
      await window.webContents.debugger.sendCommand("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
      await window.webContents.debugger.sendCommand("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
      assert.equal(await toggleOutline(), "solid", "keyboard navigation can show focus again");
    } finally {
      window.webContents.debugger.detach();
    }
    await waitFor(() => run("document.querySelector('.ast-navigation').hidden && document.querySelector('.ast-sidebar-toggle').getAttribute('aria-expanded') === 'false'"), "sidebar closes from its icon");
    assert.equal(await run("document.querySelector('.ast-pane-divider--sidebar') === null"), true);
    assert.equal(await run("document.querySelector('.ast-navigation').inert"), true);
    await waitFor(async () => (await paneWidths())[0] === 0, "sidebar finishes closing");
    assert.ok((await paneWidths())[1] > adjustedWidths[1]);
    if (await run("!matchMedia('(prefers-reduced-motion: reduce)').matches")) {
      const moving = await run(`(async () => {
        const sidebar = document.querySelector('.ast-navigation');
        const workspace = document.querySelector('.ast-workspace');
        document.querySelector('.ast-sidebar-toggle').click();
        await new Promise(requestAnimationFrame);
        const motion = workspace.getAnimations().find((animation) => animation.transitionProperty === 'grid-template-columns');
        if (!motion) return null;
        motion.currentTime = 100;
        return { width: sidebar.getBoundingClientRect().width, duration: motion.effect.getTiming().duration };
      })()`);
      assert.ok(moving && moving.duration === 320 && moving.width > 0 && moving.width < adjustedWidths[0],
        "the sidebar expands through intermediate widths over 320 ms");
    } else {
      await run("document.querySelector('.ast-sidebar-toggle').click()");
    }
    await waitFor(() => run("!document.querySelector('.ast-navigation').hidden && document.querySelector('.ast-sidebar-toggle').getAttribute('aria-expanded') === 'true'"), "sidebar reopens from its icon");
    await waitFor(async () => (await paneWidths())[0] === adjustedWidths[0], "sidebar finishes reopening");
    assert.deepEqual(await paneWidths(), adjustedWidths);
    window.webContents.debugger.attach();
    try {
      await window.webContents.debugger.sendCommand("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
      await openBriefing();
      assert.equal(await run("document.documentElement.matches(':active-view-transition-type(ast-screen)')"), false, "reduced motion skips the tab transition");
      await run("document.querySelector('.ast-sidebar-toggle').click()");
      await waitFor(async () => (await paneWidths())[0] === 0, "reduced motion closes the sidebar immediately");
      assert.equal(await run("document.querySelector('.ast-workspace').hasAttribute('data-sidebar-moving')"), false);
      await run("document.querySelector('.ast-sidebar-toggle').click()");
      await clickNavigation("홈 화면");
    } finally {
      await window.webContents.debugger.sendCommand("Emulation.setEmulatedMedia", { features: [] });
      window.webContents.debugger.detach();
    }
    window.setContentSize(960, 540);
    await waitFor(async () => (await paneWidths())[1] === 380, "narrow window protects the main panel width");
    window.setContentSize(...roomySize);
    await waitFor(async () => (await paneWidths()).every((width, i) => width === adjustedWidths[i]), "wider window restores pane widths");
    await run("document.querySelector('.ast-pane-divider--chat').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }))");
    await waitFor(async () => (await paneWidths())[2] === adjustedWidths[2] - 10, "arrow key narrows chat");
    assert.equal(await run("document.querySelector('#dashboard-title').textContent"), "테스트학생님, 반가워요!");
    assert.equal(await run("document.querySelectorAll('.ast-search input').length"), 1);
    assert.deepEqual(await run(`(async () => {
      const icon = document.querySelector('.ast-search--header img');
      await icon.decode();
      return [icon.width, icon.height];
    })()`), [17, 17]);
    assert.match(await run("document.querySelector('.sketch-courses').textContent"), /테스트 강의.*2 \/ 3 완료/);
    assert.equal(await run("document.querySelectorAll('.sketch-meal-tabs button').length"), 3);
    assert.equal(screens.status.state, "loading", "workspace opens while other tabs are still loading");
    otherScreens.resolve();
    await waitFor(() => screens.status.state === "partial", "background queries finish independently");
    await waitFor(() => ["2", "3", "4"].every((id) => indexedBodyReads.includes(id)), "all courses are indexed before opening the screen");
    const allCourseNotices = ".app-nav > button[aria-pressed]";
    await run(`[...document.querySelectorAll('${allCourseNotices}')].find(button => button.textContent.trim() === '공지 모아보기').click()`);
    await waitFor(() => run("document.querySelector('#course-notice-index-title')?.checkVisibility()"), "the parent opens course notices");
    const searchCourseNotices = (value) => run(`(() => {
      const input = document.querySelector('input[aria-label="수업 공지 검색"]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(value)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await waitFor(() => run("document.querySelectorAll('.course-notice-index-row').length === 6"), "notices from both regular courses are shown by default");
    const beforeSearch = listedCourseNotices;
    const courseTags = '[aria-label="과목 필터"] button';
    const tagLabels = () => run(`[...document.querySelectorAll(${JSON.stringify(courseTags)})].map(button => button.textContent.trim())`);
    const selectedTag = () => run(`document.querySelector(${JSON.stringify(courseTags + '[aria-pressed="true"]')}).textContent.trim()`);
    const courseTag = (name) => `[...document.querySelectorAll(${JSON.stringify(courseTags)})].find(button => button.textContent.trim() === ${JSON.stringify(name)})`;
    const tagLayout = (name) => run(`(async () => {
      const tag = ${courseTag(name)};
      await Promise.allSettled(tag.getAnimations({ subtree: true }).map(animation => animation.finished));
      const { left, width, height } = tag.getBoundingClientRect();
      const label = tag.lastElementChild.getBoundingClientRect();
      return {
        width, height,
        centered: Math.abs(label.left + label.width / 2 - (left + width / 2)) < 0.5,
        hasCheck: getComputedStyle(tag.querySelector('img')).opacity === '1',
      };
    })()`);
    const pressCourseTag = (name, measureMotion = false) => run(`(async () => {
      const tag = ${courseTag(name)};
      tag.focus();
      tag.click();
      if (!${measureMotion}) return;
      await new Promise(requestAnimationFrame);
      const expansion = tag.firstElementChild.getAnimations()[0];
      if (!expansion) return null;
      expansion.currentTime = expansion.effect.getTiming().duration / 2;
      return tag.getBoundingClientRect().width;
    })()`);
    assert.deepEqual(await tagLabels(), ["전체", "테스트 강의", secondCourse.name]);
    assert.equal(await selectedTag(), "전체");
    const allSelected = await tagLayout("전체");
    const courseUnselected = await tagLayout(secondCourse.name);
    assert.ok(allSelected.hasCheck && courseUnselected.centered && !courseUnselected.hasCheck);
    assert.deepEqual(await run(`(() => {
      const rows = [...document.querySelectorAll('.course-notice-index-meta')];
      const courseStarts = new Set(rows.map(row => row.firstElementChild.getBoundingClientRect().left));
      const dateEnds = new Set(rows.map(row => row.querySelector('time').getBoundingClientRect().right));
      return [courseStarts.size, dateEnds.size];
    })()`), [1, 1], "course names and dates align across notice cards");
    const expandingWidth = await pressCourseTag(secondCourse.name, true);
    assert.equal(await selectedTag(), secondCourse.name);
    const courseSelected = await tagLayout(secondCourse.name);
    const allUnselected = await tagLayout("전체");
    assert.ok(courseSelected.width > courseUnselected.width && courseSelected.hasCheck, "selecting a course makes room for a check");
    assert.ok(allUnselected.width < allSelected.width && allUnselected.centered && !allUnselected.hasCheck, "deselecting all centers the label and removes the check space");
    assert.equal(courseSelected.height, courseUnselected.height);
    assert.equal(allUnselected.height, allSelected.height);
    if (await run("!matchMedia('(prefers-reduced-motion: reduce)').matches")) {
      assert.ok(expandingWidth > courseUnselected.width && expandingWidth < courseSelected.width, "the tag grows through an intermediate width");
    }
    assert.deepEqual(await run("[...document.querySelectorAll('.course-notice-index-row strong')].map(row => row.textContent)"), [secondCourseNotice.title]);
    await searchCourseNotices("본문 전용 검색어");
    assert.equal(await run("document.querySelectorAll('.course-notice-index-row').length"), 0, "search stays within the selected course");
    await pressCourseTag("전체");
    assert.deepEqual(await tagLayout("전체"), allSelected, "all expands again when selected");
    assert.equal(await run("document.querySelector('input[aria-label=\"수업 공지 검색\"]').value"), "본문 전용 검색어", "changing the course retains the search text");
    await waitFor(() => run("document.querySelectorAll('.course-notice-index-row').length === 1 && document.querySelector('.course-notice-index-row strong')?.textContent === '추가 안내'"), "search finds a match in an older notice's cached body");
    await run("document.querySelector('.course-notice-index-row').click()");
    assert.match(await run("document.querySelector('.course-notice-index-reader .course-notice-body').textContent"), /세미나실/);
    assert.equal(listedCourseNotices, beforeSearch, "local search and reading do not query the LMS");

    await searchCourseNotices("수업 공지 본문 3");
    assert.equal(await run("document.querySelectorAll('.course-notice-index-row').length"), 0, "all excludes non-regular notice bodies by default");
    const nonRegularToggle = "document.querySelector('.settings-course-notices input[type=checkbox]')";
    const setNonRegularNotices = async (checked) => {
      await clickNavigation("설정");
      await waitFor(() => run(`${nonRegularToggle} && !${nonRegularToggle}.disabled`), "course notice preference is ready");
      assert.equal(await run(`${nonRegularToggle}.checked`), !checked);
      await run(`${nonRegularToggle}.click()`);
      await waitFor(() => run(`${nonRegularToggle}.checked === ${checked} && !${nonRegularToggle}.disabled`), "course notice preference is saved");
      assert.deepEqual(JSON.parse(readFileSync(join(directoryFor(keyA), "course-notice-settings.json"), "utf8")), { includeNonRegular: checked });
      await clickNavigation("수업 공지");
    };
    await setNonRegularNotices(true);
    assert.deepEqual(await tagLabels(), ["전체", "테스트 강의", secondCourse.name, nonRegularCourse.name]);
    assert.equal(await run("document.querySelector('.course-notice-index-row strong')?.textContent"), nonRegularNotice.title);
    window.setContentSize(960, 540);
    await waitFor(() => run("innerWidth === 960"), "course tags in a narrow window");
    assert.deepEqual(await run(`(() => {
      const strip = document.querySelector('.course-notice-index-tag-scroll');
      const buttons = [...document.querySelectorAll(${JSON.stringify(courseTags)})];
      const fixedTag = buttons[0];
      const left = fixedTag.getBoundingClientRect().left;
      const sameRow = new Set(buttons.map(button => button.getBoundingClientRect().top)).size === 1;
      strip.scrollLeft = strip.scrollWidth;
      return [sameRow, strip.scrollLeft > 0, fixedTag.getBoundingClientRect().left === left];
    })()`), [true, true, true], "course tags scroll on one line while the all tag stays fixed");
    window.setContentSize(...roomySize);
    await waitFor(() => run(`innerWidth === ${roomySize[0]}`), "notice screen returns to its original width");
    await searchCourseNotices("");
    await pressCourseTag(nonRegularCourse.name);
    assert.equal(await selectedTag(), nonRegularCourse.name);
    await run("document.querySelector('.course-notice-index-row').click()");
    await setNonRegularNotices(false);
    assert.equal(await selectedTag(), "전체", "hiding the selected course returns to all courses");
    assert.deepEqual(await tagLabels(), ["전체", "테스트 강의", secondCourse.name]);
    assert.equal(await run("document.querySelectorAll('.course-notice-index-row').length"), 6);
    assert.equal(await run("document.querySelector('#course-notice-index-reader-title')"), null);
    assert.equal(listedCourseNotices, beforeSearch, "changing the preference filters cached notices");

    await searchCourseNotices("");
    noticeAdded = true;
    const previousBodies = indexedBodyReads.length;
    await run("document.querySelector('.course-notice-index-refresh').click()");
    await waitFor(() => run("document.querySelector('.course-notice-index-row strong')?.textContent === '새로 올라온 수업 공지'"), "refresh adds a newly posted notice");
    await waitFor(() => indexedBodyReads.length > previousBodies, "the newly posted notice is indexed");
    assert.deepEqual(indexedBodyReads.slice(previousBodies), ["9"]);
    await setNonRegularNotices(true);
    await clickNavigation("홈 화면");
    noticeAdded = false;
    if (process.env.AST_HOME_SNAPSHOT) {
      const { writeFileSync } = await import("node:fs");
      window.setContentSize(1800, 1100);
      await waitFor(() => run("innerWidth === 1800 && innerHeight === 1100"), "Figma reference viewport");
      const snapshot = await window.capturePage(undefined, { stayHidden: true });
      writeFileSync(process.env.AST_HOME_SNAPSHOT, snapshot.toPNG());
    }
    const courseHeading = () => run("document.querySelector('#course-room-title')?.textContent");
    const recommendedAssignment = ".sketch-greeting button";
    assert.match(await run(`document.querySelector('${recommendedAssignment}').textContent`), /임박한 테스트 과제/);
    await run(`document.querySelector('${recommendedAssignment}').click()`);
    await waitFor(async () => await courseHeading() === "테스트 강의", "the home recommendation opens the assignment's classroom");
    await waitFor(() => assignmentPrepares.length === 1, "the recommendation prepares the assignment browser while weekly activities load");
    await clickNavigation("홈 화면");
    await waitFor(() => preparedAssignmentCancels.length === 1, "leaving the course cancels the prepared window");
    assert.equal(preparedAssignmentCancels[0], assignmentPrepares[0].request);
    const motionEnabled = await run("!matchMedia('(prefers-reduced-motion: reduce)').matches");
    if (motionEnabled) {
      await run(`(() => {
        const style = document.createElement('style');
        style.id = 'pause-recommendation-transition';
        style.textContent = '::view-transition-new(ast-screen) { animation-play-state: paused !important; }';
        document.head.append(style);
      })()`);
    }
    const secondDeadlineCard = ".sketch-deadlines .sketch-deadline:nth-child(2)";
    assert.match(await run(`document.querySelector('${secondDeadlineCard}').textContent`), /다음 테스트 과제/);
    await run(`document.querySelector('${secondDeadlineCard}').click()`);
    await waitFor(async () => await courseHeading() === "테스트 강의", "the second deadline card opens its classroom");
    await waitFor(() => assignmentPrepares.length === 2, "the deadline card prepares the browser while weekly activities load");
    const { target, request: preparedRequest, revision: preparedRevision } = assignmentPrepares[1];
    assert.deepEqual(target, { courseId: "1", assignmentId: "14" });
    assert.equal(preparedRevision, revisionA);
    assert.equal(assignmentOpens.length, 0);
    assert.equal(preparedAssignmentShows.length, 0);
    assert.equal(await run("document.documentElement.matches(':active-view-transition-type(ast-screen)')"), motionEnabled,
      "the deadline card uses the screen transition when motion is enabled");
    await run(`(() => {
      const pane = document.querySelector('.ast-main');
      pane.addEventListener('scrollend', () => {
        pane.dataset.recommendationScrollEnded = 'true';
      }, { once: true });
    })()`);
    courseActivities.resolve({ weeks: [
      { number: 1, date_label: "9월 1일 ~ 9월 7일", activities: [
        { id: "51", kind: "material", title: "주차별 테스트 자료", status: "complete", details: null, due_at: null, url: activityUrl },
      ] },
      ...Array.from({ length: 13 }, (_, index) => ({ number: index + 2, date_label: null, activities: [] })),
      { number: 15, date_label: null, activities: [
        { id: "11", kind: "assignment", title: "주차별 테스트 과제", status: "not_submitted", details: null, due_at: null, url: null },
        { id: "14", kind: "assignment", title: "다음 테스트 과제", status: "not_submitted", details: null, due_at: null, url: null },
      ] },
    ], open_boards: [{ id: "21", title: "열린게시판" }] });
    if (motionEnabled) {
      await waitFor(() => run("!!document.querySelector('[data-kind=assignment][data-activity-id=\"14\"]')"), "the target loads during the transition");
      await run("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
      assert.equal(await run("document.querySelector('.ast-main').scrollTop"), 0, "the classroom stays at the top while the transition plays");
      assert.equal(preparedAssignmentShows.length, 0, "the browser stays hidden during the transition");
      await run("document.getElementById('pause-recommendation-transition').remove()");
    }
    await waitFor(() => preparedAssignmentShows.length === 1, "the prepared browser is requested after classroom scrolling");
    assert.deepEqual(preparedAssignmentShows[0], { request: preparedRequest, position: { visible: true, focused: true, scrolled: true } });

    const actionSignal = new AbortController().signal;
    assert.deepEqual(await workspace.dispatch("ast_navigate", { screen: "timetable" }, actionSignal),
      { status: "ok", screen: "timetable" });
    assert.equal(await run("document.querySelector('#ast-sidebar button[aria-pressed=true]')?.textContent"), "시간표 및 캘린더");
    assert.equal((await workspace.dispatch("ast_lookup_workspace", { course_id: "1" }, actionSignal)).assignments.at(-1).week, 15);
    assert.equal((await workspace.dispatch("ast_open_assignment", { course_id: "2", assignment_id: "14" }, actionSignal)).status, "error");
    const action = workspace.dispatch("ast_open_assignment", { course_id: "1", assignment_id: "14" }, actionSignal);
    await waitFor(() => assignmentPrepares.length === 3, "the agent prepares the browser while moving to the classroom");
    const agentRequest = assignmentPrepares[2].request;
    assert.equal(preparedAssignmentShows.length, 1, "the agent's prepared window stays hidden during navigation");
    await run(`document.querySelector('.ast-main').addEventListener('scrollend', ({ currentTarget }) => {
      currentTarget.dataset.recommendationScrollEnded = 'true';
    }, { once: true })`);
    assert.deepEqual(await action, { status: "ok", title: "다음 테스트 과제" });
    assert.deepEqual(preparedAssignmentShows[1], { request: agentRequest, position: { visible: true, focused: true, scrolled: true } });
    if (motionEnabled) {
      await clickNavigation("홈 화면");
      await run(`(() => {
        const style = document.createElement('style');
        style.id = 'pause-agent-transition';
        style.textContent = '::view-transition-new(ast-screen) { animation-play-state: paused !important; }';
        document.head.append(style);
      })()`);
      const abort = new AbortController();
      const stopped = workspace.dispatch("ast_open_assignment", { course_id: "1", assignment_id: "14" }, abort.signal);
      await waitFor(() => assignmentPrepares.length === 4, "the stopped agent request prepared its browser");
      abort.abort();
      assert.equal((await stopped).status, "error");
      await waitFor(() => preparedAssignmentCancels.includes(assignmentPrepares[3].request), "stopping the agent discards its prepared browser");
      await run("document.getElementById('pause-agent-transition').remove()");
      assert.equal(preparedAssignmentShows.length, 2);
    }

    await clickNavigation("홈 화면");
    await clickNavigation("내 강의실");
    await run("document.querySelector('.course-entry').click()");
    await waitFor(async () => await courseHeading() === "테스트 강의", "a course card opens the native course classroom");
    await waitFor(() => run("document.querySelectorAll('.course-room-notice-row').length === 3"), "the classroom only shows the latest three notices");
    await waitFor(() => run("document.querySelectorAll('.course-room-activity').length === 3"), "the course shows its weekly activities");
    await waitFor(() => run("document.querySelectorAll('.course-room-meetings tbody tr').length === 3"), "the course header shows its meetings");
    assert.equal(await run("document.querySelector('.course-room-code').textContent"), "123456-31001");
    assert.deepEqual(await run("[...document.querySelectorAll('.course-room-meetings tbody tr')].map(row => [...row.cells].map(cell => cell.textContent))"), [
      ["월요일 09:00–10:30", "예시관 101"], ["수요일 14:00–15:30", "예시 실습관 202"], ["금요일 3 ~ 4교시", "미확인"],
    ]);
    assert.equal(await run(`(() => {
      const title = document.querySelector('.course-room-identity').getBoundingClientRect();
      const info = document.querySelector('.course-room-info').getBoundingClientRect();
      const tabs = document.querySelector('.course-room-tab-strip').getBoundingClientRect();
      return info.left > title.right && info.top === title.top && Math.abs(info.right - tabs.right) <= 1;
    })()`), true, "the schedule uses the right side of the course header");
    assert.match(await run("document.querySelector('.course-room-week').textContent"), /1주차.*9월 1일.*주차별 테스트 자료.*완료/);
    assert.match(await run("document.querySelector('.course-room-week:last-child').textContent"), /15주차.*주차별 테스트 과제.*미제출/);
    const courseWindowSize = window.getContentSize();
    window.setContentSize(960, 540);
    await waitFor(() => run("innerWidth === 960 && !!document.querySelector('[aria-label=\"다음 과목 메뉴 보기\"]:enabled')"), "course tabs overflow in a narrow pane");
    assert.equal(await run(`(() => {
      const title = document.querySelector('.course-room-identity').getBoundingClientRect();
      const info = document.querySelector('.course-room-info').getBoundingClientRect();
      return info.top > title.bottom && Math.abs(info.left - title.left) <= 1;
    })()`), true, "the schedule moves below the title in a narrow pane");
    await run("document.querySelector('[aria-label=\"다음 과목 메뉴 보기\"]').click()");
    await waitFor(() => run("document.querySelector('.course-room-tabs').scrollLeft > 0"), "the right arrow scrolls the course tabs");
    assert.equal(await run(`(() => {
      const viewport = document.querySelector('.course-room-tabs').getBoundingClientRect();
      const button = document.querySelector('.course-room-tabs button').getBoundingClientRect();
      return button.top > viewport.top && button.bottom < viewport.bottom;
    })()`), true, "tab buttons have space above and below the horizontal scrollbar");
    assert.equal(await run("document.querySelector('.ast-main').scrollWidth <= document.querySelector('.ast-main').clientWidth + 1"), true);
    window.setContentSize(...courseWindowSize);
    const openTab = (label) => run(`document.querySelector(${JSON.stringify(`[aria-label="${label} 새 창에서 열기"]`)}).click()`);
    await openTab("출석");
    await waitFor(() => coursePageOpens.length === 1, "the attendance tab requests a course browser window");
    assert.deepEqual(coursePageOpens[0], { courseId: "1", page: { kind: "attendance" } });
    assert.equal(await courseHeading(), "테스트 강의", "a web tab leaves the native classroom open");
    await openTab("열린게시판");
    await waitFor(() => coursePageOpens.length === 2, "the open board uses the selected course's board ID");
    assert.deepEqual(coursePageOpens[1], { courseId: "1", page: { kind: "open_board", boardId: "21" } });
    assert.equal(await run(`window.ast.openCoursePage('1', {kind: 'open_board', boardId: '999'}, ${revisionA})`), false);
    assert.equal(await run(`window.ast.openCoursePage('1', {kind: 'grades'}, ${revisionA - 1})`), false);
    await run("document.querySelector('[aria-label=\"주차별 테스트 자료 열기\"] .course-room-activity-heading').click()");
    await waitFor(() => coursePageOpens.length === 3, "a verified activity link requests a course browser window");
    assert.deepEqual(coursePageOpens[2], { courseId: "1", page: { kind: "activity", activityId: "51", url: activityUrl } });
    await run("document.querySelector('[aria-label=\"주차별 테스트 과제 과제 하러 가기\"]').click()");
    await waitFor(() => assignmentOpens.length === 1, "the assignment calls the existing assignment browser");
    assert.deepEqual(assignmentOpens[0], { courseId: "1", assignmentId: "11" });

    await run("[...document.querySelectorAll('.course-room button')].find(button => button.textContent.includes('전체 공지 보기')).click()");
    await waitFor(async () => await courseHeading() === "전체 공지", "the full list is a separate course screen");
    await waitFor(() => run("document.querySelectorAll('.course-room-notice-row').length === 4"), "the archive shows notices beyond the latest three");
    await run("[...document.querySelectorAll('.course-room-pagination button')].find(button => button.textContent === '다음').click()");
    await waitFor(() => run("document.querySelector('.course-room-notice-row')?.textContent.includes('추가 안내')"), "the archive opens the next notice page");
    await run(`(() => {
      const input = document.querySelector('input[placeholder="제목 및 본문 검색"]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '보충 수업');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.form.requestSubmit();
    })()`);
    await waitFor(() => run("document.querySelector('.course-room-search-status')?.textContent.includes('검색 결과 1개')"), "body search continues through an empty first result page");
    await run("document.querySelector('.course-room-notice-row').click()");
    await waitFor(() => run("document.querySelector('.course-notice-body')?.textContent.includes('전체 공지 본문')"), "a result opens the rich notice body from its source page");
    await run("document.querySelector('.notice-dialog').close()");

    const openProfileFromAccount = () => run(`(async () => {
      document.querySelector('.ast-account-trigger').click();
      await new Promise(requestAnimationFrame);
      [...document.querySelectorAll('.ast-account-panel button')].find(button => button.textContent === '내 정보').click();
    })()`);
    await openProfileFromAccount();
    const profileText = () => run("document.querySelector('.my-profile')?.textContent ?? ''");
    await waitFor(async () => (await profileText()).includes("profile@example.test"), "profile shows the signed-in user's contact information");
    assert.match(await profileText(), /테스트학생.*컴퓨터 공학과.*2학년.*010-0000-0000.*profile@example.test.*테스트 강의/);
    assert.equal(profileReads, 1);
    await clickNavigation("홈 화면");
    await clickNavigation("내 정보");
    await waitFor(async () => (await profileText()).includes("profile@example.test"), "profile opens from the sidebar");
    assert.equal(profileReads, 1, "the same verified session reuses the profile in memory");
    assert.doesNotMatch(readFileSync(join(directoryFor(keyA), "screen-cache.json"), "utf8"), /profile@example.test/);

    const openDormMenu = () => run("[...document.querySelectorAll('.ast-navigation button')].find(button => button.textContent.includes('기숙사 식단')).click()");
    const diningHall = () => run("document.querySelector('.dorm-menu-choices [aria-pressed=true]')?.textContent.trim()");
    await openDormMenu();
    await waitFor(async () => await diningHall() === "성림학사", "the dining view starts with the saved residence");
    const diningPeriod = () => run("document.querySelector('[aria-label=\"식단 조회 기간\"] [aria-pressed=true]')?.textContent");
    assert.equal(await diningPeriod(), "이번 주", "the dining view defaults to the weekly menu");
    await run("[...document.querySelectorAll('[aria-label=\"식단 조회 기간\"] button')].find(button => button.textContent === '오늘').click()");
    await clickNavigation("홈 화면");
    await run("document.querySelector('.sketch-meals .sketch-link').click()");
    await waitFor(() => run("document.querySelector('#settings-title')?.checkVisibility()"), "the dining change link opens settings");
    assert.match(await run("document.querySelector('.settings-account').textContent"), /ASTRA 연결.*e-Class 연결됨/);
    assert.equal(await run("document.querySelector('.settings-preferences-form [name=language]')"), null);
    const loginMode = () => run("document.querySelector('input[name=keep-login]:checked')?.value");
    await waitFor(async () => await loginMode() === "true", "keeping the session is the default");
    await run("document.querySelector('input[name=keep-login][value=false]').click()");
    await waitFor(async () => await loginMode() === "false", "the fresh login setting saves through IPC");
    assert.deepEqual(await run("window.ast.getLoginSettings()"), { keepLogin: false });
    assert.equal((await run("window.ast.getAstraLoginStatus()")).state, "authenticated", "the new setting applies at startup");
    const changePreferences = (residence = "surim") => run(`(() => {
      const { elements } = document.querySelector('.settings-preferences-form');
      for (const [name, value] of Object.entries({ departmentId: 'electrical', residence: ${JSON.stringify(residence)} })) {
        elements[name].value = value;
        elements[name].dispatchEvent(new Event('change', { bubbles: true }));
      }
    })()`);
    await changePreferences();
    await run("document.querySelector('.settings-preferences-form button[type=reset]').click()");
    assert.equal(await run("document.querySelector('.settings-preferences-form select[name=residence]').value"), "seonglim");
    assert.deepEqual(await run("window.ast.getStudentPreferences()"), savedPreferences, "reset discards the draft");
    await changePreferences();
    await run("document.querySelector('.settings-preferences-form button[type=submit]').click()");
    const editedPreferences = { residence: "surim", departmentId: "electrical" };
    await waitFor(() => run("!!document.querySelector('.settings-preferences-form [role=status]')"), "preferences saved from the settings page");
    assert.deepEqual(await run("window.ast.getStudentPreferences()"), editedPreferences);

    await run("document.querySelector('.assignment-settings input[type=checkbox]').click(); document.querySelector('.assignment-settings button[type=submit]').click()");
    await waitFor(() => run("!!document.querySelector('.assignment-settings footer [role=status]')"), "assignment setting saved from the settings page");
    await clickNavigation("홈 화면");
    assert.equal(await run("document.querySelector('.sketch-meal-dorm').textContent"), "수림학사");
    for (const [residence, hall, dish] of [
      ["none", null, null],
      ["nuri", "성림학사", dormDishes.seonglim],
      ["buram", "KB학사", dormDishes.kb],
      ["surim", "수림학사", dormDishes.surim],
    ]) {
      await clickNavigation("설정");
      await changePreferences(residence);
      await run("document.querySelector('.settings-preferences-form button[type=submit]').click()");
      await waitFor(() => run("!!document.querySelector('.settings-preferences-form [role=status]')"), `${residence} preference saved`);
      await clickNavigation("홈 화면");
      if (!hall) {
        assert.equal(await run("document.querySelector('.sketch-meals')"), null, "the home meal card is absent for non-residents");
        continue;
      }
      assert.equal(await run("document.querySelector('.sketch-meal-dorm')?.textContent"), hall);
      await waitFor(async () => await run("document.querySelector('.sketch-meal-item')?.textContent") === dish, `${residence} shows its assigned dining hall's meal`);
      await openDormMenu();
      await waitFor(async () => await diningHall() === hall, `${residence} defaults to its assigned dining hall in the menu view`);
      await clickNavigation("홈 화면");
    }
    assert.match(await run("document.querySelector('.sketch-overdue')?.textContent"), /어제 지난 테스트 과제/);
    await openDormMenu();
    await waitFor(() => run("document.querySelector('#dorm-menu-title')?.checkVisibility()"), "the previously opened dining view is active");
    assert.equal(await diningHall(), "수림학사");
    assert.equal(await diningPeriod(), "오늘", "the dining view keeps the selected period after a preference change");
    await run("document.querySelector('[aria-label=\"학사 선택\"] button:last-child').click()");
    await clickNavigation("홈 화면");
    await waitFor(() => run("!!document.querySelector('.sketch-meal-item')"), "the home dining preview shows a dish");
    await run("document.querySelector('.sketch-meal-item').click()");
    await waitFor(() => run("document.querySelector('#dorm-menu-title')?.checkVisibility()"), "a dish opens the dining view");
    assert.equal(await diningHall(), "수림학사", "the home shortcut selects the saved residence");
    assert.equal(await diningPeriod(), "이번 주", "the home shortcut opens the weekly menu");
    assert.equal(await run("document.querySelector('[aria-label=\"학사 선택\"] button:first-child').textContent.trim()"), "수림학사");

    writeFileSync(join(directoryFor(keyA), "student-preferences.json"), JSON.stringify({ ...editedPreferences, language: "en" }) + "\n");
    await window.loadFile(join(root, "dist/index.html"));
    await waitFor(() => run("document.querySelector('.ast-entry-shell')?.dataset.entry === 'open'"), "legacy preferences skip setup on reopening");
    assert.equal(await run("!!document.querySelector('.student-setup')"), false);
    assert.deepEqual(await run("window.ast.getStudentPreferences()"), editedPreferences, "legacy language is omitted from IPC");
    assert.deepEqual(await run("window.ast.getAssignmentSettings()"), { includeOverdue: true, overdueDays: 2 });
    await openDormMenu();
    await waitFor(async () => await diningHall() === "수림학사", "saved residence selects the dining hall");
    assert.equal((await run("window.ast.getChatTranscript()")).turns[0].question, "첫 번째 계정 채팅");
    await clickNavigation("설정");
    await waitFor(async () => await loginMode() === "false", "the login setting survives reopening the renderer");
    await run("document.querySelector('input[name=keep-login][value=true]').click()");
    await waitFor(async () => await loginMode() === "true", "keeping the session can be restored");
    const relogin = async () => {
      await clickNavigation("설정");
      await run("document.querySelector('.settings-account button').click()");
    };
    await openProfileFromAccount();
    await waitFor(async () => (await profileText()).includes("profile@example.test"), "profile remains available after reopening the window");
    const replacement = deferred();
    pendingProfile = replacement;
    await run("document.querySelector('.my-profile-header button').click()");
    await waitFor(() => profileReads === 2, "refresh starts a new profile request");
    assert.match(await profileText(), /profile@example.test/);
    const staleProfileRead = screens.readStudentProfile(revisionA, false);
    nextAccount = { account_key: keyB, display_name: "다른학생", student_profile: { department: "자유전공학부", year: 1 } };
    await relogin();
    assert.equal((await staleProfileRead).status, "login_required", "account change rejects an in-flight profile response");
    replacement.resolve({ display_name: "테스트학생", phone: "010-0000-0000", email: "old-account@example.test" });
    pendingProfile = undefined;
    await waitFor(() => run("!document.querySelector('.my-profile')"), "old profile is cleared on account change");
    await waitFor(() => run("document.querySelector('.student-setup h1')?.textContent === '다른학생님 안녕하세요!'"), "a different account gets its own first-run setup");
    assert.equal(await run("window.ast.getStudentPreferences()"), null);
    assert.deepEqual(await run(`window.ast.getCourseNoticeSettings(${screens.confirmedSessionRevision})`), { includeNonRegular: false },
      "a new account keeps the default course notice preference");
    assert.equal((await run("window.ast.getChatTranscript()")).turns[0].question, "두 번째 계정 채팅");
    assert.equal(await run(`window.ast.saveStudentPreferences(${JSON.stringify(savedPreferences)}, ${revisionA})`), null);
    const savedB = { residence: "none", departmentId: "computer" };
    assert.equal(await run("document.querySelector('.student-setup-header p').textContent"), "1 / 2");
    await run("document.querySelector('input[name=residence][value=none]').click(); document.querySelector('.student-setup-next').click()");
    await waitFor(() => run("!!document.querySelector('input[name=department]')"), "second account department step");
    assert.equal(await run("document.querySelector('.student-setup-header p').textContent"), "2 / 2");
    assert.equal(await run("document.querySelector('input[name=department]:checked')"), null);
    assert.equal(await run("document.querySelector('.student-setup-next').disabled"), true);
    await run(`(() => {
      const input = document.querySelector('.student-setup-search');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, "컴퓨터 공학");
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await waitFor(() => run("document.querySelectorAll('input[name=department]').length === 1"), "department search ignores spaces");
    assert.match(await run("document.querySelector('.student-setup-departments').textContent"), /컴퓨터공학과/);
    await run("document.querySelector('input[name=department][value=computer]').click()");
    assert.equal(await run("document.querySelector('.student-setup-next').disabled"), false);
    assert.deepEqual(await run(`window.ast.saveStudentPreferences(${JSON.stringify(savedB)}, ${screens.confirmedSessionRevision})`), savedB);
    nextAccount = { account_key: keyA, display_name: "테스트학생", course_roster: initialRoster };
    returningTimetable = deferred();
    returningOverview = { ...initialOverview,
      assignments: initialOverview.assignments.map((item) => item.id === "11" ? { ...item, title: "수정된 테스트 과제", signature: "updated-11" } : item) };
    returningBriefing = deferred();
    await run("window.ast.startAstraLogin()");
    await waitFor(() => run("document.querySelector('.ast-entry-shell')?.dataset.entry === 'open'"), "returning account skips setup and opens before the overview is ready");
    assert.equal(await run("!!document.querySelector('.student-setup')"), false);
    assert.match(await run("document.querySelector('.sketch-courses').textContent"), /테스트 강의/);
    assert.match(await run("document.querySelector('.sketch-courses').textContent"), /2 \/ 3 완료/);
    assert.match(await run("document.querySelector('.sketch-notices').textContent"), /첫 화면 공지/);
    const deadlineCard = () => run("document.querySelector('.sketch-deadline')?.textContent");
    assert.match(await deadlineCard(), /임박한 테스트 과제/);
    const readsBeforeRefresh = lmsReads.length;
    returningTimetable.resolve();
    await waitFor(() => lmsReads.slice(readsBeforeRefresh).includes("get_home_course_details"), "returning account is checking the changed deadline");
    assert.match(await deadlineCard(), /임박한 테스트 과제/);
    assert.doesNotMatch(await deadlineCard(), /수정된 테스트 과제/);
    returningBriefing.resolve({ assignments: [{ ...assignmentFixture("11", "수정된 테스트 과제", 3), signature: "updated-11", submitted_at: null }], stats: null });
    await waitFor(async () => (await deadlineCard())?.includes("수정된 테스트 과제"), "the saved card updates after details arrive");
    assert.deepEqual(await run("window.ast.getStudentPreferences()"), editedPreferences);
    assert.deepEqual(await run(`window.ast.getCourseNoticeSettings(${screens.confirmedSessionRevision})`), { includeNonRegular: true },
      "the returning account keeps its saved course notice preference");
    assert.equal((await run("window.ast.getChatTranscript()")).turns[0].question, "첫 번째 계정 채팅");
    await waitFor(() => screens.status.state !== "loading", "returning account refresh finishes");
    const pdfCalls = [];
    ipcMain.handle("ast:focus-library", () => ({ ok: true, value: { version: 1, items: [] } }));
    ipcMain.handle("ast:focus-pdf-import", (_event, revision, folderId) => {
      pdfCalls.push({ revision, folderId });
      return { ok: true, value: null };
    });
    await run("document.querySelector('.ast-mode-switch button:last-child').click()");
    await waitFor(() => run("!!document.querySelector('#focus-home-title')"), "focus home opens");
    for (const [kind, title, features] of [
      ["explain", "PDF로 강의 해설 보기", ["강의 해설", "개념 정리와 N제", "AI 멘토"]],
      ["practice", "PDF로 N제 만들기", ["개념 완성 N제", "이해 확인 N제", "실전 N제", "암기 확인 N제"]],
    ]) {
      await run(`document.querySelector('.focus-study[data-task="${kind}"] > button').click()`);
      await waitFor(() => run("!!document.querySelector('.focus-files > dialog:modal')"), "study guide opens inside My Files");
      assert.equal(await run("document.querySelector('.focus-navigation [aria-current=page]').textContent"), "내 파일");
      assert.equal(await run("document.querySelector('#focus-files-title').textContent"), "내 파일");
      assert.equal(await run("document.querySelector('.focus-dialog h2').textContent"), title);
      assert.deepEqual(await run("[...document.querySelectorAll('.focus-study-guide dt')].map(name => name.textContent)"), features);
      assert.match(await run("document.querySelector('.focus-study-guide').textContent"), /PDF 가져오기.*PDF를 누르면 AST 학습 프로그램이 자동으로 열려요/);
      assert.equal(pdfCalls.length, 0, "the home shortcut does not immediately open a file picker");
      const dismiss = kind === "explain" ? ".focus-dialog-actions button" : ".focus-dialog button[aria-label=닫기]";
      await run(`document.querySelector('${dismiss}').click()`);
      await waitFor(() => run("!document.querySelector('.focus-files > dialog')"), "dismissing the guide keeps My Files open");
      await run("document.querySelector('.focus-navigation button:first-of-type').click()");
      await waitFor(() => run("!!document.querySelector('#focus-home-title')"), "return to focus home");
    }
    await run("document.querySelector('.focus-navigation button:nth-of-type(2)').click()");
    await waitFor(() => run("!!document.querySelector('.focus-files .focus-primary:enabled')"), "direct My Files navigation enables import");
    assert.equal(await run("!!document.querySelector('.focus-files > dialog')"), false);
    await run("document.querySelector('.focus-files .focus-primary').click()");
    await waitFor(() => pdfCalls.length === 1, "My Files still opens its existing PDF import");
    assert.deepEqual(pdfCalls, [{ revision: screens.confirmedSessionRevision, folderId: null }]);
    console.log("PASS: first login, home warmup, pane controls, course navigation and notice search, account-isolated settings and chats, and My Files study guides");
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    closing = true;
    login?.shutdown();
    await screens?.shutdown();
    window?.destroy();
    rmSync(profile, { recursive: true, force: true });
    app.exit(process.exitCode ?? 0);
  }
}
void main();
