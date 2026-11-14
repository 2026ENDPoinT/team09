import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setTimeout as wait } from "node:timers/promises";
import vm from "node:vm";
import { Utterances } from "../dist-desktop/desktop/live-lecture/utterances.js";
import { SonioxStream } from "../dist-desktop/desktop/live-lecture/soniox.js";
import { GptAssist } from "../dist-desktop/desktop/live-lecture/gpt.js";
import { AssistSession } from "../dist-desktop/desktop/live-lecture/assist.js";

test("only confirmed Soniox text commits, with speaker splits and reconnect timing", () => {
  const finals = [];
  const splitter = new Utterances((segment) => finals.push(segment));
  assert.deepEqual(splitter.accept([{ text: "복사 생성", is_final: false, speaker: "1" }]), [{ text: "복사 생성", speaker: null }]);
  assert.equal(finals.length, 0);
  splitter.accept([
    { text: "복사 생성자", is_final: true, speaker: "1", start_ms: 20, end_ms: 320 },
    { text: "질문", is_final: true, speaker: "2", start_ms: 350, end_ms: 600 },
    { text: "<end>", is_final: true },
  ]);
  splitter.newConnection(2000);
  splitter.accept([{ text: "재접속.", is_final: true, speaker: "1", start_ms: 12, end_ms: 55 }]);
  assert.deepEqual(finals.map(({ speaker, text, startMs, endMs }) => [speaker, text, startMs, endMs]), [
    [1, "복사 생성자", 20, 320], [2, "질문", 350, 600], [3, "재접속.", 2012, 2055],
  ]);
});

class Socket extends EventTarget {
  readyState = WebSocket.CONNECTING;
  bufferedAmount = 0;
  sent = [];
  open() { this.readyState = WebSocket.OPEN; this.dispatchEvent(new Event("open")); }
  send(data) { this.sent.push(data); }
  close() { this.readyState = WebSocket.CLOSED; }
  server(value) { this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(value) })); }
}

test("Soniox authenticates in the handshake, reconnects once, and drains final audio on stop", async () => {
  const sockets = [];
  const finals = [];
  const reconnects = [];
  const errors = [];
  let gaps = 0;
  const stream = new SonioxStream("sample", "stt-rt-v6", {
    ready() {}, reconnect: (attempt) => reconnects.push(attempt), gap: () => gaps++,
    captions() {}, final: (value) => finals.push(value), ended: (error) => errors.push(error),
  }, (url, protocols) => {
    assert.equal(url, "wss://stt-rt.soniox.com/transcribe-websocket");
    assert.deepEqual(protocols, ["soniox-api-key", "sample"]);
    const socket = new Socket();
    sockets.push(socket);
    return socket;
  });
  try {
    stream.start();
    stream.push(new ArrayBuffer(8000));
    sockets[0].open();
    const options = JSON.parse(sockets[0].sent[0]);
    assert.equal(options.enable_speaker_diarization, true);
    assert.equal(options.enable_endpoint_detection, true);
    assert.equal(options.api_key, undefined);
    sockets[0].dispatchEvent(new Event("close"));
    assert.deepEqual(reconnects, [1]);
    assert.equal(gaps, 1);
    stream.push(new ArrayBuffer(3200));
    await wait(550);
    sockets[1].open();
    stream.stop();
    assert.equal(sockets[1].sent.at(-1), "");
    sockets[1].server({ tokens: [{ text: "다음 발화", is_final: true, start_ms: 5, end_ms: 80 }], finished: true });
    assert.equal(finals[0].startMs, 255);
    assert.deepEqual(errors, [undefined]);
  } finally { stream.dispose(); }
});

