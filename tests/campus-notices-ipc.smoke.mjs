// Run after npm run build. AST_NOTICE_LIVE=1 checks the public school site.
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, ipcMain, session, shell } from "electron";
import { createLmsConnector } from "../dist-desktop/desktop/lms-connector.js";
import { registerAssignmentWindows } from "../dist-desktop/desktop/assignment-windows.js";
import { AssignmentWebSession } from "../dist-desktop/desktop/assignment-web-session.js";
import { LmsAccess } from "../dist-desktop/desktop/lms-access.js";
import { registerScreenActions } from "../dist-desktop/desktop/screen-controller.js";
import { ScreenData } from "../dist-desktop/desktop/screen-data.js";
import { saveStudentPreferences } from "../dist-desktop/desktop/student-preferences.js";
import { campusNoticeKey } from "../dist-desktop/shared/campus-notices.js";
import { campusNoticeTags } from "../dist-desktop/shared/campus-notice-tags.js";
import { departmentNoticeSources } from "../dist-desktop/shared/seoultech-department-notices.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const profile = mkdtempSync(join(tmpdir(), "ast-campus-ipc-"));
const live = process.env.AST_NOTICE_LIVE === "1";
const applicationUrl = "https://example.test/ast-fixture-application";
const sameTabUrl = "https://example.test/ast-fixture-details";
const noContentUrl = "https://example.test/ast-fixture-no-content";
const preferences = { residence: "none", departmentId: "computer" };
const fallbackPreferences = { ...preferences, departmentId: "open-information" };
const { college, department } = departmentNoticeSources(preferences.departmentId);
assert.ok(college && department);
app.setPath("userData", profile);
app.disableHardwareAcceleration();

const fixture = [
  { board: "notice", board_id: "4691", id: "1", title: "겨울 프로그램 안내", published_at: "2026-11-13", content: "교환학생과 함께 부산을 여행하는 문화 체험 행사예요. 부산표본 검색 문구가 본문에 있어요.\n\n신청 마감: 2026년 11월 20일(금)\n지원 대상: 재학생\n겨울 프로그램에 참여할 학부생은 안내 자료에서 신청 기간과 참가 방법을 확인해 주세요. 일정이 바뀌면 학교 공지로 다시 알려 드려요." },
  { board: "matters", board_id: "57139", id: "2", title: "수강신청 안내", published_at: "2025-07-09", content: "수강신청과 수강 정정 방법을 안내해요." },
  { board: "janghak", board_id: "57138", id: "3", title: "국가근로장학 안내", published_at: "2026-11-12", content: "근로장학금 신청 안내예요. 장학표본 검색 문구가 본문에 있어요." },
  { board: "janghak", board_id: "57138", id: "4", title: "지난 장학금 안내", published_at: "2026-10-30", content: "장학금 추가 지급에 관한 예전 공지예요." },
  { board: "notice", board_id: "4691", id: "5", title: "고정 운영 안내", published_at: "2026-11-14", pinned: true, content: "이번 학기 동안 목록 상단에서 확인할 수 있어요." },
  { board: "notice", board_id: "4691", id: "6", title: "교내 네트워크 점검 및 실습실 이용 시간 변경 안내", published_at: "2026-11-12", content: "교내 네트워크 점검 일정을 안내해요." },
].map(({ board, board_id, id, title, content, published_at, pinned = false }) => ({
  board, board_id, id, title, content, published_at, pinned, department: "예시 부서",
  has_attachments: id === "1", attachments: id === "1" ? [{ id: "100", name: "예시 안내.pdf" }] : [], images: [],
  links: id === "1" ? [{ url: applicationUrl, text: "테스트 신청 페이지" }] : [],
  url: `https://www.seoultech.ac.kr/service/info/${board}?do=commonview&bnum=${board_id}&bidx=${id}`,
}));

const departmentFixture = [
  { source: college, board_id: "2836", id: "11", title: "정보통신대학 안내", content: "학사 운영과 신입생 학사일정 소식이에요." },
  { source: department, board_id: "58476", id: "12", title: "컴퓨터공학과 인턴십 안내", content: "현장실습 설명회에서 산학표본 단어를 확인하세요." },
].map(({ source, board_id, id, title, content }) => ({
  board: source.id, board_id, id, title, content, published_at: "2026-11-13", department: source.label,
  pinned: false, has_attachments: false, attachments: [], images: [],
  url: `${source.listUrl}?do=commonview&bnum=${board_id}&bidx=${id}`,
}));

async function waitFor(check, message, timeout = 8000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.fail(message);
}

