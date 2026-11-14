// Run after npm run build: electron tests/chat-cost-ipc.smoke.mjs --headless
// Uses the real controller, preload and renderer with mocked provider/MCP data.
// No real API key, user profile, LMS session or external network is used.
import assert from "node:assert/strict";
import { readFile, rm, writeFile } from "node:fs/promises";
import { mkdtempSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, session, shell } from "electron";
import { registerChatActions } from "../dist-desktop/desktop/chat-controller.js";
import { createChatWorkspace } from "../dist-desktop/desktop/chat-workspace.js";
import { registerChatWorkspace } from "../dist-desktop/desktop/chat-workspace-ipc.js";
import { loadChatApiKey } from "../dist-desktop/desktop/chat-key.js";
import { removeLegacyChatKey, saveChatSettings } from "../dist-desktop/desktop/chat-settings.js";
import { registerScreenActions } from "../dist-desktop/desktop/screen-controller.js";
import { ScreenData } from "../dist-desktop/desktop/screen-data.js";
import { ChatTranscript } from "../dist-desktop/desktop/chat-transcript.js";
import { saveStudentPreferences } from "../dist-desktop/desktop/student-preferences.js";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const profile = mkdtempSync(join(tmpdir(), "ast-chat-cost-ipc-"));
app.setPath("userData", profile);
app.disableHardwareAcceleration();
process.env.OPENAI_API_KEY = "fixture-ignored-environment-key";
const counters = new Map();
let waitingForCancel = false;
let acceptNormal;
let normalStream;
const queried = [];
const openedUrls = [];
const astUrls = [];
const diningUrl = "https://housing.seoultech.ac.kr/livng/dining";
const scholarshipUrl = "https://www.seoultech.ac.kr/service/info/janghak?do=commonview&bnum=57138&bidx=12";
const applicationUrl = "https://example.test/scholarship-application";
let window;
const usage = { input_tokens: 1000, input_tokens_details: { cached_tokens: 200 },
  output_tokens: 100, output_tokens_details: { reasoning_tokens: 70 } };
const message = [{ type: "message", role: "assistant", content: [{ type: "output_text", text: "테스트 답변이에요." }] }];
const diningMessage = [{ type: "message", role: "assistant", content: [{ type: "output_text",
  text: `[자세한 내용은 여기를 눌러 주세요](${diningUrl})에서 확인해요.` }] }];
const toolCall = [{ type: "function_call", name: "list_courses", arguments: "{}", call_id: "fixture-read" }];
globalThis.fetch = async (_url, init) => {
  assert.equal(init.headers.Authorization, "Bearer fixture-dotenv-key");
  const request = JSON.parse(init.body);
  assert.equal(request.service_tier, "default");
  assert.equal(request.stream, true);
  const question = request.input.filter((item) => item.role === "user").at(-1).content;
  const n = (counters.get(question) ?? 0) + 1;
  counters.set(question, n);
  if (question === "normal" && n === 1) {
    await new Promise((resolve) => { acceptNormal = resolve; });
    const stream = new ReadableStream({ start(controller) { normalStream = controller; } });
    return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
  }
  if (question === "cancel 수강 과목" && n === 2) {
    waitingForCancel = true;
    return await new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new Error("fixture abort")), { once: true });
    });
  }
  if (question === "error 수강 과목" && n === 2) throw new Error("fixture network error");
  if (question === "대기 중 수강 과목" && n === 2) {
    assert.ok(!JSON.stringify(request.input).includes("fixture-course"), "old account context must not be sent during login");
    const outcome = request.input.find((item) => item.type === "function_call_output");
    assert.equal(JSON.parse(outcome.output).status, "login_required");
  }
  let output = message;
  if (["error 수강 과목", "cancel 수강 과목", "대기 중 수강 과목"].includes(question) && n === 1) output = toolCall;
  if (question === "공개 식단") output = n === 1 ? [{ ...toolCall[0], name: "get_dorm_menu" }] : diningMessage;
  if (question === "장학 공지 찾아줘") output = n === 1 ? [{ ...toolCall[0], name: "get_campus_briefing" }]
    : [{ type: "message", role: "assistant", content: [{ type: "output_text",
      text: `[장학 공지](${scholarshipUrl})에서 확인하고 [신청 페이지](${applicationUrl})로 이동해요.` }] }];
  if (question === "캘린더로 이동해줘") {
    if (n === 1) {
      assert.ok(request.tools.some(({ name }) => name === "ast_navigate"));
      output = [{ ...toolCall[0], name: "ast_navigate", arguments: '{"screen":"timetable"}' }];
    } else {
      assert.deepEqual(JSON.parse(request.input.at(-1).output), { status: "ok", screen: "timetable" });
      assert.equal(await run("document.querySelector('.ast-timetable-screen')?.hidden"), false);
      output = [{ type: "message", role: "assistant", content: [{ type: "output_text", text: "캘린더로 이동했어요." }] }];
    }
  }
  const detail = question === "tiny" ? { input_tokens: 1, input_tokens_details: { cached_tokens: 0 }, output_tokens: 0 } : usage;
  return new Response(JSON.stringify({ status: "completed", model: question === "unknown" ? "unknown-model" : "gpt-6-luna",
    service_tier: "default", usage: detail,
    output }), { status: 200 });
};

