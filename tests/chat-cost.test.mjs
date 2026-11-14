import assert from "node:assert/strict";
import test from "node:test";
import { ChatCostLedger } from "../dist-desktop/desktop/chat-cost.js";
import { runChatTurn } from "../dist-desktop/desktop/chat-agent.js";
import { DEFAULT_USD_KRW } from "../dist-desktop/shared/chat.js";

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`);
const usage = (input = 1000, cached = 200, output = 100, extra = {}) => ({
  input_tokens: input, input_tokens_details: { cached_tokens: cached, ...extra },
  output_tokens: output, output_tokens_details: { reasoning_tokens: 70 }, total_tokens: input + output,
});
const billed = (usageValue = usage(), extra = {}) => ({ model: "gpt-6-luna", service_tier: "default", usage: usageValue, ...extra });
const message = [{ type: "message", role: "assistant", content: [{ type: "output_text", text: "확인했어요." }] }];
const toolCall = [{ type: "function_call", name: "list_courses", arguments: "{}", call_id: "read1" }];
const options = (extra = {}) => ({ apiKey: "test-key-not-real", model: "gpt-6-luna", question: "수강 과목 알려줘", history: [],
  signal: new AbortController().signal, onProgress() {}, ...extra });
const deps = (fetch) => ({ listTools: async () => [{ name: "list_courses", inputSchema: { type: "object", properties: {} } }],
  callTool: async () => ({ courses: [] }), fetch });
const response = (data) => new Response(JSON.stringify({ status: "completed", output: message, ...data }), { status: 200 });

test("cached input is discounted and reasoning is not double counted", () => {
  const ledger = new ChatCostLedger(1400);
  ledger.receive(ledger.begin("gpt-6-luna"), billed());
  const cost = ledger.snapshot();
  close(cost.usd, (800 * 0.1 + 200 * 0.01 + 100 * 0.5) / 1e6);
  close(cost.krw, cost.usd * 1400);
  assert.equal(cost.outputTokens, 100);
  assert.equal(cost.cachedInputTokens, 200);
  assert.equal(cost.status, "estimated");
  assert.equal(cost.pricedCalls, 1);
});

test("standard prices are exact model IDs, including the actual returned model", () => {
  for (const [model, inputPrice, cachedPrice, outputPrice] of [
    ["gpt-6-luna", 0.1, 0.01, 0.5], ["gpt-6.1-sol", 2, 0.1, 10],
    ["gpt-6.1-terra", 1, 0.05, 5], ["gpt-6-astra", 10, 1, 50],
  ]) {
    const ledger = new ChatCostLedger();
    ledger.receive(ledger.begin("gpt-6-luna"), billed(usage(), { model }));
    close(ledger.snapshot().usd, (800 * inputPrice + 200 * cachedPrice + 100 * outputPrice) / 1e6);
  }
  for (const model of ["gpt-6-luna-test", "gpt-6-luna-2026-11-12", "gpt-unknown", "toString"]) {
    const ledger = new ChatCostLedger();
    ledger.receive(ledger.begin("gpt-6-luna"), billed(usage(), { model }));
    assert.equal(ledger.snapshot().usd, null);
    assert.equal(ledger.snapshot().status, "unavailable");
  }
});

test("cache writes are separate from ordinary input and both lifetimes are handled", () => {
  const ledger = new ChatCostLedger();
  ledger.receive(ledger.begin("gpt-6-luna"), billed(usage(12_000, 4000, 100, {
    cache_write_tokens: 7000, cache_write_tokens_details: { ttl_30m_tokens: 3000, ttl_12h_tokens: 4000 },
  })));
  close(ledger.snapshot().usd, (1000 * 0.1 + 4000 * 0.01 + 3000 * 0.125 + 4000 * 0.25 + 100 * 0.5) / 1e6);
  const defaultTtl = new ChatCostLedger();
  defaultTtl.receive(defaultTtl.begin("gpt-6-luna"), billed(usage(1000, 0, 0, { cache_write_tokens: 1000 })));
  close(defaultTtl.snapshot().usd, 1000 * 0.125 / 1e6);
});

test("the long-context threshold changes the full request, including cache reads and writes", () => {
  const ledger = new ChatCostLedger();
  ledger.receive(ledger.begin("gpt-6-luna"), billed(usage(272000, 1000, 100, { cache_write_tokens: 1000 })));
  const short = ((270000 * 0.1 + 1000 * 0.01 + 1000 * 0.125) + 100 * 0.5) / 1e6;
  close(ledger.snapshot().usd, short);
  ledger.receive(ledger.begin("gpt-6-luna"), billed(usage(272001, 1000, 100, { cache_write_tokens: 1000 })));
  const long = ((270001 * 0.1 + 1000 * 0.01 + 1000 * 0.125) * 2 + 100 * 0.5 * 1.5) / 1e6;
  close(ledger.snapshot().usd, short + long);
});

test("missing, invalid, or mismatched pricing metadata never becomes a free call", () => {
  const invalidResponses = [
    {}, billed(null), billed({ input_tokens: 100, output_tokens: 10 }),
    billed(usage(-1)), billed(usage(100, 101)), billed(usage(100, 10, 1.5)),
    billed(usage(100, 10, 1, { cache_write_tokens: 91 })), billed(usage(100, 10, 1, { cache_write_tokens: null })),
    billed(usage(100, 10, 1, { cache_write_tokens: 10, cache_write_tokens_details: { ttl_30m_tokens: 9, ttl_12h_tokens: 0 } })),
    billed(usage(), { service_tier: "priority" }), billed(usage(), { service_tier: "flex" }),
  ];
  for (const data of invalidResponses) {
    const ledger = new ChatCostLedger();
    const call = ledger.begin("gpt-6-luna");
    assert.equal(ledger.snapshot().usd, null);
    ledger.receive(call, data);
    assert.equal(ledger.snapshot().status, "unavailable");
    assert.equal(ledger.snapshot().usd, null);
    assert.equal(ledger.snapshot().krw, null);
    assert.equal(ledger.snapshot().unknownCalls, 1);
  }
});

test("snapshots preserve known cost across missing calls and cannot double-count a response", () => {
  const ledger = new ChatCostLedger();
  assert.equal(ledger.snapshot().usd, 0);
  assert.equal(ledger.snapshot().calls, 0);
  assert.equal(ledger.snapshot().usdKrw, DEFAULT_USD_KRW);
  const first = ledger.begin("gpt-6-luna");
  ledger.receive(first, billed());
  ledger.receive(first, billed());
  const known = ledger.snapshot();
  ledger.begin("gpt-6-luna");
  const partial = ledger.snapshot();
  close(partial.usd, known.usd);
  assert.equal(partial.status, "partial");
  assert.equal(partial.calls, 2);
  assert.equal(partial.pricedCalls, 1);
  assert.equal(partial.unknownCalls, 1);
  // Snapshots are detached values; later updates do not alter displayed totals.
  assert.equal(known.status, "estimated");
  assert.equal(new ChatCostLedger(NaN).snapshot().usdKrw, DEFAULT_USD_KRW);
  assert.equal(new ChatCostLedger(-1).snapshot().usdKrw, DEFAULT_USD_KRW);
});

test("one user answer sums every model request and emits cost before each request", async () => {
  const snapshots = [];
  let calls = 0;
  const result = await runChatTurn(options({ usdKrw: 1400, onCost: (cost) => snapshots.push(cost) }), deps(async (_url, init) => {
    const body = JSON.parse(init.body);
    assert.equal(body.service_tier, "default");
    assert.equal(snapshots.at(-1).unknownCalls, 1);
    calls++;
    assert.equal(snapshots.at(-1).calls, calls);
    return response({ ...billed(), output: calls === 1 ? toolCall : message });
  }));
  assert.equal(result.cost.calls, 2);
  assert.equal(result.cost.pricedCalls, 2);
  assert.equal(result.cost.inputTokens, 2000);
  assert.equal(result.cost.outputTokens, 200);
  close(result.cost.usd, 2 * (800 * 0.1 + 200 * 0.01 + 100 * 0.5) / 1e6);
  close(result.cost.krw, result.cost.usd * 1400);
  assert.deepEqual(snapshots.map((cost) => [cost.calls, cost.pricedCalls]), [[0, 0], [1, 0], [1, 1], [2, 1], [2, 2]]);
});

test("usage survives incomplete output and abort after the response arrives", async () => {
  for (const cancelled of [false, true]) {
    const abort = new AbortController();
    let latest;
    await assert.rejects(runChatTurn(options({ signal: abort.signal, onCost: (cost) => { latest = cost; } }), deps(async () => {
      if (cancelled) abort.abort();
      return response({ ...billed(), status: cancelled ? "completed" : "incomplete" });
    })), cancelled ? /중지/ : /끝까지/);
    assert.equal(latest.status, "estimated");
    assert.equal(latest.pricedCalls, 1);
    assert.ok(latest.krw > 0);
  }
});

test("a failed later request retains the earlier request's amount without claiming a final total", async () => {
  let latest;
  let requests = 0;
  await assert.rejects(runChatTurn(options({ onCost: (cost) => { latest = cost; } }), deps(async () => {
    if (++requests === 1) return response({ ...billed(), output: toolCall });
    throw new Error("synthetic network failure");
  })), /네트워크/);
  assert.equal(latest.status, "partial");
  assert.equal(latest.calls, 2);
  assert.equal(latest.pricedCalls, 1);
  assert.equal(latest.unknownCalls, 1);
  assert.ok(latest.krw > 0);
});

test("cost is retained for malformed output or a failed response that still reports usage", async () => {
  for (const makeResponse of [
    () => response({ ...billed(), output: null }),
    () => new Response(JSON.stringify(billed()), { status: 500 }),
  ]) {
    let latest;
    await assert.rejects(runChatTurn(options({ onCost: (cost) => { latest = cost; } }), deps(async () => makeResponse())));
    assert.equal(latest.pricedCalls, 1);
    assert.equal(latest.status, "estimated");
    assert.ok(latest.krw > 0);
  }
});

test("an answer without provider usage reports an unavailable amount", async () => {
  const result = await runChatTurn(options(), deps(async () => response({})));
  assert.equal(result.cost.calls, 1);
  assert.equal(result.cost.status, "unavailable");
  assert.equal(result.cost.krw, null);
});

test("failures before any paid request report zero requests and no fabricated usage", async () => {
  let latest;
  await assert.rejects(runChatTurn(options({ onCost: (cost) => { latest = cost; } }), {
    ...deps(async () => assert.fail("must not request AI")), listTools: async () => { throw new Error("offline"); },
  }), /로컬 조회 도구/);
  assert.equal(latest.calls, 0);
  assert.equal(latest.krw, 0);
});
