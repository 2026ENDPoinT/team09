import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as wait } from "node:timers/promises";
import { app, BrowserWindow, ipcMain, screen } from "electron";
import { fileURLToPath, pathToFileURL } from "node:url";
import { registerLiveLecture } from "../dist-desktop/desktop/live-lecture/controller.js";
import { loadChatApiKey } from "../dist-desktop/desktop/chat-key.js";
import { saveChatSettings } from "../dist-desktop/desktop/chat-settings.js";
import { LectureArchive } from "../dist-desktop/desktop/live-lecture/archive.js";

const profile = mkdtempSync(join(tmpdir(), "live-lecture-smoke-"));
app.setPath("userData", profile);
app.disableHardwareAcceleration();
app.commandLine.appendSwitch("use-fake-device-for-media-stream");
const root = fileURLToPath(new URL("../", import.meta.url));
const fixture = mkdtempSync(join(tmpdir(), "ast-live-lecture-fixtures-"));
const fixtureModel = "fixture-lecture-model";
const checkVisible = process.argv.includes("--verify-visible");

const audioChunks = [];
const requests = [];
const output = (text) => ({ status: "completed", output: [{ type: "message", content: [{ type: "output_text", text }] }] });
globalThis.fetch = async (_url, request) => {
  const body = JSON.parse(request.body);
  assert.equal(request.headers.Authorization, "Bearer fixture-openai");
  assert.equal(body.model, fixtureModel);
  requests.push(body);
  const input = JSON.parse(body.input);
  const text = input.request === "utterance" ? "선택한 발화를 설명해요."
    : input.request === "question" ? "강의 예시에 연결해 설명해요."
    : input.request === "recent"
    ? "방금 나온 개념은 삼투압이에요."
    : "반투과성 막은 물처럼 작은 분자를 골라 통과시키는 막이에요.";
  if (!body.stream) return Response.json(output(JSON.stringify({ items: input.recent
    .filter(({ id, text }) => input.targetIds.includes(id) && text.includes("반투과성 막"))
    .map(({ id }) => ({ segmentId: id, quote: "반투과성 막", concept: "반투과성 막", followUps: [] })) })));
  if (input.request === "question") await wait(850);
  return new Response([
    { type: "response.output_text.delta", delta: text },
    { type: "response.completed", response: output(text) },
  ].map((value) => "data: " + JSON.stringify(value) + "\n\n").join(""));
};

globalThis.WebSocket = class FakeSpeech extends EventTarget {
  static OPEN = 1;
  readyState = 0;
  bufferedAmount = 0;
  chunks = 0;
  constructor() {
    super();
    setTimeout(() => {
      this.readyState = 1;
      this.dispatchEvent(new Event("open"));
    }, 100);
  }
  send(value) {
    if (value === "") {
      this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ tokens: [], finished: true }) }));
    } else if (typeof value === "string" && JSON.parse(value).api_key) {
      assert.equal(JSON.parse(value).api_key, "fixture-soniox");
      assert.equal(JSON.parse(value).model, "fixture-stt-model");
    } else if (value instanceof ArrayBuffer) {
      audioChunks.push(value.byteLength);
      if (++this.chunks === 2) this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
        tokens: [
          { text: "이 예에서 물은 반투과성 막을 지나가요.", is_final: true, speaker: "1", start_ms: 0, end_ms: 140 },
          { text: "다음으로 삼투압을 살펴볼게요.", is_final: true, speaker: "1", start_ms: 160, end_ms: 200 },
        ],
      }) }));
    }
  }
  close() { this.readyState = 3; }
};

async function until(predicate, timeout = 10_000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const value = await predicate();
    if (value) return value;
    await wait(75);
  }
  throw new Error("Desktop condition timed out");
}