test("GPT reviews exact transcript references and consumes fragmented Korean streaming events", async () => {
  const requests = [];
  const answer = "복사 생성자는 새 객체를 초기화해요.";
  const envelope = (text) => ({ status: "completed", output: [{ type: "message", content: [{ type: "output_text", text }] }] });
  const item = { segmentId: "1", quote: "복사 생성자", concept: "복사 생성자", followUps: ["언제 쓰일까요?", "대입과 어떻게 다를까요?"] };
  const provider = new GptAssist("placeholder", "gpt-6-luna", async (_url, request) => {
    const body = JSON.parse(request.body);
    requests.push(body);
    if (!body.stream) return Response.json(envelope(JSON.stringify({ items: [{
      ...item, followUps: ["복사 생성자란 무엇일까요?", "언제 쓰일까요?", "언제 쓰일까요?", "대입과 어떻게 다를까요?"],
    }] })));
    const messages = [
      { type: "response.output_text.delta", delta: answer },
      { type: "response.completed", response: envelope(answer) },
    ].map((event) => "data: " + JSON.stringify(event) + "\r\n\r\n").join("");
    const bytes = new TextEncoder().encode(messages);
    return new Response(new ReadableStream({ start(controller) {
      for (let index = 0; index < bytes.length; index += 7) controller.enqueue(bytes.slice(index, index + 7));
      controller.close();
    } }));
  });
  const signal = new AbortController().signal;
  const segment = { id: "1", startMs: 0, endMs: 1000, speaker: 1, text: "복사 생성자가 호출돼요." };
  assert.deepEqual(await provider.review({ recent: [segment], targetIds: ["1"], known: [] }, signal), [item]);
  const deltas = [];
  const input = { item: { ...item, id: "1:복사 생성자", startMs: 0 }, recent: [segment], evidence: segment };
  assert.equal(await provider.explain(input, signal, (text) => deltas.push(text)), answer);
  assert.deepEqual(deltas, [answer]);
  assert.equal(JSON.parse(requests[1].input).question, "복사 생성자란 무엇일까요?");
  assert.equal("followUp" in JSON.parse(requests[1].input), false);
  await provider.explain({ ...input, followUp: item.followUps[1] }, signal, () => {});
  assert.equal(JSON.parse(requests[2].input).followUp, "대입과 어떻게 다를까요?");
  assert.equal(requests[0].text.format.strict, true);
  assert.ok(requests.every(({ store }) => store === false));
});

test("the session blocks unsupported quotes and duplicates, and keeps the clicked concept's evidence for follow-ups", async () => {
  const item = { segmentId: "a", quote: "복사 생성자", concept: "복사 생성자", followUps: ["언제 쓰일까요?", "대입과 어떻게 다를까요?"] };
  const inputs = [];
  const fake = {
    async review() { return [item, { ...item }, { ...item, quote: "없는 인용", concept: "없는 개념" }]; },
    async explain(value) { inputs.push(value); return value.followUp ?? "기본 설명"; },
  };
  const session = new AssistSession(fake, { state() {}, captions() {}, explanation() {} });
  try {
    session.begin(false);
    session.phase("listening");
    session.add({ id: "a", startMs: 0, endMs: 900, speaker: 1, text: "여기서 복사 생성자가 호출돼요." });
    await wait(1310);
    assert.equal(session.current.suggestions.length, 1);
    const { id } = session.current.suggestions[0];
    await session.explain(id);
    assert.equal(session.detail.state, "ready");
    assert.equal(session.detail.question, "복사 생성자란 무엇일까요?");
    assert.equal(inputs[0].evidence.text, "여기서 복사 생성자가 호출돼요.");
    await session.explain(id, "목록에 없는 질문");
    await session.explain(id, item.followUps[1]);
    assert.equal(session.detail.text, item.followUps[1]);
    assert.equal(inputs[1].evidence, inputs[0].evidence);
    await session.explain(id);
    assert.equal(session.detail.text, "기본 설명");
    assert.equal(inputs.length, 2);
  } finally { session.dispose(); }
});

