import { DEFAULT_USD_KRW, type ChatCost } from "../shared/chat.js";

// Standard global-endpoint prices per million tokens, checked 2026-11-12.
// https://developers.openai.com/api/docs/pricing
// Each model's official page documents the >272K long-context multipliers.
// https://developers.openai.com/api/docs/guides/prompt-caching documents write
// lifetimes and the mutually exclusive ordinary/read/write token buckets.
export const CHAT_PRICING_DATE = "2026-11-12";
const PRICES: Readonly<Record<string, { input: number; cached: number; output: number }>> = {
  "gpt-6-luna": { input: 0.1, cached: 0.01, output: 0.5 },
  "gpt-6.1-sol": { input: 2, cached: 0.1, output: 10 },
  "gpt-6.1-terra": { input: 1, cached: 0.05, output: 5 },
  "gpt-6-astra": { input: 10, cached: 1, output: 50 },
};

type Usage = { input: number; cached: number; output: number; write30m: number; write12h: number };
type CostEntry = { requestedModel: string; received: boolean; usd: number | null; usage?: Usage; reason?: string };

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function tokenCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function readUsage(value: unknown): Usage | null {
  if (!record(value) || !tokenCount(value.input_tokens) || !tokenCount(value.output_tokens) ||
    !record(value.input_tokens_details)) return null;
  const details = value.input_tokens_details;
  const cached = details.cached_tokens;
  const written = details.cache_write_tokens === undefined ? 0 : details.cache_write_tokens;
  if (!tokenCount(cached) || !tokenCount(written) || cached + written > value.input_tokens) return null;
  // Requests use the provider's documented default 30-minute cache lifetime.
  // If the provider returns lifetime buckets, use them instead of guessing.
  let write30m = written;
  let write12h = 0;
  if (details.cache_write_tokens_details !== undefined) {
    const writes = details.cache_write_tokens_details;
    if (!record(writes) || !tokenCount(writes.ttl_30m_tokens) || !tokenCount(writes.ttl_12h_tokens) ||
      writes.ttl_30m_tokens + writes.ttl_12h_tokens !== written) return null;
    write30m = writes.ttl_30m_tokens;
    write12h = writes.ttl_12h_tokens;
  }
  return { input: value.input_tokens, cached, output: value.output_tokens, write30m, write12h };
}

/** One ledger per user turn; never persist prompts, responses, or credentials. */
export class ChatCostLedger {
  private readonly entries: CostEntry[] = [];
  private readonly usdKrw: number;

  constructor(usdKrw = DEFAULT_USD_KRW) {
    this.usdKrw = Number.isFinite(usdKrw) && usdKrw > 0 ? usdKrw : DEFAULT_USD_KRW;
  }

  /** Record before sending: an interrupted request can still incur a charge. */
  begin(requestedModel: string): number {
    this.entries.push({ requestedModel, received: false, usd: null, reason: "일부 요청의 사용량을 받지 못했어요." });
    return this.entries.length - 1;
  }

  receive(index: number, response: unknown): void {
    const entry = this.entries[index];
    if (!entry || entry.received) return;
    entry.received = true;
    const usage = readUsage(record(response) ? response.usage : null);
    if (!usage) {
      entry.reason = "사용량 정보가 없거나 불완전해 비용을 모두 계산하지 못했어요.";
      return;
    }
    entry.usage = usage;
    const model = record(response) && response.model !== undefined ? response.model : entry.requestedModel;
    const price = typeof model === "string" && Object.hasOwn(PRICES, model) ? PRICES[model] : undefined;
    if (!price) {
      entry.reason = "이 모델의 확인된 요금표가 없어 비용을 계산하지 못했어요.";
      return;
    }
    // runChatTurn explicitly requests Standard. A returned override is not
    // charged as Standard merely because the requested model is recognized.
    if (record(response) && response.service_tier !== undefined && response.service_tier !== "default") {
      entry.reason = "응답의 처리 요금이 기본 요금과 달라 비용을 계산하지 못했어요.";
      return;
    }
    const longContext = usage.input > 272_000;
    const inputMultiplier = longContext ? 2 : 1;
    const outputMultiplier = longContext ? 1.5 : 1;
    const ordinary = usage.input - usage.cached - usage.write30m - usage.write12h;
    // output_tokens already includes reasoning tokens; never add them again.
    entry.usd = ((ordinary * price.input + usage.cached * price.cached +
      usage.write30m * price.input * 1.25 + usage.write12h * price.input * 2.5) * inputMultiplier +
      usage.output * price.output * outputMultiplier) / 1_000_000;
    delete entry.reason;
  }

  snapshot(): ChatCost {
    const priced = this.entries.filter((entry) => entry.usd !== null);
    const unknownCalls = this.entries.length - priced.length;
    const usd = !this.entries.length || priced.length ? priced.reduce((sum, entry) => sum + entry.usd!, 0) : null;
    const reasons = [...new Set(this.entries.flatMap((entry) => entry.reason ? [entry.reason] : []))];
    return {
      status: !unknownCalls ? "estimated" : priced.length ? "partial" : "unavailable",
      usd, krw: usd === null ? null : usd * this.usdKrw, usdKrw: this.usdKrw,
      calls: this.entries.length, pricedCalls: priced.length, unknownCalls,
      inputTokens: this.entries.reduce((sum, entry) => sum + (entry.usage?.input ?? 0), 0),
      cachedInputTokens: this.entries.reduce((sum, entry) => sum + (entry.usage?.cached ?? 0), 0),
      outputTokens: this.entries.reduce((sum, entry) => sum + (entry.usage?.output ?? 0), 0),
      pricingDate: CHAT_PRICING_DATE,
      ...(reasons.length ? { reason: reasons.join(" ") } : {}),
    };
  }
}