const run = (source) => window.webContents.executeJavaScript(source);
const waitFor = async (check, label) => {
  for (let i = 0; i < 100; i++) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Timed out: ${label}`);
};
const summaries = () => run("[...document.querySelectorAll('.chat-cost summary')].map(x => x.textContent)");
async function assertChatIcons(expected) {
  for (const [selector, name, width, height] of expected) {
    await waitFor(() => run(`Boolean(document.querySelector(${JSON.stringify(selector)})?.naturalWidth)`), `Figma ${name} loaded`);
    const icon = await run(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      const rect = element.getBoundingClientRect();
      return { file: new URL(element.src).pathname.split('/').at(-1), width: rect.width, height: rect.height };
    })()`);
    assert.ok(icon.file.startsWith(`${name}-`) && icon.file.endsWith(".svg"), `Figma ${name} asset in its intended control`);
    assert.ok(Math.abs(icon.width - width) < .1 && Math.abs(icon.height - height) < .1, `Figma ${name} rendered at native size`);
  }
}

const send = async (question, { throughBridge = false } = {}) => {
  if (throughBridge) {
    // Test main-process session checks even when the welcome screen makes the composer inert.
    const id = "fixture-" + (counters.size + 1);
    assert.ok((await run(`window.ast.sendChat(${JSON.stringify(id)}, ${JSON.stringify(question)})`)).ok);
    return;
  }
  await run(`(() => { const el=document.querySelector('textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(el, ${JSON.stringify(question)}); el.dispatchEvent(new Event('input',{bubbles:true})); })()`);
  await waitFor(() => run("!document.querySelector('[aria-label=\"메시지 보내기\"]').disabled"), "input ready");
  await run("document.querySelector('.chat-composer').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))");
};

function fixtureWindow() {
  return new BrowserWindow({ show: false, width: 1600, height: 1000, webPreferences: {
    preload: join(root, "dist-desktop/desktop/preload.cjs"), contextIsolation: true, sandbox: true, nodeIntegration: false,
  } });
}