test("ending a lecture reviews short final utterances and leaves them available for an on-demand explanation", async () => {
  let reviewed;
  let explained;
  const checked = Promise.withResolvers();
  const fake = {
    async review(input) {
      reviewed = input;
      return [
        { segmentId: "constant", quote: "상수", concept: "상수", followUps: [] },
        { segmentId: "class", quote: "클래스", concept: "클래스", followUps: [] },
      ];
    },
    async explain(input) { explained = input; return "상수는 값이고 클래스는 객체를 만드는 틀이에요."; },
  };
  const session = new AssistSession(fake, {
    state(value) { if (value.reviewStatus === "checked") checked.resolve(); },
    captions() {},
    explanation() {},
  });
  try {
    session.begin(false);
    session.phase("listening");
    session.add({ id: "constant", startMs: 0, endMs: 800, speaker: 1, text: "상수." });
    session.phase("stopping");
    session.add({ id: "class", startMs: 900, endMs: 1400, speaker: 1, text: "클래스." });
    session.phase("ended");
    await Promise.race([checked.promise, wait(2000, undefined, { ref: false }).then(() => assert.fail("Pending review was lost"))]);
    assert.deepEqual(reviewed.targetIds, ["constant", "class"]);
    assert.deepEqual(session.current.suggestions.map(({ concept }) => concept), ["상수", "클래스"]);
    await session.explainRecent();
    assert.equal(explained.request, "recent");
    assert.deepEqual(explained.recent.map(({ text }) => text), ["상수.", "클래스."]);
    assert.equal(session.detail.state, "ready");
  } finally { session.dispose(); }
});

test("reviewed concepts from different subjects have exact underlines and open with their basic definition", async () => {
  const checked = Promise.withResolvers();
  let input;
  let reviewed;
  const session = new AssistSession({
    async review(value) {
      reviewed = value;
      return [
        { segmentId: "first", quote: "수요", concept: "수요", followUps: [] },
        { segmentId: "first", quote: "급", concept: "급", followUps: [] },
        { segmentId: "second", quote: "반투과성 막", concept: "반투과성 막", followUps: [] },
      ];
    },
    async explain(value) { input = value; return "설명"; },
  }, {
    state(value) { if (value.reviewStatus === "checked") checked.resolve(); },
    captions() {}, explanation() {},
  });
  try {
    session.begin(false);
    session.phase("listening");
    const economics = "수요곡선을 보면 가격이 내려갈 때 수요가 달라져요. 공급은 그대로예요.";
    const biology = "반투과성 막을 사이에 두면 물이 이동해요.";
    session.add({ id: "first", startMs: 0, endMs: 800, speaker: 1, text: economics });
    session.add({ id: "second", startMs: 900, endMs: 1600, speaker: 1, text: biology });
    assert.deepEqual(session.current.suggestions, []);
    session.phase("ended");
    await Promise.race([checked.promise, wait(2000, undefined, { ref: false }).then(() => assert.fail("Review timed out"))]);
    assert.deepEqual(reviewed.recent.map(({ text }) => text), [economics, biology]);
    assert.deepEqual(session.current.suggestions.map(({ segmentId, concept }) => [segmentId, concept]),
      [["first", "수요"], ["second", "반투과성 막"]]);
    assert.deepEqual(session.current.suggestions[0].positions, [economics.indexOf("수요가")]);
    const item = session.current.suggestions.find(({ concept }) => concept === "반투과성 막");
    await session.explain(item.id);
    assert.equal(input.item.concept, "반투과성 막");
    assert.equal(input.evidence.text, biology);
    assert.equal(input.followUp, undefined);
    assert.equal(session.detail.question, "반투과성 막이란 무엇일까요?");
  } finally { session.dispose(); }
});