let window;
let screens;
let connector;
const calls = [];
const openedUrls = [];
const externalUrls = [];
const run = (code) => window.webContents.executeJavaScript(code);
const browserState = (browser) => browser.webContents.executeJavaScript("window.assignmentBrowser?.getAssignmentBrowser()");
const pageView = (browser, id) => browser.contentView.children.find((child) => child.webContents?.id === id);
const primaryTabs = '[aria-label="공지 게시판"] button';
const sourceButtons = '[aria-label="소속 공지 게시판"] button';
const topicButtons = '[aria-label="공지 주제"] button';
const noticeSearchField = 'input[aria-label="공지 검색"]';
const readingPane = ".campus-notices article.notice-reading-pane";
const timeline = ".campus-notices .notice-timeline";
const splitter = '.notice-splitter[role="separator"]';

async function setSearch(selector, value) {
  await run(`(() => {
    const field = document.querySelector(${JSON.stringify(selector)});
    field.focus();
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(field, ${JSON.stringify(value)});
    field.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);
}

async function expectPageReveal(browser, url, asset) {
  await waitFor(() => asset.requested, "the page requested its delayed asset");
  const state = await browserState(browser);
  assert.equal(state.url, url);
  assert.equal(state.initialLoad, true, "the loading surface stays up while an asset is pending");
  const overlay = browser.contentView.children.at(-1);
  assert.notEqual(overlay, pageView(browser, state.activeTabId));
  const contents = overlay.webContents;
  await waitFor(() => contents.getURL().endsWith("/web-loading/index.html") && overlay.getBounds().width > 0, "the handwriting overlay is ready");
  assert.deepEqual(overlay.getBounds(), pageView(browser, state.activeTabId).getBounds());
  assert.equal(await contents.executeJavaScript(`(() => {
    const mark = document.querySelector(".web-loading-mark");
    return !!mark && getComputedStyle(mark).maskImage.includes("ast-wordmark") &&
      !mark.parentElement.classList.contains("is-revealing");
  })()`), true);
  asset.finish.resolve();
  await waitFor(() => contents.executeJavaScript(`getComputedStyle(document.querySelector(".web-loading-screen"))
    .maskImage.startsWith("linear-gradient(135deg")`), "the finished page begins the diagonal reveal");
  await waitFor(() => contents.isDestroyed(), "the transition removes the overlay");
  assert.equal((await browserState(browser)).initialLoad, false);
}

const click = (selector, title) => run(`(() => {
  const button = [...document.querySelectorAll(${JSON.stringify(selector)})].find((item) => item.textContent.trim() === ${JSON.stringify(title)});
  if (!button) throw Error("missing button " + ${JSON.stringify(title)});
  button.click();
})()`);

async function verifyFilterSelection(selector, title) {
  const { before, during, after, all, reducedMotion } = await run(`(async () => {
    const filters = [...document.querySelectorAll(${JSON.stringify(selector)})];
    const button = filters.find((item) => item.textContent.trim() === ${JSON.stringify(title)});
    const all = filters.find((item) => item.textContent.trim() === '전체');
    const layout = (filter) => {
      const { left, width, height } = filter.getBoundingClientRect();
      const label = filter.lastElementChild.getBoundingClientRect();
      return {
        width, height,
        centered: Math.abs(left + width / 2 - label.left - label.width / 2) < 0.5,
        checkVisible: getComputedStyle(filter.querySelector('img')).opacity === '1',
      };
    };
    const before = layout(button);
    button.click();
    await new Promise(requestAnimationFrame);
    const expansion = button.querySelector('.notice-filter-check').getAnimations()[0];
    let during;
    if (expansion) {
      expansion.currentTime = expansion.effect.getTiming().duration / 2;
      during = layout(button).width;
    }
    await Promise.allSettled([button, all].flatMap((filter) => filter.getAnimations({ subtree: true }).map((motion) => motion.finished)));
    return { before, during, after: layout(button), all: layout(all), reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches };
  })()`);
  assert.ok(before.centered && !before.checkVisible && all.centered && !all.checkVisible, "unselected filters center their labels");
  assert.ok(after.width > before.width && after.height === before.height && after.checkVisible, "selection grows sideways to show the check");
  if (!reducedMotion) assert.ok(during > before.width && during < after.width, "selection animates through an intermediate width");
}

const inRows = (title) => run(`[...document.querySelectorAll(".notice-list strong")].some((item) => item.textContent.includes(${JSON.stringify(title)}))`);
const inExcerpt = (text) => run(`[...document.querySelectorAll(".notice-result-excerpt")].some((item) => item.textContent.includes(${JSON.stringify(text)}))`);
const sourceLabels = () => run(`[...document.querySelectorAll(${JSON.stringify(sourceButtons)})].map((button) => button.textContent.trim())`);
const selectNotice = (title) => run(`(() => {
  const row = [...document.querySelectorAll(".campus-notices .notice-row")]
    .find((item) => item.querySelector("strong")?.textContent.trim() === ${JSON.stringify(title)});
  if (!row) throw Error("missing notice row " + ${JSON.stringify(title)});
  row.click();
})()`);
const readingContains = (text) => run(`document.querySelector(${JSON.stringify(readingPane)})?.textContent.includes(${JSON.stringify(text)})`);
const isShown = (selector) => run(`(() => {
  const element = document.querySelector(${JSON.stringify(selector)});
  return !!element?.getClientRects().length && getComputedStyle(element).visibility === "visible";
})()`);

async function resize(width, height) {
  window.setContentSize(width, height);
  await waitFor(() => run(`innerWidth === ${width} && innerHeight === ${height}`), `notice window resized to ${width} × ${height}`);
}

const pointIn = (selector) => run(`(() => {
  const { left, top, width, height } = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
  return { x: Math.round(left + width / 2), y: Math.round(top + Math.min(height / 2, 15)) };
})()`);

async function withPointer(work) {
  const debuggerConnection = window.webContents.debugger;
  debuggerConnection.attach("1.3");
  try {
    await work((type, point, extra = {}) => debuggerConnection.sendCommand("Input.dispatchMouseEvent", { type, ...point, ...extra }));
  } finally {
    debuggerConnection.detach();
  }
}

const splitLayout = () => run(`(() => {
  const control = document.querySelector(${JSON.stringify(splitter)});
  return {
    value: Number(control.getAttribute("aria-valuenow")),
    min: Number(control.getAttribute("aria-valuemin")),
    max: Number(control.getAttribute("aria-valuemax")),
    listWidth: document.querySelector(${JSON.stringify(timeline)}).getBoundingClientRect().width,
    detailWidth: document.querySelector(${JSON.stringify(readingPane)}).getBoundingClientRect().width,
  };
})()`);

const moveSplitter = (key, shiftKey = false) => run(`(() => {
  const control = document.querySelector(${JSON.stringify(splitter)});
  control.focus();
  control.dispatchEvent(new KeyboardEvent("keydown", { key: ${JSON.stringify(key)}, shiftKey: ${shiftKey}, bubbles: true, cancelable: true }));
})()`);

async function verifySplitter() {
  await waitFor(() => isShown(splitter), "the wide layout exposes a splitter");
  const start = await splitLayout();
  assert.ok(start.min > 0 && start.min < start.value && start.value < start.max);
  assert.equal(await run(`document.querySelector(${JSON.stringify(splitter)}).getAttribute("aria-label")`), "공지 목록 너비");
  await withPointer(async (mouse) => {
    const point = await pointIn(splitter);
    assert.equal(await run(`!!document.elementFromPoint(${point.x}, ${point.y})?.closest(${JSON.stringify(splitter)})`), true,
      "pointer hits the notice splitter");
    const right = { ...point, x: point.x + 70 };
    await mouse("mousePressed", point, { button: "left", buttons: 1, clickCount: 1 });
    await mouse("mouseMoved", right, { button: "left", buttons: 1 });
    await mouse("mouseReleased", right, { button: "left", buttons: 0, clickCount: 1 });
    await waitFor(async () => {
      const current = await splitLayout();
      return current.value > start.value && current.listWidth > start.listWidth + 20 && current.detailWidth < start.detailWidth - 20;
    }, "dragging right widens the list and narrows the reader");
  });

  const dragged = await splitLayout();
  await moveSplitter("ArrowLeft");
  await waitFor(async () => Math.abs((await splitLayout()).listWidth - (dragged.listWidth - 10)) <= 1, "left arrow narrows the list by 10 px");
  await moveSplitter("ArrowRight");
  await waitFor(async () => Math.abs((await splitLayout()).listWidth - dragged.listWidth) <= 1, "right arrow restores the list width");
  await moveSplitter("ArrowLeft", true);
  await waitFor(async () => Math.abs((await splitLayout()).listWidth - (dragged.listWidth - 40)) <= 1, "Shift+Left narrows the list by 40 px");

  await moveSplitter("Home");
  await waitFor(async () => (await splitLayout()).value === start.min, "Home moves the splitter to its minimum");
  const minimum = await splitLayout();
  await moveSplitter("ArrowLeft");
  assert.deepEqual(await splitLayout(), minimum, "keyboard cannot move past the minimum width");
  await moveSplitter("End");
  await waitFor(async () => (await splitLayout()).value === start.max, "End moves the splitter to its maximum");
  const maximum = await splitLayout();
  await moveSplitter("ArrowRight");
  assert.deepEqual(await splitLayout(), maximum, "keyboard cannot move past the maximum width");
  assert.ok(maximum.listWidth > minimum.listWidth && maximum.detailWidth > 0 && minimum.detailWidth > maximum.detailWidth,
    "both panes keep usable width at either divider limit");
}

async function verifyWorkspaceSplitters() {
  for (const [side, key] of [["sidebar", "ArrowRight"], ["chat", "ArrowLeft"]]) {
    const selector = `.ast-pane-divider--${side}`;
    const width = () => run(`Number(document.querySelector(${JSON.stringify(selector)}).getAttribute("aria-valuenow"))`);
    const press = (key) => run(`document.querySelector(${JSON.stringify(selector)}).dispatchEvent(
      new KeyboardEvent("keydown", { key: ${JSON.stringify(key)}, bubbles: true, cancelable: true }))`);
    const initial = await width();
    await press(key);
    await waitFor(async () => await width() === initial + 10, `${side} widens in the expected direction`);
    await press(key === "ArrowRight" ? "ArrowLeft" : "ArrowRight");
    await waitFor(async () => await width() === initial, `${side} returns to its initial width`);
  }
}

async function verifyTimeline() {
  await resize(1800, 1100);
  await waitFor(() => isShown(readingPane), "wide layout displays the first regular notice automatically");
  assert.equal(await readingContains(fixture[0].title), true, "a newer pinned notice does not replace the initial reading pane");
  assert.equal(await run('document.querySelector(".notice-pinned")?.open'), false, "pinned notices start collapsed");
  const groups = await run(`[...document.querySelectorAll(".notice-date-group")].map((group) => {
    const date = group.querySelector("time[datetime]");
    const marker = date.parentElement.getBoundingClientRect();
    const label = date.getBoundingClientRect();
    return {
      date: date.dateTime, label: date.innerText,
      visible: date.checkVisibility({ opacityProperty: true }) && label.left >= marker.left && label.right <= marker.right,
      titles: [...group.querySelectorAll(".notice-row strong")].map((title) => title.textContent.trim()),
    };
  })`);
  assert.deepEqual(groups.map(({ date }) => date), ["2026-11-13", "2026-11-12", "2025-07-09"]);
  assert.ok(groups.every(({ visible }) => visible), "full dates are visible within the timeline without hovering");
  assert.match(groups[0].label, /2026년 11월\s+13일 \(금\)/);
  assert.match(groups[2].label, /2025년 7월\s+9일 \(수\)/);
  assert.deepEqual(groups[0].titles, [fixture[0].title]);
  assert.deepEqual(groups[1].titles.sort(), [fixture[2].title, fixture[5].title].sort(), "notices sharing a date use one group");
  assert.deepEqual(groups[2].titles, [fixture[1].title]);
  assert.equal(await run(`(() => {
    const list = document.querySelector(${JSON.stringify(timeline)}).getBoundingClientRect();
    const reader = document.querySelector(${JSON.stringify(readingPane)}).getBoundingClientRect();
    return list.width > 0 && reader.width > 0 && list.right <= reader.left + 1;
  })()`), true, "the timeline and reader are side by side in the wide layout");
  assert.equal(await run(`(() => {
    const row = document.querySelector(".notice-boards").getBoundingClientRect();
    const school = document.querySelector(".notice-school-tabs button:last-child").getBoundingClientRect();
    const department = document.querySelector(".notice-affiliation-tab").getBoundingClientRect();
    return department.right >= row.right - 1 && department.left - school.right > 16;
  })()`), true, "the department tab is separated at the trailing edge");

  await run('document.querySelector(".notice-pinned summary").click()');
  await waitFor(() => run('document.querySelector(".notice-pinned")?.open === true'), "pinned accordion opens");
  await selectNotice(fixture[4].title);
  await waitFor(() => readingContains(fixture[4].content), "pinned notice can be read in the inline pane");
  await selectNotice(fixture[0].title);
  await waitFor(() => readingContains("부산표본"), "regular notice can be reselected");
  const application = await run(`[...document.querySelectorAll(${JSON.stringify(`${readingPane} .notice-application div`)})].map((item) => [
    item.querySelector("dt").textContent, item.querySelector("dd").textContent,
  ])`);
  assert.deepEqual(application, [["신청 마감", "2026년 11월 20일(금)"], ["지원 대상", "재학생"]]);
  assert.equal(await run('!!document.querySelector("dialog[open]")'), false, "timeline selection does not open a dialog");
  assert.equal(await run(`(() => {
    const icons = [...document.querySelectorAll(".campus-notices img[alt='']")].filter((icon) => icon.getClientRects().length);
    return Promise.all(icons.map((icon) => icon.decode().then(() =>
      icon.width === icon.naturalWidth && icon.height === icon.naturalHeight &&
      icon.naturalWidth > 0 && new URL(icon.src).protocol === "file:"))).then((checks) =>
      checks.length >= 12 && checks.every(Boolean));
  })()`), true, "the Figma icons render from local files at their original sizes");
  await run('document.querySelector(".notice-pinned summary").click()');

  if (process.env.AST_NOTICE_SNAPSHOT) {
    await run("document.fonts.ready.then(() => true)");
    await waitFor(() => readingContains("부산표본"), "the reading pane is ready for capture");
    await run("new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
    assert.equal(window.isVisible(), false);
    const snapshot = await window.capturePage(undefined, { stayHidden: true });
    assert.equal(snapshot.isEmpty(), false);
    assert.equal(window.isVisible(), false);
    writeFileSync(process.env.AST_NOTICE_SNAPSHOT, snapshot.toPNG());
  }
  await verifySplitter();
  await verifyWorkspaceSplitters();
}

async function verifyNarrowNotice() {
  const previousSize = window.getContentSize();
  await resize(960, 700);
  await waitFor(async () => await isShown(timeline) && !await isShown(readingPane), "narrow layout starts in the timeline");
  assert.equal(await isShown(splitter), false, "a one-pane layout does not show a splitter");
  assert.deepEqual(await run(`[...document.querySelectorAll('.notice-school-tabs, .notice-topic-tabs')].map((strip) => {
    const all = strip.previousElementSibling.querySelector('button');
    const { left, top } = all.getBoundingClientRect();
    strip.scrollLeft = strip.scrollWidth;
    return strip.scrollLeft > 0 && all.getBoundingClientRect().left === left &&
      [...strip.children].every((button) => button.getBoundingClientRect().top === top);
  })`), [true, true], "board and topic filters scroll on one line with All fixed");
  await selectNotice(fixture[0].title);
  await waitFor(async () => await isShown(readingPane) && !await isShown(timeline) && await readingContains("부산표본"),
    "narrow layout replaces the timeline with the selected cached body");
  await click(`${readingPane} button`, "목록으로");
  await waitFor(async () => await isShown(timeline) && !await isShown(readingPane), "back restores the narrow timeline");
  await waitFor(() => run('document.activeElement?.matches(".notice-row")'), "back restores focus to the previously selected row");
  assert.equal(await run(`document.querySelector(${JSON.stringify(noticeSearchField)}).value`), "부산표본", "back restores the current search");
  assert.equal(await inRows(fixture[0].title), true);
  assert.equal(await inRows(fixture[1].title), false);
  assert.equal(await run("document.querySelector('.ast-main').scrollWidth <= document.querySelector('.ast-main').clientWidth + 1"), true,
    "narrow notice content has no horizontal overflow");
  await resize(...previousSize);
  await waitFor(async () => await isShown(timeline) && await isShown(readingPane), "restoring width shows both panels");
}

function bodyOnlyExample(notices, entries) {
  return notices.flatMap((notice) => {
    const entry = entries[campusNoticeKey(notice)];
    if (!entry?.tags.length) return [];
    const metadata = notice.title + (notice.department ?? "") + entry.detail.title + (entry.detail.department ?? "");
    const word = entry.detail.content.match(/[가-힣]{4,12}/g)?.find((value) => !metadata.includes(value));
    return word ? [{ notice, tag: entry.tags[0], word }] : [];
  })[0];
}

async function openNoticeScreen() {
  await window.loadFile(join(root, "dist/index.html"));
  await waitFor(() => run("document.querySelector('.ast-entry-shell')?.dataset.entry === 'open'"), "app opens");
  await click(".app-nav button", "대학생활 공지");
  await waitFor(() => run(`!!document.querySelector(${JSON.stringify(noticeSearchField)})`), "notice search renders");
}

async function verifyDepartmentNotices() {
  await setSearch(noticeSearchField, "");
  if (await run(`document.querySelector(".notice-clear-tags") !== null`)) {
    await click(topicButtons, "주제 선택 해제");
  }
  await click(primaryTabs, "학과 공지");
  assert.deepEqual(await sourceLabels(), [college.label, department.label]);
  assert.equal(await run(`document.querySelectorAll(${JSON.stringify(sourceButtons)})[1].getAttribute("aria-pressed")`), "true");

  let snapshot;
  await waitFor(async () => {
    snapshot = await run('window.ast.getCampusNoticeIndex(undefined, "department")');
    return !snapshot.loading && snapshot.listedBoards.includes(college.id) && snapshot.listedBoards.includes(department.id) &&
      Object.values(snapshot.entries).some(({ detail }) => detail.board === department.id);
  }, "department and college lists and department body are indexed", live ? 150_000 : 8000);
  const example = live ? bodyOnlyExample(snapshot.notices.filter(({ board }) => board === department.id), snapshot.entries)
    : { notice: departmentFixture[1], tag: "career", word: "산학표본" };
  assert.ok(example, "the registered department has a classified notice with a body-only search term");
  assert.ok(snapshot.entries[campusNoticeKey(example.notice)].tags.includes(example.tag));
  const reads = () => calls.filter((name) => name === "get_department_notice").length;
  const readsAfterIndex = reads();
  await click(topicButtons, campusNoticeTags[example.tag]);
  await setSearch(noticeSearchField, example.word);
  await waitFor(async () => await inRows(example.notice.title) && await inExcerpt(example.word), "department tag and body-only query show matching excerpt");
  await selectNotice(example.notice.title);
  await waitFor(() => readingContains(example.word), "opens indexed department body in the reading pane");
  if (!live) {
    await click(`${readingPane} a.notice-reading-original`, "원문 열기");
    await waitFor(() => openedUrls.at(-1) === departmentFixture[1].url, "opens the selected department article");
  }
  await setSearch(noticeSearchField, "");
  await click(topicButtons, "주제 선택 해제");
  await click(sourceButtons, college.label);
  const collegeExample = snapshot.notices.find(({ board }) => board === college.id);
  assert.ok(collegeExample, "registered college has a notice");
  await waitFor(() => inRows(collegeExample.title), "college list can be selected");
  assert.equal(await inRows(example.notice.title), false);
  await click(sourceButtons, department.label);
  await waitFor(() => inRows(example.notice.title), "department source restores the cached list");
  assert.equal(reads(), readsAfterIndex);
  await click(primaryTabs, "전체");
  await waitFor(async () => (await sourceLabels()).length === 0 && !await inRows(example.notice.title), "school All excludes department rows");
  const schoolSnapshot = await run('window.ast.getCampusNoticeIndex(undefined, "school")');
  assert.ok(schoolSnapshot.notices.length > 0);
  assert.ok(schoolSnapshot.notices.every(({ board }) => !board.includes(":")));

  const currentRevision = screens.confirmedSessionRevision;
  const saved = await run(`window.ast.saveStudentPreferences(${JSON.stringify(fallbackPreferences)}, ${currentRevision})`);
  assert.deepEqual(saved, fallbackPreferences);
  assert.deepEqual(departmentNoticeSources(fallbackPreferences.departmentId), { college, department: undefined });
  const prohibited = await run(`window.ast.listCampusNotices(${JSON.stringify(department.id)}, 1).then(() => false, () => true)`);
  assert.equal(prohibited, true, "former department cannot be queried after changing the saved preference");
  await openNoticeScreen();
  await click(primaryTabs, "학과 공지");
  assert.deepEqual(await sourceLabels(), [college.label]);
  await waitFor(() => inRows(collegeExample.title), "fallback shows only the verified college board");
  assert.equal(await inRows(example.notice.title), false);
  assert.equal(reads(), readsAfterIndex);
}

async function main() {
  try {
    await app.whenReady();
    app.dock?.hide();
    if (!live) shell.openExternal = async (url) => { externalUrls.push(url); };
    session.defaultSession.webRequest.onBeforeRequest({ urls: ["http://*/*", "https://*/*"] }, (_, callback) => callback({ cancel: true }));
    if (live) connector = createLmsConnector(root, join(profile, "lms"));
    const request = async (name, args, ...rest) => {
      if (name === "list_campus_notices" || name === "get_campus_notice" ||
          name === "list_department_notices" || name === "get_department_notice") {
        calls.push(name);
        if (live) return connector.requestTool(name, args, ...rest);
        if (name === "list_campus_notices") return {
          board: args.board,
          notices: fixture.filter((item) => item.board === args.board && args.start_page === (item.id === "4" ? 4 : 1))
            .map(({ content, attachments, images, ...item }) => item),
          next_page: args.board === "janghak" && args.start_page === 1 ? 4 : null,
        };
        if (name === "list_department_notices") return {
          board: args.source_id,
          notices: departmentFixture.filter((item) => item.board === args.source_id && args.start_page === 1)
            .map(({ content, attachments, images, ...item }) => item),
          next_page: null,
        };
        if (name === "get_department_notice") {
          return departmentFixture.find((item) => item.board === args.source_id && item.board_id === args.board_id && item.id === args.notice_id)
            ?? { status: "error", message: "fixture" };
        }
        return fixture.find((item) => item.board === args.board && item.id === args.notice_id) ?? { status: "error", message: "fixture" };
      }
      return { status: "error", message: "Test fixture does not load other screens." };
    };
    screens = new ScreenData(request, () => {}, { directory: () => profile, busy: () => false, publicDirectory: profile });
    await saveStudentPreferences(preferences, profile);
    screens.warm({ key: "notice-test-account" }, { regular: 0, non_regular: 0, courses: [] });
    window = new BrowserWindow({ show: false, width: 1380, height: 1000, webPreferences: {
      preload: join(root, "dist-desktop/desktop/preload.cjs"), contextIsolation: true, sandbox: true, nodeIntegration: false,
      backgroundThrottling: false,
    } });
    const verify = (event) => assert.equal(event.senderFrame, window.webContents.mainFrame);
    const access = new LmsAccess();
    const web = new AssignmentWebSession(access, "ast-notice-browser-test");
    const assets = new Map([fixture[0].url, sameTabUrl, applicationUrl].map((url, index) => [
      url, { path: `/fixture-asset-${index}.svg`, requested: false, finish: Promise.withResolvers() },
    ]));
    if (!live) web.session.protocol.handle("https", async ({ url }) => {
      const asset = [...assets.values()].find(({ path }) => new URL(url).pathname === path);
      if (asset) {
        asset.requested = true;
        await asset.finish.promise;
        return new Response('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>', { headers: { "content-type": "image/svg+xml" } });
      }
      if (url === noContentUrl) return new Response(null, { status: 204 });
      const image = assets.get(url);
      return new Response(`<h1 id="top">테스트 공지 원문</h1>
        <a id="same" href="${sameTabUrl}">본문 보기</a>
        <a id="next" href="${applicationUrl}" target="_blank">테스트 신청</a>
        <a id="no-content" href="${noContentUrl}">표시할 내용 없음</a>
        <a id="anchor" href="#top">맨 위로</a>
        ${image ? `<img src="${image.path}">` : ""}`, { headers: { "content-type": "text/html" } });
    });
    const browser = registerAssignmentWindows({
      rendererPath: join(root, "dist/assignment-browser.html"), preload: join(root, "dist-desktop/desktop/preload.cjs"),
      connector: { access, requestTool: request }, screenData: screens, apiKey: "", verifyMain: verify, web, show: false,
    });
    registerScreenActions(screens, request, verify, undefined, () => profile, undefined, undefined, (url) => {
      if (!browser.openBrowser(url)) return false;
      openedUrls.push(url.href);
      return true;
    });
    const ready = {
      "astra-login-status": { state: "authenticated", message: "fixture" },
      "prefetch-status": { state: "ready", completed: 1, total: 1, sessionRevision: screens.confirmedSessionRevision },
      "home-snapshot": { overview: { regular: 0, non_regular: 0, courses: [] }, timetable: null, briefing: null, changes: [] },
      "assignment-settings": { includeOverdue: false, overdueDays: 7 },
      "chat-config": { model: "fixture", usdKrw: 1400, hasApiKey: false },
      "chat-transcript": { turns: [], storageError: false },
      "chat-composing": undefined,
    };
    for (const [name, value] of Object.entries(ready)) {
      ipcMain.removeHandler("ast:" + name);
      ipcMain.handle("ast:" + name, (event) => { verify(event); return value; });
    }
    await openNoticeScreen();

    let snapshot;
    await waitFor(async () => {
      snapshot = await run("window.ast.getCampusNoticeIndex()");
      return !snapshot.loading && Object.keys(snapshot.entries).length >= (live ? 30 : fixture.length - 1);
    }, "notice index loads", live ? 150_000 : 8000);
    const selectTopic = (title) => click('[aria-label="공지 주제"] button', title);
    const field = noticeSearchField;
    const readsAfterIndex = calls.filter((name) => name === "get_campus_notice").length;
    let term;
    if (live) {
      const samples = [
        ["Google Chrome 업데이트 권고", "systems"],
        ["영상 콘텐츠 공모전", "competition"],
        ["무료 일본어 클리닉", "international"],
        ["로스쿨 진학준비와 학습전략", "career"],
        ["3D프린터 장비교육", "learning"],
      ];
      const found = samples.flatMap(([title, tag]) => {
        const item = snapshot.notices.find((notice) => notice.title.includes(title));
        if (!item || !snapshot.entries[campusNoticeKey(item)]) return [];
        assert.ok(snapshot.entries[campusNoticeKey(item)].tags.includes(tag), `${title} should have ${tag}`);
        return [item];
      });
      for (const { tags } of Object.values(snapshot.entries)) assert.ok(tags.length <= 2);
      const example = bodyOnlyExample([...found, ...snapshot.notices], snapshot.entries);
      assert.ok(example, "a real classified notice contains a searchable body-only word");
      await selectTopic(campusNoticeTags[example.tag]);
      await waitFor(() => inRows(example.notice.title), "live topic filter includes the sample");
      term = example.word;
      await setSearch(field, term);
      await waitFor(() => inRows(example.notice.title), "live body-only query matches the sample");
      await waitFor(() => inExcerpt(term), "live result shows the matching excerpt");
      console.log(`Live school sample: ${snapshot.notices.length} list rows, ${Object.keys(snapshot.entries).length} indexed, ${found.length} expected classifications, partial=${snapshot.partial}`);
    } else {
      term = "부산표본";
      await waitFor(() => inRows("국가근로장학 안내"), "default All includes a different board");
      await verifyTimeline();
      await verifyFilterSelection(topicButtons, "장학·등록");
      await waitFor(async () => await inRows("국가근로장학 안내") && !await inRows("수강신청 안내"), "topic filters across boards");
      await selectTopic("학사·수업");
      await waitFor(async () => await inRows("국가근로장학 안내") && await inRows("수강신청 안내"), "multiple topics match either tag");
      await selectTopic("학사·수업");
      await setSearch(field, "장학표본");
      await waitFor(async () => await inRows("국가근로장학 안내") && await inExcerpt("장학표본"), "body-only term matches");
      await setSearch(field, "부산표본");
      await waitFor(async () => !await inRows("겨울 프로그램 안내") && !await inRows("국가근로장학 안내"), "query and tags both apply");
      await click('section[aria-labelledby="campus-notice-title"] button', "주제 선택 해제");
      await waitFor(() => inRows("겨울 프로그램 안내"), "body-only match reappears after clearing tags");
      await verifyFilterSelection(primaryTabs, "장학공지");
      await waitFor(async () => !await inRows("겨울 프로그램 안내"), "board narrows body matches");
      await click('[aria-label="공지 게시판"] button', "전체");
      await waitFor(() => inRows("겨울 프로그램 안내"), "All restores cross-board scope");
      await click('[aria-label="이 공지의 주제"] button', "국제교류·어학");
      assert.equal(await run('[...document.querySelectorAll(\'[aria-label="공지 주제"] button\')].find((item) => item.textContent === "국제교류·어학").getAttribute("aria-pressed")'), "true");
      await waitFor(() => readingContains(term), "opens cached body");
      await click(`${readingPane} .notice-reading-files a`, "예시 안내.pdf");
      await waitFor(() => openedUrls.length > 0, "attachment area opens the original in AST");
      assert.deepEqual(openedUrls, [fixture[0].url]);
      const original = BrowserWindow.getAllWindows().find((candidate) => candidate !== window);
      assert.ok(original);
      await expectPageReveal(original, fixture[0].url, assets.get(fixture[0].url));
      const originalId = (await browserState(original)).activeTabId;
      const { webContents: noticePage } = pageView(original, originalId);
      await noticePage.executeJavaScript("document.querySelector('#same').click()");
      await expectPageReveal(original, sameTabUrl, assets.get(sameTabUrl));
      assert.equal((await browserState(original)).activeTabId, originalId);
      const viewsBeforeAnchor = original.contentView.children.length;
      await noticePage.executeJavaScript("document.querySelector('#anchor').click()");
      await waitFor(async () => (await browserState(original)).url === sameTabUrl + "#top", "page anchor updates the current address");
      assert.equal(original.contentView.children.length, viewsBeforeAnchor, "in-page scrolling does not create an overlay");
      await noticePage.executeJavaScript("document.querySelector('#no-content').click()");
      await waitFor(async () => {
        const state = await browserState(original);
        return state.url === sameTabUrl + "#top" && !state.loading && !state.initialLoad && original.contentView.children.length === viewsBeforeAnchor;
      }, "a navigation with no page releases the overlay and restores the current page");
      await noticePage.executeJavaScript("document.querySelector('#next').click()");
      await expectPageReveal(original, applicationUrl, assets.get(applicationUrl));
      assert.equal((await browserState(original)).tabs.length, 2);
      assert.notEqual((await browserState(original)).activeTabId, originalId);
      await click(`${readingPane} [aria-label="본문 링크"] a`, "테스트 신청 페이지");
      await waitFor(() => openedUrls.at(-1) === applicationUrl, "verified body link opens in AST");
      assert.equal(await run(`window.ast.openCampusNoticeLink("https://example.test/unlisted", { board: "notice", board_id: "4691", id: "1" })`), false);
      assert.deepEqual(externalUrls, []);
      await verifyNarrowNotice();
    }
    await setSearch('input[aria-label="과목, 공지, 자료 검색"]', term);
    await waitFor(() => run(`document.querySelector(".ast-search-results")?.textContent.includes(${JSON.stringify(term)})`), "global search shares body index");
    if (!live) {
      await click(".ast-search-results button strong", fixture[0].title);
      await waitFor(() => run('document.querySelector("dialog[open]")?.textContent.includes("부산표본")'), "global search still opens the cached modal");
      await click("dialog[open] button", "닫기");
    }
    assert.equal(calls.filter((name) => name === "get_campus_notice").length, readsAfterIndex);
    if (!live) {
      await setSearch(field, "");
      await click('section[aria-labelledby="campus-notice-title"] button', "주제 선택 해제");
      await click('[aria-label="공지 게시판"] button', "장학공지");
      await waitFor(() => run('[...document.querySelectorAll(".notice-pagination button")].some((item) => item.textContent.trim() === "이전 공지 더 보기")'), "board offers the next page");
      await click(".notice-pagination button", "이전 공지 더 보기");
      await waitFor(() => inRows("지난 장학금 안내"), "board appends next page");
      await click('[aria-label="공지 게시판"] button', "전체");
      await waitFor(() => inRows("지난 장학금 안내"), "All includes pages browsed from a board");
      await click('[aria-label="공지 게시판"] button', "장학공지");
      await waitFor(() => inRows("지난 장학금 안내"), "board preserves its browsed pages");
    }
    await verifyDepartmentNotices();
    console.log(`PASS: School and registered college/department notices, timeline grouping, responsive inline reading, filtering, cached bodies and scope isolation.${live ? "" : " Full dates and splitter controls passed."} Extra body reads after indexing: 0.`);
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    window?.destroy();
    await screens?.shutdown();
    await connector?.close();
    rmSync(profile, { recursive: true, force: true });
    app.exit(process.exitCode ?? 0);
  }
}

void main();