async function main() {
try {
  await app.whenReady();
  app.dock?.hide();
  app.on("window-all-closed", () => {});
  shell.openExternal = async (url) => { openedUrls.push(url); };
  const settingsPath = join(profile, "chat-settings.json");
  const envPath = join(profile, ".env");
  await writeFile(settingsPath, JSON.stringify({ model: "gpt-6-luna", usdKrw: 1334.4, encryptedKey: "fixture-legacy-ciphertext" }));
  assert.equal(await loadChatApiKey(profile), "", "an inherited key does not substitute for .env");
  await saveChatSettings({ model: "gpt-6-luna", usdKrw: 1370 });
  assert.equal(JSON.parse(await readFile(settingsPath, "utf8")).encryptedKey, "fixture-legacy-ciphertext");
  await writeFile(envPath, 'OPENAI_API_KEY="fixture-dotenv-key"\n');
  const apiKey = await loadChatApiKey(profile);
  assert.equal(apiKey, "fixture-dotenv-key");
  assert.equal(process.env.OPENAI_API_KEY, "fixture-ignored-environment-key");
  await removeLegacyChatKey();
  assert.deepEqual(JSON.parse(await readFile(settingsPath, "utf8")), { model: "gpt-6-luna", usdKrw: 1370, fontSize: 16 });
  session.defaultSession.webRequest.onBeforeRequest({ urls: ["http://*/*", "https://*/*"] }, (_details, callback) => callback({ cancel: true }));
  window = fixtureWindow();
  const verifySender = (event) => assert.equal(event.senderFrame, window.webContents.mainFrame);
  const screenRequest = async (tool) => {
    if (tool === "confirm_desktop_login") return { status: "authenticated", message: "fixture" };
    if (tool === "start_desktop_login") return { status: "opened", message: "fixture" };
    if (tool === "get_desktop_login_status") return { status: "pending", message: "fixture" };
    if (tool === "get_course_overview") return { status: "ok", overview: { regular: 0, non_regular: 0, courses: [] } };
    return { status: "error", message: tool };
  };
  const screenData = new ScreenData(screenRequest, (status) => {
    chat.sessionChanged();
    login.sessionChanged();
    if (!window.isDestroyed()) window.webContents.send("ast:prefetch-status", status);
  });
  const chat = registerChatActions({
    apiKey,
    verifySender,
    window: () => window,
    confirmedLmsSession: () => screenData.confirmedSessionRevision,
    openBrowser: (url) => { astUrls.push(url.href); return true; },
    workspace: createChatWorkspace({
      screenData, run: registerChatWorkspace(() => window, verifySender),
      openCoursePage: async () => false, openBrowser: () => false,
    }),
    getClient: async () => ({
      listTools: async () => ({ tools: ["list_courses", "get_dorm_menu", "get_campus_briefing"].map((name) => ({ name, inputSchema: { type: "object", properties: {} } })) }),
      callTool: async ({ name }) => {
        queried.push(name);
        if (name === "get_campus_briefing") return { structuredContent: { notices: [{ title: "테스트 장학 공지", url: scholarshipUrl,
          links: [{ url: applicationUrl, text: "테스트 신청 페이지" }] }] } };
        return { structuredContent: name === "list_courses"
          ? { result: [{ id: "fixture-course", name: "검증용 과목" }] }
          : { dorm_name: "검증 학사", days: [{}], source_url: diningUrl } };
      },
    }),
  });
  const login = registerScreenActions(screenData, screenRequest, verifySender);
  await saveStudentPreferences({ residence: "none", departmentId: "computer" });
  await window.loadFile(join(root, "dist/index.html"));
  await waitFor(() => run("!!document.querySelector('.chat-composer')"), "renderer");
  assert.equal((await run("window.ast.getPrefetchStatus()")).state, "idle");
  assert.equal((await run("window.ast.getCourseTimetable('bad-date')")).status, "error");
  const initial = await run("window.ast.getChatConfig()");
  assert.deepEqual(initial, { model: "gpt-6-luna", usdKrw: 1370, fontSize: 16, hasApiKey: true });
  for (const rate of ["0", "-1", "100001", "NaN", "Infinity", "'1400'"]) {
    const rejected = await run(`window.ast.saveChatConfig({model:'gpt-6-luna',usdKrw:${rate}}).then(()=>false,()=>true)`);
    assert.equal(rejected, true, `rate rejected: ${rate}`);
  }
  await run("window.ast.saveChatConfig({model:'gpt-6-luna',usdKrw:1400,apiKey:'fixture-renderer-key'})");
  assert.deepEqual(JSON.parse(await readFile(settingsPath, "utf8")), { model: "gpt-6-luna", usdKrw: 1400, fontSize: 16 });
  await window.reload();
  await waitFor(() => run("!!document.querySelector('.chat-composer')"), "reload");
  assert.equal((await run("window.ast.getChatConfig()")).usdKrw, 1400);

  assert.equal((await run("window.ast.confirmLogin()")).status, "authenticated");
  await waitFor(() => run("document.querySelector('.ast-entry-shell')?.dataset.entry === 'open'"), "welcome complete");
  assert.deepEqual(await run(`(() => {
    const style = getComputedStyle(document.querySelector('.chat-sidebar--let-him-cook'));
    return { radius: style.borderRadius, colorScheme: style.colorScheme, blushGradient: style.backgroundImage.includes('70.673%') };
  })()`), { radius: "25px", colorScheme: "light", blushGradient: true });
  await assertChatIcons([
    [".chat-identity-avatar img", "avatar", 50.75, 52.5],
    [".chat-new img", "reset", 17, 17],
    [".chat-scope img:first-child", "scope", 15.2, 15],
    [".chat-scope img:last-child", "chevron", 14, 14],
    [".chat-followups img", "followup", 13, 13],
    [".chat-attach img", "attach", 17, 17],
    [".chat-send img", "send", 40, 40],
  ]);
  await send("normal");
  await waitFor(() => acceptNormal, "request sent but no response received");
  assert.equal(await run("document.querySelector('.chat-receipt').textContent"), "방금 보냄");
  assert.equal(await run("!!document.querySelector('.chat-assistant-message')"), false, "the agent area waits for a read receipt");
  if (await run("!matchMedia('(prefers-reduced-motion: reduce)').matches")) {
    const flight = await run(`(() => {
      const copy = document.querySelector('.chat-message-flight');
      const frames = copy?.getAnimations()[0]?.effect.getKeyframes();
      return { duration: copy?.getAnimations()[0]?.effect.getTiming().duration, travels: frames?.[0].transform !== frames?.at(-1).transform };
    })()`);
    assert.deepEqual(flight, { duration: 440, travels: true });
  }
  acceptNormal();
  await waitFor(() => run("document.querySelector('.chat-receipt').textContent === '방금 읽음'"), "accepted response marks the message read");
  assert.match(await run("document.querySelector('.chat-working').textContent"), /생각 중이에요\..*질문을 확인하고 있어요/);
  const push = (type, fields = {}) => normalStream.enqueue(new TextEncoder().encode("data: " + JSON.stringify({ type, ...fields }) + "\r\n\r\n"));
  push("response.in_progress");
  push("response.output_text.delta", { delta: "테스트 " });
  await waitFor(() => run("document.querySelector('.chat-answer-text')?.textContent === '테스트 '"), "the first text arrives before completion");
  assert.equal(await run("document.querySelector('.chat-working-label').textContent"), "생각 중이에요.");
  assert.equal(await run("!!document.querySelector('.chat-answer-time')"), false);
  assert.equal((await summaries()).length, 0, "cost and final transcript wait for the terminal event");
  push("response.output_text.delta", { delta: "답변이에요." });
  await waitFor(() => run("document.querySelector('.chat-answer-text')?.textContent === '테스트 답변이에요.'"), "the second chunk appends");
  const markdown = [
    "테스트 답변이에요.", "", "## 신청 일정", "", "- **마감** 11/25", "- 준비물 확인", "",
    "> 원문에 나온 조건을 확인해요.", "",
    "| 공지 | 마감 |", "| --- | ---: |", "| [등록 안내](https://example.invalid) | 11/25 |",
    "| A\\|B | 11/27 |", "", "```sh", "npm run build", "```",
  ].join("\n");
  push("response.output_text.delta", { delta: markdown.slice("테스트 답변이에요.".length) });
  await waitFor(() => run("!!document.querySelector('.chat-answer-text table tbody td')"), "Markdown table renders while streaming");
  const output = [{ type: "message", role: "assistant", content: [{ type: "output_text", text: markdown }] }];
  push("response.completed", { response: { status: "completed", model: "gpt-6-luna", service_tier: "default", usage, output } });
  await waitFor(async () => (await summaries()).length === 1, "normal answer");
  assert.deepEqual(await run(`(() => {
    const answer = document.querySelector('.chat-answer-text');
    const bubble = document.querySelector('.chat-user-message');
    return {
      heading: answer.querySelector('h3').textContent,
      list: [...answer.querySelectorAll('li')].map((item) => item.textContent),
      quote: answer.querySelector('blockquote').textContent,
      cells: [...answer.querySelectorAll('tbody td')].map((cell) => cell.textContent),
      code: answer.querySelector('pre').textContent,
      unverifiedLink: !!answer.querySelector('a, .chat-inline-source'),
      card: getComputedStyle(answer).backgroundColor,
      bubble: getComputedStyle(bubble).backgroundImage,
    };
  })()`), {
    heading: "신청 일정", list: ["마감 11/25", "준비물 확인"], quote: "원문에 나온 조건을 확인해요.",
    cells: ["등록 안내", "11/25", "A|B", "11/27"], code: "npm run build", unverifiedLink: false,
    card: "rgb(255, 255, 255)", bubble: "linear-gradient(90deg, rgb(0, 0, 0), rgb(54, 48, 48) 37.5%, rgb(0, 0, 0))",
  });
  if (await run("!matchMedia('(prefers-reduced-motion: reduce)').matches")) {
    assert.equal(await run("getComputedStyle(document.querySelector('.chat-assistant-message')).animationName"), "chat-assistant-in");
  }
  assert.equal((await summaries())[0], "예상 비용 약 0.18원");
  const firstAnswer = (await run("window.ast.getChatTranscript()")).turns[0];
  assert.ok(firstAnswer.answeredAt >= firstAnswer.readAt);
  assert.equal(await run("document.querySelector('.chat-answer-time').dateTime"), new Date(firstAnswer.answeredAt).toISOString());
  await assertChatIcons([[".chat-reply-avatar img", "reply", 35, 36.2]]);
  await send("tiny");
  await waitFor(async () => (await summaries()).length === 2, "tiny answer");
  assert.match((await summaries())[1], /0\.01원 미만/);
  await send("unknown");
  await waitFor(async () => (await summaries()).length === 3, "unknown price");
  assert.equal((await summaries())[2], "비용 확인 불가");

  await send("error 수강 과목");
  await waitFor(async () => (await summaries()).length === 4, "partial error");
  const originalError = (await summaries())[3];
  assert.equal(originalError, "확인된 예상 비용 약 0.18원 · 일부 미확인");
  assert.equal(await run("document.querySelector('.chat-results li').textContent"), "검증용 과목 확인");
  await run("document.querySelector('.chat-retry').click()");
  await waitFor(async () => (await summaries()).length === 5, "retry");
  assert.equal((await summaries())[3], originalError);
  assert.equal((await summaries())[4], "예상 비용 약 0.18원");

  await send("cancel 수강 과목");
  await waitFor(() => waitingForCancel, "in-flight second request");
  await waitFor(() => run("document.querySelector('.chat-turn:last-child .chat-results li')?.textContent === '검증용 과목 확인'"), "live tool result");
  assert.equal(await run("document.querySelectorAll('.chat-turn:last-child .chat-working').length"), 1);
  await assertChatIcons([
    [".chat-loading-orbs img:first-child", "loadingBack", 34, 34.7],
    [".chat-loading-orbs img:last-child", "loadingFront", 32.75, 32.9],
  ]);
  assert.equal(await run("document.querySelectorAll('.chat-steps').length"), 0);
  await run("document.querySelector('[aria-label=\"답변 생성 중지\"]').click()");
  await waitFor(async () => (await summaries()).length === 6, "cancel partial cost");
  assert.equal((await summaries())[5], "확인된 예상 비용 약 0.18원 · 일부 미확인");
  assert.equal(await run("document.querySelector('.chat-turn:last-child .chat-results li').textContent"), "검증용 과목 확인");
  const finalSummaries = await summaries();
  await run("document.querySelector('.chat-scope').click()");
  await waitFor(() => run("!!document.querySelector('#chat-usd-krw')"), "rate settings");
  assert.equal(await run("!!document.querySelector('.chat-settings input[type=password]')"), false);
  assert.match(await run("document.querySelector('.chat-key-status').textContent"), /키 · 설정됨/);
  assert.equal(await run("document.querySelector('#chat-usd-krw').value"), "1400");
  assert.equal(await run("document.querySelector('#chat-font-size').value"), "16");
  await run(`(() => {
    const size = document.querySelector('#chat-font-size');
    size.value = '22';
    size.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await run("(() => { const el=document.querySelector('#chat-usd-krw'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'1500'); el.dispatchEvent(new Event('input',{bubbles:true})); })()");
  await new Promise((resolve) => setTimeout(resolve, 30));
  await run("document.querySelector('.chat-settings form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))");
  await waitFor(() => run("document.querySelector('.settings-chat [role=status]')?.textContent === '대화 설정을 저장했어요.'"), "rate saved");
  assert.equal((await run("window.ast.getChatConfig()")).usdKrw, 1500);
  const chatTextSizes = () => run(`['.chat-user-message', '.chat-answer-text', '.chat-composer textarea'].map((selector) =>
    getComputedStyle(document.querySelector(selector)).fontSize)`);
  assert.deepEqual(await chatTextSizes(), ["22px", "22px", "22px"]);
  assert.deepEqual(await run(`['.chat-header', '.chat-messages', '.chat-footer'].map((selector) =>
    getComputedStyle(document.querySelector(selector)).backgroundColor)`), Array(3).fill("rgba(0, 0, 0, 0)"),
    "header, history and footer share the sidebar gradient");
  await run(`document.querySelector('.ast-pane-divider--chat').dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }))`);
  await waitFor(() => run("document.querySelector('.ast-pane-divider--chat').getAttribute('aria-valuenow') === '240'"), "minimum chat width");
  assert.equal(await run(`(() => {
    const messages = document.querySelector('.chat-messages');
    const card = document.querySelector('.chat-answer-text');
    const table = card.querySelector('.chat-markdown-table');
    return messages.scrollWidth === messages.clientWidth && table.scrollWidth > table.clientWidth;
  })()`), true, "wide tables scroll inside the narrow answer card");
  const scrollHistory = (position) => run(`(() => {
    const history = document.querySelector('.chat-messages');
    history.scrollTop = (history.scrollHeight - history.clientHeight) * ${position};
  })()`);
  const hasFadedEdges = (top, bottom) => run(`(() => {
    const style = getComputedStyle(document.querySelector('.chat-messages'));
    return style.getPropertyValue('--chat-fade-top').trim() === '${top}' &&
      style.getPropertyValue('--chat-fade-bottom').trim() === '${bottom}';
  })()`);
  await scrollHistory(0);
  await waitFor(() => hasFadedEdges("0px", "18px"), "only the lower edge fades at the start of history");
  await scrollHistory(.5);
  await waitFor(() => hasFadedEdges("18px", "18px"), "both edges fade between messages");
  await scrollHistory(1);
  await waitFor(() => hasFadedEdges("18px", "0px"), "the last message stays clear above the footer");
  await run("[...document.querySelectorAll('.app-nav button')].find(button => button.textContent === '홈 화면').click()");
  await waitFor(() => run("!!document.querySelector('.ast-mode-switch')"), "home mode switch");
  await run("document.querySelector('.ast-mode-switch button:last-child').click()");
  await waitFor(() => run("document.querySelector('.ast-workspace').dataset.mode === 'focus'"), "focus mode");
  assert.deepEqual(await chatTextSizes(), ["22px", "22px", "22px"]);
  assert.equal(await run("getComputedStyle(document.querySelector('.chat-messages')).backgroundColor"), "rgba(0, 0, 0, 0)");
  assert.deepEqual(await summaries(), finalSummaries, "previous amounts retain their original exchange rate");
  await send("new-rate");
  await waitFor(async () => (await summaries()).length === 7, "new rate answer");
  assert.equal((await summaries())[6], "예상 비용 약 0.20원");

  assert.equal((await run("window.ast.openLogin()")).status, "opened");
  await send("대기 중 수강 과목", { throughBridge: true });
  await waitFor(async () => (await run("window.ast.getChatTranscript()")).turns.length === 8, "blocked private query");
  assert.deepEqual(queried, ["list_courses", "list_courses"]);
  assert.equal((await run("window.ast.getChatTranscript()")).turns[7].state, "done");
  await send("공개 식단", { throughBridge: true });
  await waitFor(async () => (await run("window.ast.getChatTranscript()")).turns.length === 9, "public query while login is pending");
  assert.equal(queried.at(-1), "get_dorm_menu");

  const historyPath = join(profile, "chat-history.json");
  const saved = await run("window.ast.getChatTranscript()");
  assert.ok(saved.turns[0].sentAt <= saved.turns[0].readAt);
  assert.deepEqual(new ChatTranscript(historyPath).snapshot(), JSON.parse(JSON.stringify(saved)));
  assert.equal(statSync(historyPath).mode & 0o777, 0o600);
  const historyJson = await readFile(historyPath, "utf8");
  assert.doesNotMatch(historyJson, /fixture-dotenv-key|function_call_output|fixture-course/);
  assert.equal(saved.turns[8].sources[0].url, diningUrl);
  assert.equal((await summaries()).length, 7, "bridge-only probes do not alter mounted transcript state");
  const beforeReload = await summaries();
  window.destroy();
  window = fixtureWindow();
  await window.loadFile(join(root, "dist/index.html"));
  await waitFor(async () => (await summaries()).length === 9, "transcript restored into the renderer");
  assert.deepEqual(await chatTextSizes(), ["22px", "22px", "22px"]);
  assert.deepEqual((await summaries()).slice(0, 7), beforeReload);
  assert.deepEqual(await run("window.ast.getChatTranscript()"), saved);
  const readTime = saved.turns[0].readAt;
  const advanceClock = (minutes) => run(`Date.now = () => ${readTime + minutes * 60_000};
    document.dispatchEvent(new Event('visibilitychange'))`);
  await advanceClock(127);
  await waitFor(() => run("document.querySelector('.chat-receipt').textContent === '읽음: 2시간 7분 전'"), "relative read receipt");
  const date = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium" }).format(readTime);
  await advanceClock(1440);
  await waitFor(() => run(`document.querySelector('.chat-receipt').textContent === ${JSON.stringify("읽음: " + date)}`), "date after 24 hours");
  const answerTime = new Date(firstAnswer.answeredAt + 9 * 3_600_000).toISOString();
  const answerDate = `${answerTime.slice(5, 7)}/${answerTime.slice(8, 10)} ${answerTime.slice(11, 16)}`;
  await run(`Date.now = () => ${firstAnswer.answeredAt + 16 * 60_000};
    document.dispatchEvent(new Event('visibilitychange'))`);
  await waitFor(() => run(`document.querySelector('.chat-answer-time').textContent === ${JSON.stringify(answerDate + " 16분 전")}`),
    "the restored answer shows its Seoul completion time and elapsed minutes");
  assert.deepEqual(await run(`(() => {
    const button = document.querySelector('.chat-turn:last-child button.chat-inline-source');
    return { title: button.firstElementChild.textContent, border: getComputedStyle(button).borderTopStyle };
  })()`), { title: "검증 학사", border: "solid" });
  await run("document.querySelector('.chat-turn:last-child button.chat-inline-source').click()");
  await waitFor(() => openedUrls.length === 1, "the title button opens the same verified URL");
  assert.deepEqual(openedUrls, [diningUrl]);
  await run("document.querySelector('.chat-turn:last-child .chat-sources summary').click()");
  await assertChatIcons([
    [".chat-turn:last-child .chat-sources button img:first-child", "source", 13, 14.2],
    [".chat-turn:last-child .chat-sources button img:last-child", "external", 12.1, 12.1],
  ]);
  await run("document.querySelector('.chat-new').click()");
  await waitFor(async () => (await summaries()).length === 0, "clear transcript");
  assert.deepEqual(new ChatTranscript(historyPath).snapshot().turns, []);
  screenData.warm();
  await waitFor(() => run("document.querySelector('.ast-entry-shell')?.dataset.entry === 'open'"), "workspace reopened");
  await send("캘린더로 이동해줘");
  await waitFor(async () => (await run("window.ast.getChatTranscript()")).turns[0]?.answer === "캘린더로 이동했어요.", "agent confirms the committed calendar navigation");
  await send("장학 공지 찾아줘");
  await waitFor(() => run("document.querySelectorAll('.chat-turn:last-child .chat-inline-source').length === 2"), "scholarship and application links become title buttons");
  await run("document.querySelector('.chat-turn:last-child .chat-inline-source').click()");
  await waitFor(() => astUrls[0] === scholarshipUrl, "inline scholarship link opens the AST browser");
  await run("document.querySelector('.chat-turn:last-child .chat-sources summary').click()");
  await run("document.querySelector('.chat-turn:last-child .chat-sources li:last-child button').click()");
  await waitFor(() => astUrls[1] === applicationUrl, "the verified application link in the source list opens AST");
  assert.deepEqual(openedUrls, [diningUrl], "notice links never invoke the default browser");
  console.log("PASS: chat login gating, restored transcript and costs, settings and screen IPC; zero external requests");
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  window?.destroy();
  await rm(profile, { recursive: true, force: true });
  app.exit(process.exitCode ?? 0);
}
}
void main();