test("starting a recording preserves a streaming answer and the context for the next chat question", async () => {
  const answer = Promise.withResolvers();
  const explanations = [];
  const received = [];
  const session = new AssistSession({
    async review() { return []; },
    async explain(input, signal, delta) {
      received.push(input);
      delta("답변을 쓰고 있어요.");
      const text = received.length === 1 ? await answer.promise : "다음 답변이에요.";
      signal.throwIfAborted();
      return text;
    },
  }, { state() {}, captions() {}, explanation(value) { explanations.push(value); } });
  try {
    const first = session.ask("먼저 용어를 설명해 주세요.");
    const opened = session.detail;
    assert.equal(opened.state, "loading");
    session.begin(true);
    assert.equal(session.detail, opened);
    assert.equal(explanations.length, 1);
    answer.resolve("첫 답변이에요.");
    await first;
    assert.equal(session.detail.state, "ready");
    assert.equal(session.detail.turn, opened.turn);
    session.phase("ended");
    session.begin(false);
    assert.equal(session.detail.text, "첫 답변이에요.");
    await session.ask("그 부분을 다시 설명해 주세요.");
    assert.deepEqual(received[1].history, [{ question: "먼저 용어를 설명해 주세요.", answer: "첫 답변이에요." }]);
  } finally { session.dispose(); }
});

test("reused utterance IDs open the new recording's evidence", async () => {
  const received = [];
  const session = new AssistSession({
    async review() { return []; },
    async explain(input) { received.push(input.evidence.text); return input.evidence.text; },
  }, { state() {}, captions() {}, explanation() {} });
  try {
    session.begin(false);
    session.add({ id: "1", startMs: 0, endMs: 800, speaker: 1, text: "첫 강의 내용이에요." });
    await session.explainUtterance("1");
    const firstId = session.detail.item.id;
    session.begin(false);
    session.add({ id: "1", startMs: 0, endMs: 800, speaker: 1, text: "다음 강의 내용이에요." });
    await session.explainUtterance("1");
    assert.notEqual(session.detail.item.id, firstId);
    assert.deepEqual(received, ["첫 강의 내용이에요.", "다음 강의 내용이에요."]);
  } finally { session.dispose(); }
});

test("queued final utterances are reviewed across batches", async () => {
  const drained = Promise.withResolvers();
  const batches = [];
  const session = new AssistSession({
    async review({ targetIds }) {
      batches.push(targetIds);
      return [];
    },
    async explain() { return "설명"; },
  }, {
    state(value) { if (value.reviewStatus === "checked" && batches.length === 2) drained.resolve(); },
    captions() {}, explanation() {},
  });
  try {
    session.begin(false);
    session.phase("stopping");
    const ids = Array.from({ length: 8 }, (_, index) => String(index));
    ids.forEach((id, index) => session.add({ id, startMs: index * 800, endMs: (index + 1) * 800, speaker: 1, text: "이 예를 살펴봐요." }));
    session.phase("ended");
    await Promise.race([drained.promise, wait(2000, undefined, { ref: false }).then(() => assert.fail("Pending batches were lost"))]);
    assert.deepEqual(batches, [ids.slice(0, 6), ids.slice(6)]);
  } finally { session.dispose(); }
});

test("the worklet preserves 16 kHz little-endian PCM and flushes the final partial chunk", async () => {
  let Worklet;
  const messages = [];
  const context = {
    sampleRate: 48_000,
    AudioWorkletProcessor: class { port = { postMessage: (message) => messages.push(message) }; },
    registerProcessor(_name, constructor) { Worklet = constructor; },
  };
  vm.runInNewContext(await readFile(new URL("../public/lecture-capture.js", import.meta.url), "utf8"), context);
  const worker = new Worklet();
  const block = new Float32Array(4800).fill(0.5);
  worker.process([[block]]);
  worker.port.onmessage({ data: "flush" });
  assert.deepEqual(messages.map((value) => value.byteLength ?? value), [2560, 640, "flushed"]);
  assert.equal(new DataView(messages[0]).getInt16(0, true), 16383);
});