async function dragResize(window, deltaX, deltaY) {
  const contents = window.webContents;
  const { x, y } = await contents.executeJavaScript(`(() => {
    const grip = document.querySelector(".resize-grip").getBoundingClientRect();
    return { x: grip.x + grip.width / 2, y: grip.y + grip.height / 2 };
  })()`);
  const debug = contents.debugger;
  debug.attach();
  try {
    await debug.sendCommand("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
    await contents.executeJavaScript(`(() => {
      const grip = document.querySelector(".resize-grip");
      const bounds = grip.getBoundingClientRect();
      grip.dispatchEvent(new PointerEvent("pointerup", {
        bubbles: true, pointerId: 1, isPrimary: true, button: 0, pointerType: "mouse",
        screenX: screenX + bounds.x + bounds.width / 2 + ${deltaX},
        screenY: screenY + bounds.y + bounds.height / 2 + ${deltaY},
      }));
    })()`);
    await debug.sendCommand("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  } finally { debug.detach(); }
}

async function main() {
  try {
    await app.whenReady();
    const dockVisible = app.dock?.isVisible();
    await writeFile(join(fixture, ".env"), "OPENAI_API_KEY=fixture-openai\nSONIOX_API_KEY=fixture-soniox\nSONIOX_MODEL=fixture-stt-model\n");
    await saveChatSettings({ model: fixtureModel }, fixture);
    const makeOwner = () => new BrowserWindow({ show: false, width: 800, height: 600, webPreferences: {
      preload: join(root, "dist-desktop", "desktop", "preload.cjs"), sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false,
    } });
    const owner = makeOwner();
    owner.webContents.on("console-message", (event) => { if (event.level === "error") console.error(event.message); });
    const renderer = join(root, "dist", "index.html");
    const rendererUrl = pathToFileURL(renderer).href;
    let sessionRevision = 1;
    let activeAccount = fixture;
    const fixtures = {
      "astra-login-status": { state: "authenticated", message: "" },
      "prefetch-status": { state: "ready", completed: 0, total: 0, sessionRevision },
      "home-snapshot": { overview: null, briefing: null, timetable: null, changes: [] },
      "student-preferences": { residence: "seonglim", departmentId: "computer" },
      "assignment-settings": { includeOverdue: false, overdueDays: 7 }, "focus-library": { ok: true, value: { version: 1, items: [] } },
      "course-notice-settings": {},
      "dorm-menu": { status: "error", message: "식단 테스트 응답" },
      "chat-config": { model: fixtureModel, usdKrw: 1400, fontSize: 15, hasApiKey: true }, "chat-transcript": { turns: [] },
    };
    for (const [name, data] of Object.entries(fixtures)) ipcMain.handle(`ast:${name}`, () => data);
    ipcMain.handle("ast:chat-composing", () => {});
    const controller = registerLiveLecture({
      projectRoot: fixture, rendererPath: join(root, "dist", "live-lecture.html"),
      apiKey: await loadChatApiKey(fixture), activeDirectory: () => activeAccount,
      sessionRevision: () => sessionRevision, hidden: !checkVisible,
      verifyMain(event) {
        if (event.sender !== owner.webContents || event.senderFrame !== event.sender.mainFrame
          || event.senderFrame?.url !== rendererUrl) throw new Error("Unexpected AST sender");
      },
    });
    await owner.loadFile(renderer);
    const ownerJs = (code) => owner.webContents.executeJavaScript(code);
    assert.deepEqual(BrowserWindow.getAllWindows(), [owner]);
    const other = makeOwner();
    await other.loadFile(renderer);
    await assert.rejects(other.webContents.executeJavaScript("window.ast.openLiveLecture()"), /Unexpected AST sender/);
    other.destroy();
    try { await until(() => ownerJs('document.querySelector(".ast-entry-shell")?.dataset.entry === "open"')); }
    catch (error) { console.error(await ownerJs('document.querySelector(".ast-entry-shell")?.dataset.entry')); throw error; }
    await ownerJs('document.querySelector(".ast-mode-switch button:last-child").click()');
    await until(() => ownerJs('document.querySelector(".focus-study[data-task=lecture] button") !== null'));
    const ownerBounds = owner.getBounds();
    if (checkVisible) {
      owner.showInactive();
      await until(() => owner.isVisible());
    }
    assert.deepEqual(await ownerJs('Array.from(document.querySelectorAll(".focus-navigation button"), button => button.textContent)'),
      ["홈", "내 파일", "강의록", "시간표 및 캘린더"]);
    await ownerJs('document.querySelector(".focus-study[data-task=lecture] button").click()');
    const lecture = () => BrowserWindow.getAllWindows().filter((window) => window.webContents.getURL().includes("live-lecture.html"));
    await until(() => lecture().length === 2 && lecture().some(window => window.webContents.getURL().endsWith("#chat")));
    const primary = lecture().find((window) => !window.webContents.getURL().endsWith("#chat"));
    const chat = lecture().find((window) => window.webContents.getURL().endsWith("#chat"));
    if (process.platform === "darwin") {
      assert.equal(app.dock.isVisible(), dockVisible, "Opening lecture panels must preserve AST's Dock visibility");
      assert.ok(primary.isVisibleOnAllWorkspaces() && chat.isVisibleOnAllWorkspaces());
    }
    assert.equal(owner.isDestroyed(), false);
    assert.equal(owner.webContents.getURL(), rendererUrl);
    assert.equal(await ownerJs('document.querySelector(".ast-workspace").dataset.mode'), "focus");
    if (checkVisible) {
      await until(() => primary.isVisible() && chat.isVisible());
      assert.ok(owner.isVisible() && !owner.isMinimized());
      assert.deepEqual(owner.getBounds(), ownerBounds);
      primary.close();
      await until(() => primary.isDestroyed() && chat.isDestroyed());
      assert.ok(owner.isVisible());
      await controller.dispose();
      owner.destroy();
      console.log("AST and both lecture panels stayed visible together. Closing the panels kept AST open.");
      return 0;
    }
    assert.deepEqual(await ownerJs("Promise.all([window.ast.openLiveLecture(), window.ast.openLiveLecture()])"), [{ ok: true }, { ok: true }]);
    assert.ok(lecture().includes(primary) && lecture().includes(chat));
    const detailJs = (code) => chat.webContents.executeJavaScript(code);
    const openChat = (open) => until(() => detailJs(`document.querySelector(".lecture-chat")?.dataset.open === "${open}" && document.querySelector(".lecture-chat")?.dataset.moving === "false"`));
    const panelRect = () => detailJs('JSON.parse(JSON.stringify(document.querySelector(".lecture-chat-panel").getBoundingClientRect()))');
    const typeQuestion = (selector, question) => detailJs(`(() => {
      const field = document.querySelector(${JSON.stringify(selector)});
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(field, ${JSON.stringify(question)});
      field.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await openChat(false);
    const workArea = screen.getDisplayMatching(primary.getBounds()).workArea;
    const idle = chat.getBounds();
    const bar = await detailJs('JSON.parse(JSON.stringify(document.querySelector(".lecture-spotlight").getBoundingClientRect()))');
    assert.equal(idle.x + bar.x + bar.width / 2, workArea.x + workArea.width / 2);
    assert.equal(idle.y + bar.bottom, workArea.y + workArea.height - 18);
    await detailJs('document.querySelector(".lecture-orb").click()');
    await until(() => detailJs('document.querySelector(".lecture-chat").dataset.moving === "true"'));
    await openChat(true);
    assert.ok(chat.getBounds().height > idle.height);
    await detailJs('document.querySelector(".lecture-orb").click()');
    await until(() => detailJs('document.querySelector(".lecture-chat").dataset.moving === "true"'));
    await openChat(false);
    await until(() => chat.getBounds().height === idle.height);
    const js = (code) => primary.webContents.executeJavaScript(code);
    assert.equal(primary.isAlwaysOnTop(), true);
    await until(() => js('document.querySelector(".action") !== null'));
    assert.equal(await js('document.querySelector(".action").textContent.includes("해설 시작")'), true);
    assert.equal(await js('document.querySelector(".overlay-footer button")'), null);
    await js('Array.from(document.querySelectorAll("button")).find(b => b.textContent === "미리보기").click()');
    await until(() => js('document.querySelector(".highlight-featured")?.textContent === "복사 생성자"'));
    const demoCards = await js('Array.from(document.querySelectorAll(".card-title"), el => el.textContent)');
    assert.equal(demoCards[0], "복사 생성자란 무엇일까요?");
    assert.ok(demoCards.includes("객체란 무엇일까요?") && demoCards.includes("메모리란 무엇일까요?"));
    assert.ok(await js('Array.from(document.querySelectorAll(".highlight")).some(el => el.textContent === "메모리")'));
    assert.equal(await js('document.querySelector(".feed").scrollHeight >= document.querySelector(".feed").clientHeight'), true);
    if (process.env.LIVE_ASSIST_SMOKE_SCREENSHOTS) {
      const image = await primary.webContents.capturePage();
      if (!image.isEmpty()) await writeFile(process.env.LIVE_ASSIST_SMOKE_SCREENSHOTS + "-overlay.png", image.toPNG());
    }
    await js('document.querySelector(".card").click()');
    await openChat(true);
    await until(() => detailJs('document.querySelector(".explanation")?.getAttribute("aria-busy") === "false"'));
    assert.match(await detailJs('document.querySelector(".explanation").textContent'), /이미 있는 객체/);
    assert.match(await detailJs('document.querySelector(".chat-turn:last-child blockquote").textContent'), /복사 생성자가 호출/);
    const position = primary.getBounds();
    const chatPosition = chat.getBounds();
    primary.setPosition(position.x - 36, position.y, false);
    assert.equal(primary.getBounds().x, position.x - 36);
    assert.deepEqual(chat.getBounds(), chatPosition);
    const mainBeforeResize = primary.getBounds();
    const before = await panelRect();
    await dragResize(primary, 48, -44);
    await until(() => primary.getBounds().width === mainBeforeResize.width - 48);
    assert.equal(primary.getBounds().height, mainBeforeResize.height - 44);
    assert.deepEqual(await panelRect(), before);
    await detailJs('document.querySelector(".chat-resize").dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }))');
    await until(async () => (await panelRect()).width === before.width + 24);
    assert.equal((await panelRect()).right, before.right);
    assert.equal(primary.getBounds().width, mainBeforeResize.width - 48);
    if (process.env.LIVE_ASSIST_SMOKE_SCREENSHOTS) {
      const image = await chat.webContents.capturePage();
      if (!image.isEmpty()) await writeFile(process.env.LIVE_ASSIST_SMOKE_SCREENSHOTS + "-chat.png", image.toPNG());
    }
    await detailJs('document.querySelector(".chat-header .close").click()');
    await openChat(false);
    await typeQuestion(".lecture-spotlight input", "메모리가 뭔가요?");
    await detailJs('document.querySelector(".lecture-spotlight .chat-send").click()');
    await openChat(true);
    await until(() => detailJs('document.querySelector(".explanation")?.textContent.includes("데이터를 두는 공간")'));
    assert.equal(await detailJs('document.querySelectorAll(".chat-turn").length'), 2);
    await detailJs('document.querySelector(".chat-header .close").click()');
    await openChat(false);
    await until(() => js('Array.from(document.querySelectorAll(".utterance-selectable")).some(el => el.textContent.includes("이제 한쪽의 값을"))'), 20_000);
    await js('Array.from(document.querySelectorAll(".highlight")).find(el => el.textContent === "깊은 복사").click()');
    await until(() => detailJs('document.querySelector(".follow-ups button") !== null'));
    assert.equal(await detailJs('document.querySelector(".chat-turn:last-child .chat-question").textContent'), "깊은 복사란 무엇일까요?");
    assert.match(await detailJs('document.querySelector(".explanation").textContent'), /^깊은 복사는 원본의 데이터를 복사본의 공간에 따로 담는 방식/);
    assert.deepEqual(await detailJs('Array.from(document.querySelectorAll(".follow-ups button span:first-child"), el => el.textContent)'),
      ["주소만 복사할 때와 뭐가 다를까요?", "왜 한쪽을 바꿔도 다른 쪽은 그대로일까요?"]);
    await detailJs('document.querySelectorAll(".follow-ups button")[1].click()');
    await until(() => detailJs('document.querySelector(".explanation")?.textContent.includes("원본은 여전히 3")'));
    assert.equal(await detailJs('document.querySelector(".chat-turn:last-child .chat-question").textContent'), "왜 한쪽을 바꿔도 다른 쪽은 그대로일까요?");
    await detailJs('document.querySelector(".back-to-basic").click()');
    await until(() => detailJs('document.querySelector(".chat-turn:last-child .chat-question")?.textContent === "깊은 복사란 무엇일까요?"'));
    assert.equal(await detailJs('document.querySelector(".explanation").getAttribute("aria-busy")'), "false");
    await js('Array.from(document.querySelectorAll(".utterance-selectable")).find(el => el.textContent.includes("이제 한쪽의 값을")).click()');
    await js('document.querySelector(".utterance-confirm").click()');
    await until(() => detailJs('document.querySelector(".explanation")?.getAttribute("aria-busy") === "false"'));
    const demoExplanation = await detailJs('document.querySelector(".explanation").textContent');
    assert.match(demoExplanation, /원본 객체와 복사한 객체/);
    assert.match(demoExplanation, /깊은 복사를 적용한 뒤/);
    assert.match(demoExplanation, /자기 말로 확인/);
    const savedTurns = () => detailJs('Array.from(document.querySelectorAll(".chat-turn"), el => el.textContent)');
    const demoChat = await savedTurns();
    await js('document.querySelector(".end-action").click()');
    await until(() => js('document.querySelector(".status").textContent.includes("종료됨")'));
    assert.deepEqual(await savedTurns(), demoChat);
    await js('document.querySelector(".action").click()');
    await until(() => {
      if (audioChunks.length >= 2) return true;
      return js('document.querySelector(".notice")?.textContent || ""').then((notice) => {
        if (notice) throw new Error(notice);
        return false;
      });
    });
    assert.deepEqual(await savedTurns(), demoChat);
    assert.equal(audioChunks[0], 2560);
    await until(() => js('document.querySelector(".highlight")?.textContent === "반투과성 막"'));
    assert.equal(requests.length, 1);
    assert.equal(await js('document.querySelector(".card-title").textContent'), "반투과성 막이란 무엇일까요?");
    await js('document.querySelector(".highlight").click()');
    await until(() => detailJs('document.querySelector(".explanation")?.getAttribute("aria-busy") === "false"'));
    assert.match(await detailJs('document.querySelector(".explanation").textContent'), /^반투과성 막은/);
    assert.equal(JSON.parse(requests[1].input).question, "반투과성 막이란 무엇일까요?");
    assert.equal(requests.length, 2);
    await js('document.querySelector(".action.stop:not(.end-action)").click()');
    await until(() => js('document.querySelector(".status").textContent.includes("일시 중지됨")'));
    const pausedAudio = audioChunks.length;
    const pausedState = await js('window.lecture.state()');
    await wait(250);
    assert.equal(audioChunks.length, pausedAudio);
    assert.equal((await ownerJs('window.ast.getLectureHistory(1)')).records.length, 0);
    await js('document.querySelector(".recent-explain").click()');
    await until(() => detailJs('document.querySelector(".explanation")?.getAttribute("aria-busy") === "false"'));
    assert.match(await detailJs('document.querySelector(".explanation").textContent'), /방금 나온 개념/);
    assert.equal(requests.length, 3);
    await js('document.querySelector(".utterance-selectable p").click()');
    await until(() => js('document.querySelector(".utterance-prompt")?.textContent.includes("이 발화를 설명할까요?")'));
    assert.equal(requests.length, 3);
    await js('document.querySelector(".utterance-prompt .quiet").click()');
    await until(() => js('!document.querySelector(".utterance-prompt")'));
    assert.equal(requests.length, 3);
    await js('document.querySelector(".utterance-toggle").click()');
    await js('document.querySelector(".utterance-confirm").click()');
    await until(() => detailJs('document.querySelector(".explanation")?.textContent.includes("선택한 발화를 설명해요.")'));
    const selected = JSON.parse(requests[3].input);
    assert.equal(selected.request, "utterance");
    assert.equal(selected.evidence.text, "이 예에서 물은 반투과성 막을 지나가요.");
    assert.deepEqual(selected.before, []);
    assert.ok(selected.after.some(({ text }) => text.includes("삼투압")));
    assert.equal("question" in selected, false);
    assert.match(await detailJs('document.querySelector(".chat-turn:last-child blockquote").textContent'), /반투과성 막을 지나가요/);
    await openChat(true);
    await typeQuestion(".chat-composer input", "그럼 물은 왜 이동해요?");
    await detailJs('document.querySelector(".chat-composer .chat-send").click()');
    await until(() => detailJs('document.querySelector(".explanation")?.getAttribute("aria-busy") === "true"'));
    await detailJs('document.querySelector(".chat-header .close").click()');
    await openChat(false);
    await until(() => detailJs('document.querySelector(".explanation")?.textContent.includes("강의 예시에 연결해")'));
    assert.equal(await detailJs('document.querySelector(".lecture-chat").dataset.open'), "false");
    const chatInput = JSON.parse(requests[4].input);
    assert.equal(chatInput.request, "question");
    assert.equal(chatInput.question, "그럼 물은 왜 이동해요?");
    assert.ok(chatInput.history.some(({ question }) => question === "깊은 복사란 무엇일까요?"));
    assert.ok(chatInput.history.some(({ question }) => question === "반투과성 막이란 무엇일까요?"));
    assert.equal((await savedTurns()).length, demoChat.length + 4);
    await detailJs('document.querySelector(".lecture-orb").click()');
    await openChat(true);
    assert.equal((await savedTurns()).length, demoChat.length + 4);
    await js('document.querySelector(".action:not(.stop)").click()');
    const resumed = await until(async () => {
      const state = await js('window.lecture.state()');
      return state.segments.length >= 4 ? state : undefined;
    });
    assert.equal(new Set(resumed.segments.map(({ id }) => id)).size, 4);
    assert.ok(resumed.segments[2].startMs >= pausedState.segments[1].endMs);
    assert.equal((await savedTurns()).length, demoChat.length + 4);
    await js('document.querySelector(".end-action").click()');
    await until(() => js('document.querySelector(".status").textContent.includes("종료됨")'));

    await ownerJs('Array.from(document.querySelectorAll(".focus-navigation button")).find(button => button.textContent === "강의록").click()');
    await until(() => ownerJs('document.querySelector(".focus-lecture-list button") !== null'));
    await ownerJs('document.querySelector(".focus-lecture-list button").click()');
    const recordWindow = await until(() => lecture().find(window => window.webContents.getURL().includes("#record/")));
    await until(() => recordWindow.webContents.executeJavaScript('document.querySelector(".lecture-record-view") !== null'));
    assert.deepEqual(await recordWindow.webContents.executeJavaScript('Array.from(document.querySelectorAll(".record-columns h2"), el => el.firstChild.textContent.trim())'), ["강의록", "강의 채팅"]);
    assert.equal(await recordWindow.webContents.executeJavaScript('document.querySelectorAll(".record-segment").length'), 4);
    assert.equal(await recordWindow.webContents.executeJavaScript('document.querySelectorAll(".record-turn").length'), 4);
    assert.match(await recordWindow.webContents.executeJavaScript('document.querySelector(".record-turn:last-child").textContent'), /그럼 물은 왜 이동해요/);
    assert.equal(await recordWindow.webContents.executeJavaScript('typeof window.lecture'), "undefined");

    await js('document.querySelector(".action").click()');
    await until(() => js('document.querySelector(".status")?.textContent.includes("듣는 중") && document.querySelectorAll(".utterance-selectable").length >= 2'));
    await js('document.querySelector(".titlebar .close").click()');
    await until(() => primary.isDestroyed() && chat.isDestroyed());
    assert.equal(owner.isDestroyed(), false);
    await until(() => ownerJs('document.querySelectorAll(".focus-lecture-list button").length === 2'));
    const diskRecords = await new LectureArchive(join(fixture, "live-lectures")).list();
    assert.deepEqual(diskRecords.map(({ utterances }) => utterances), [2, 4]);
    activeAccount = join(fixture, "other-account");
    sessionRevision++;
    controller.sessionChanged();
    assert.ok(recordWindow.isDestroyed());
    assert.deepEqual(await ownerJs("window.ast.getLectureHistory(2)"), { ok: true, records: [] });
    assert.equal((await ownerJs(`window.ast.openLectureRecord(2, ${JSON.stringify(diskRecords[0].id)})`)).ok, false);
    assert.deepEqual(await ownerJs("window.ast.openLiveLecture()"), { ok: true });
    assert.equal(lecture().length, 2);
    owner.destroy();
    assert.equal(lecture().length, 0);
    await controller.dispose();
    console.log("AST live lecture smoke passed: focus home launch, pause/resume, save on stop and close, history detail, account separation.");
    return 0;
  } catch (error) {
    console.error(error);
    return 1;
  }
}

const watchdog = setTimeout(() => {
  console.error("Desktop smoke timed out.");
  app.exit(1);
}, 65_000);
void main().then((code) => {
  clearTimeout(watchdog);
  app.exit(code);
  rmSync(profile, { recursive: true, force: true });
  rmSync(fixture, { recursive: true, force: true });
});
