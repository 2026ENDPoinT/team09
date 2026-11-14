import type { Caption, Explanation, LiveState, Phase, Segment, Suggestion } from "../../shared/live-lecture.js";
import { conceptKey, conceptQuestion, hasSpeechContent } from "../../shared/live-lecture.js";
import type { AssistModel, ExplainInput } from "./gpt.js";

const historySize = 100;
const analysisSpacing = 5_000;
const contextWait = 1_200;
const conceptWindow = 90_000;
const recentExplanationId = "recent-explanation";
const utteranceExplanationPrefix = "utterance:";

const canReview = (phase: Phase) => ["listening", "reconnecting", "paused", "ended", "error"].includes(phase);
type ExplanationContext = { demo: boolean; recent: Segment[]; evidence?: Segment };

const wordCharacterAtEnd = /[\p{L}\p{M}\p{N}\p{Pc}]$/u;
const wordCharactersAtStart = /^[\p{L}\p{M}\p{N}\p{Pc}]+/u;
const koreanSuffix = /^(?:에서|에게|한테|께서|으로서|으로써|으로|로|에|의|은|는|이|가|을|를|과|와|부터|까지|이랑|랑|마다|처럼|만큼|보다|밖에|만|도|들|이라고|라고|이라는|라는|이며|이고|이다|입니다|이에요|예요)+$/u;

function quotePositions(text: string, quote: string) {
  const positions: number[] = [];
  for (let index = text.indexOf(quote); index >= 0; index = text.indexOf(quote, index + quote.length)) {
    if (wordCharacterAtEnd.test(text.slice(0, index))) continue;
    const suffix = text.slice(index + quote.length).match(wordCharactersAtStart)?.[0];
    if (!suffix || (suffix.length <= 8 && koreanSuffix.test(suffix))) positions.push(index);
  }
  return positions;
}

const demoLines = [
  { speaker: 1, text: "오늘은 C++에서 객체를 다른 객체에 넘겨줄 때 무슨 일이 일어나는지 볼게요." },
  { speaker: 1, text: "여기서 원본 객체를 새 객체에 넘기면 복사 생성자가 호출돼요. 두 객체가 같은 메모리를 가리킬 수도 있어요." },
  { speaker: 2, text: "그러면 한쪽 객체를 지웠을 때 다른 객체에도 문제가 생기나요?" },
  { speaker: 1, text: "맞아요. 둘 다 같은 곳을 가리키고 있다면 먼저 없어진 쪽이 메모리를 해제할 수 있어요." },
  { speaker: 1, text: "여기서는 깊은 복사를 이용해서 각각 자기 메모리를 가지도록 고칠 수 있어요." },
  { speaker: 2, text: "이제 한쪽의 값을 바꿔도 다른 쪽에는 영향을 주지 않겠네요." },
];

const demoConceptsByLine = [
  ["객체"],
  ["복사 생성자", "객체", "메모리"],
  ["객체"],
  ["메모리"],
  ["깊은 복사", "메모리"],
  [],
];

const demoUtteranceExplanations = [
  "한 객체의 데이터를 새 객체로 넘길 때 내부에서 어떤 일이 생기는지 살펴보겠다는 말이에요.\n\n수업의 주제를 여는 발화예요. 뒤이어 나올 복사 생성자와 메모리 공유 이야기는 이 상황을 설명하는 내용이에요.",
  "기존 객체로 새 객체를 만들 때 복사 생성자가 불려요. 이때 객체가 들고 있는 주소만 복사되면 두 객체가 같은 데이터를 가리킬 수 있다는 뜻이에요.\n\n앞에서 객체를 넘길 때 무슨 일이 생기는지 보겠다고 했어요. 여기서는 복사가 일어나는 순간과 두 객체가 공유할 수 있는 것을 짚고 있어요.",
  "‘한쪽’과 ‘다른 객체’는 앞에서 같은 메모리를 가리킬 수 있다고 한 원본과 복사본이에요. 화자 2는 그중 하나가 사라졌을 때 남은 쪽도 영향을 받는 상황인지 묻고 있어요.\n\n직전에는 주소를 공유할 수 있다는 설명이 나왔어요. 화자 2는 그 설명을 객체가 사라지는 경우에 적용해 보고, 메모리를 공유하는 게 실제로 어떤 문제로 이어지는지 확인하고 있어요.",
  "‘같은 곳’은 두 객체가 가리키는 메모리예요. 먼저 없어진 객체가 그 메모리를 해제하면, 남은 객체가 쓰던 공간도 사라질 수 있다는 뜻이에요.\n\n화자 2가 한쪽 객체를 지우면 다른 쪽에도 문제가 생기는지 물었어요. 화자 1은 공유한 메모리를 해제하는 상황을 들어 왜 그런 문제가 생길 수 있는지 설명하고 있어요.",
  "‘각각 자기 메모리’는 원본과 복사본이 데이터를 따로 보관한다는 뜻이에요. 깊은 복사를 하면 주소가 가리키던 데이터까지 새 공간에 복사할 수 있어요.\n\n직전에는 한 객체가 공유 메모리를 해제하면 다른 객체도 그 공간을 잃을 수 있다고 했어요. 화자 1은 그 문제를 해결할 방법으로 깊은 복사를 제시하고 있어요.",
  "‘한쪽’과 ‘다른 쪽’은 원본 객체와 복사한 객체예요. ‘이제’는 바로 앞에서 설명한 깊은 복사를 적용한 뒤를 가리켜요. 두 객체가 데이터를 따로 가지니 한쪽 값을 바꿔도 다른 쪽 값은 그대로라는 뜻이에요.\n\n화자 1은 앞서 메모리를 공유할 때 생기는 문제를 설명한 뒤, 각 객체가 자기 메모리를 갖도록 고치는 방법을 제시했어요. 화자 2는 그 방법을 값 변경에 적용해 보고, 두 객체의 데이터가 독립적이라는 결론을 자기 말로 확인하고 있어요.",
];

const demoConceptExplanations: Record<string, string> = {
  객체: "객체는 프로그램에서 데이터와 그 데이터를 다루는 동작을 묶어 쓰는 단위예요. 이 예제에서는 원본 객체의 데이터를 새 객체로 옮길 때 두 객체가 같은 메모리를 공유하는지를 살펴보고 있어요.",
  메모리: "메모리는 프로그램이 실행되는 동안 데이터를 두는 공간이에요. 두 객체가 같은 주소를 가지고 있으면 같은 메모리를 참조해요. 한쪽에서 그 공간을 해제하면 다른 쪽은 그 주소를 안전하게 사용할 수 없어요.",
};

const demoFollowUps: Record<string, Record<string, string>> = {
  "복사 생성자": {
    "언제 호출될까요?": "이미 있는 객체로 새 객체를 초기화할 때 호출돼요. 예를 들어 C++에서 Book copy = original;처럼 새 객체를 만들면 원본을 바탕으로 복사 생성자가 실행돼요.",
  },
  "깊은 복사": {
    "주소만 복사할 때와 뭐가 다를까요?": "주소만 복사하면 원본과 복사본이 같은 데이터를 가리켜요. 깊은 복사를 하면 데이터도 새 공간에 담으므로 두 객체가 서로 다른 곳을 가리켜요. 강의에서는 이 차이가 한쪽 객체의 메모리를 해제할 때 중요해요.",
    "왜 한쪽을 바꿔도 다른 쪽은 그대로일까요?": "깊은 복사를 한 뒤에는 원본과 복사본의 데이터가 서로 다른 공간에 있어요. 예를 들어 두 객체가 각각 숫자 3을 갖고 있을 때 복사본의 숫자만 7로 바꾸면 원본은 여전히 3이에요.",
  },
};

const demoModel: AssistModel = {
  async review({ recent, targetIds }) {
    return recent.filter(({ id }) => targetIds.includes(id)).flatMap(({ id }) =>
      (demoConceptsByLine[Number(id) - 1] ?? []).map((concept) => ({
        segmentId: id, quote: concept, concept, followUps: Object.keys(demoFollowUps[concept] ?? {}),
      })));
  },
  async explain({ item, request, followUp }, signal, delta) {
    const selected = request === "question" ? "미리보기에서는 예시 강의의 답변을 보여줘요.\n\n" + (Object.entries(demoConceptExplanations)
      .find(([concept]) => item.quote.includes(concept))?.[1] ?? demoUtteranceExplanations[4])
      : request === "utterance" ? demoUtteranceExplanations[Number(item.segmentId) - 1]
      : followUp ? demoFollowUps[item.concept]?.[followUp]
      : request === "concept" ? demoConceptExplanations[item.concept] : undefined;
    const lines = selected ? [selected] : request === "recent" || item.concept === "복사 생성자"
      ? ["복사 생성자는 이미 있는 객체를 바탕으로 새 객체를 초기화하는 함수예요. 예를 들어 C++에서 객체를 값으로 넘기면, 그 객체로부터 새 객체를 복사해 만들 수 있어요.\n\n",
        "방금 강의에서는 새 객체에 주소만 복사했을 때의 문제를 짚었어요. 두 객체가 같은 메모리를 자기 것처럼 다루면, 한쪽이 메모리를 해제한 뒤 다른 쪽이 그 주소를 다시 사용할 수 있어요."]
      : ["깊은 복사는 원본의 데이터를 복사본의 공간에 따로 담는 방식이에요. 예를 들어 사진 목록을 복사하면서 목록에 들어 있는 사진도 새 폴더에 함께 복사하는 것과 비슷해요.\n\n",
        "강의에서는 원본 객체와 복사한 객체가 각자 데이터를 보관하도록 깊은 복사를 사용했어요."];
    for (const line of lines) {
      const chars = Array.from(line);
      for (let offset = 0; offset < chars.length; offset += 10) {
        signal.throwIfAborted();
        delta(chars.slice(offset, offset + 10).join(""));
        await new Promise((resolve) => setTimeout(resolve, 23));
      }
    }
    return lines.join("");
  },
};

type Change = {
  state(value: LiveState): void;
  captions(value: Caption[]): void;
  explanation(value: Explanation | null): void;
  archiveSegment?(value: Segment): void;
  archiveSuggestions?(value: Suggestion[]): void;
  demoEnded?(): void;
};

export class AssistSession {
  private state: LiveState = {
    phase: "idle", segments: [], captions: [], suggestions: [], startedAt: null, elapsedMs: 0,
    message: "", aiMessage: "", reviewStatus: "waiting", gaps: 0, demo: false,
  };
  private recording = 0;
  private run = new AbortController();
  private pending = new Set<string>();
  private reviewTimer?: ReturnType<typeof setTimeout>;
  private demoTimer?: ReturnType<typeof setTimeout>;
  private demoIndex = 0;
  private reviewing = false;
  private nextReview = 0;
  private explanation: Explanation | null = null;
  private turn = 0;
  private chatHistory: NonNullable<ExplainInput["history"]> = [];
  private explaining?: AbortController;
  private explanationTimer?: ReturnType<typeof setTimeout>;
  private suggestionContext = new Map<string, ExplanationContext>();
  private manualExplanation?: { item: Suggestion; context: ExplanationContext; request: "recent" | "utterance" };
  private activeConcept?: { item: Suggestion; context: ExplanationContext; basicText?: string };

  constructor(private readonly model: AssistModel, private readonly change: Change) {}

  get current() { return this.state; }
  get detail() { return this.explanation; }

  update(values: Partial<LiveState>) {
    this.state = { ...this.state, ...values };
    this.change.state(this.state);
  }

  setCaptions(captions: Caption[]) {
    const previous = this.state.captions;
    if (captions.length === previous.length && captions.every((caption, index) =>
      caption.speaker === previous[index].speaker && caption.text === previous[index].text)) return;
    this.state = { ...this.state, captions };
    this.change.captions(captions);
  }

  begin(demo: boolean) {
    this.pauseReview();
    this.run = new AbortController();
    this.recording++;
    this.demoIndex = 0;
    this.suggestionContext.clear();
    this.nextReview = 0;
    this.update({
      phase: demo ? "listening" : "connecting", segments: [], captions: [], suggestions: [],
      startedAt: Date.now(), elapsedMs: 0, demo, message: "", aiMessage: "", reviewStatus: "waiting", gaps: 0,
    });
    if (demo) this.playDemo();
  }

  resume() {
    this.update({ phase: this.state.demo ? "listening" : "connecting", startedAt: Date.now(), message: "" });
    if (this.state.demo) this.playDemo();
  }

  private playDemo(index = this.demoIndex) {
    const line = demoLines[index];
    if (!line) {
      this.demoTimer = setTimeout(() => {
        if (this.change.demoEnded) this.change.demoEnded();
        else this.phase("ended");
      }, 5_500);
      return;
    }
    this.demoTimer = setTimeout(() => {
      this.setCaptions([line]);
      this.demoTimer = setTimeout(() => {
        const endMs = this.state.elapsedMs + Date.now() - (this.state.startedAt ?? Date.now());
        this.add({ ...line, id: String(index + 1), startMs: Math.max(0, endMs - 1_300), endMs });
        this.setCaptions([]);
        this.demoIndex = index + 1;
        this.playDemo();
      }, index === 0 ? 900 : 1_450);
    }, index === 4 ? 4_400 : index === 0 ? 350 : 1_000);
  }

  add(segment: Segment) {
    this.change.archiveSegment?.(segment);
    const segments = [...this.state.segments, segment].slice(-historySize);
    const removed = this.state.segments.length === historySize ? this.state.segments[0].id : undefined;
    let suggestions = this.state.suggestions;
    if (removed !== undefined) {
      this.pending.delete(removed);
      suggestions = suggestions.filter(({ id, segmentId }) => {
        if (segmentId !== removed) return true;
        this.suggestionContext.delete(id);
        return false;
      });
    }
    this.update({ segments, suggestions });
    if (this.run.signal.aborted || this.state.phase === "idle" || !hasSpeechContent(segment.text)) return;
    this.pending.add(segment.id);
    this.schedule();
  }

  phase(phase: Phase, message = "") {
    const frozen = phase === "pausing" || phase === "paused" || phase === "stopping" || phase === "ended" || phase === "error";
    const elapsedMs = this.state.elapsedMs + (this.state.startedAt === null ? 0 : Date.now() - this.state.startedAt);
    this.update({ phase, message, ...(frozen ? { startedAt: null, elapsedMs, captions: [] } : {}) });
    if (frozen) {
      clearTimeout(this.demoTimer);
      clearTimeout(this.reviewTimer);
      this.reviewTimer = undefined;
    }
    this.schedule();
  }

  private schedule() {
    if (this.reviewTimer || this.reviewing || this.run.signal.aborted || !this.pending.size) return;
    if (!canReview(this.state.phase)) return;
    const finished = this.state.phase === "paused" || this.state.phase === "ended" || this.state.phase === "error";
    this.reviewTimer = setTimeout(() => {
      this.reviewTimer = undefined;
      if (canReview(this.state.phase)) void this.review();
    }, finished ? 0 : Math.max(contextWait, this.nextReview - Date.now()));
  }

  private async review() {
    const signal = this.run.signal;
    if (signal.aborted) return;
    const segments = this.state.segments;
    const latest = segments.at(-1)?.endMs ?? 0;
    const recent = segments.filter(({ endMs }) => latest - endMs < 45_000).slice(-16);
    const eligible = new Set(recent.filter(({ endMs }) => latest - endMs <= 35_000).map(({ id }) => id));
    for (const id of this.pending) if (!eligible.has(id)) this.pending.delete(id);
    const targetIds = [...this.pending].slice(0, 6);
    for (const id of targetIds) this.pending.delete(id);
    if (!targetIds.length) return;
    this.reviewing = true;
    this.update({ reviewStatus: "checking", aiMessage: "" });
    this.nextReview = Date.now() + (this.state.demo ? 1_300 : analysisSpacing);
    const demo = this.state.demo;
    const known = [...new Set(this.state.suggestions
      .filter(({ startMs }) => latest - startMs < conceptWindow)
      .map(({ concept }) => concept))].slice(-12);
    try {
      const candidates = await (demo ? demoModel : this.model).review({ recent, targetIds, known }, signal);
      if (signal.aborted) return;
      const suggestions = [...this.state.suggestions];
      const liveEnd = this.state.segments.at(-1)?.endMs ?? latest;
      for (const candidate of candidates) {
        const evidence = recent.find(({ id }) => id === candidate.segmentId);
        const quote = candidate.quote.trim();
        const concept = candidate.concept.trim().slice(0, 64);
        const key = conceptKey(concept);
        if (!evidence || !targetIds.includes(evidence.id) || liveEnd - evidence.endMs > 35_000
          || !key || !conceptKey(quote) || quote.length > 85) continue;
        const positions = quotePositions(evidence.text, quote);
        if (!positions.length) continue;
        if (suggestions.some((item) => item.segmentId === evidence.id
          && (item.quote === quote || conceptKey(item.concept) === key))) continue;
        const item: Suggestion = {
          id: `${this.recording}:${evidence.id}:${quote}`,
          segmentId: evidence.id, quote, concept, positions,
          followUps: candidate.followUps,
          startMs: evidence.startMs,
        };
        this.suggestionContext.set(item.id, { demo, recent, evidence });
        suggestions.push(item);
      }
      const visible = new Set(this.state.segments.map(({ id }) => id));
      const added = suggestions.slice(this.state.suggestions.length).filter(({ segmentId }) => visible.has(segmentId));
      if (added.length) this.change.archiveSuggestions?.(added);
      const retained = suggestions.filter(({ segmentId }) => visible.has(segmentId));
      const retainedIds = new Set(retained.map(({ id }) => id));
      for (const id of this.suggestionContext.keys()) if (!retainedIds.has(id)) this.suggestionContext.delete(id);
      this.update({ suggestions: retained, aiMessage: "", reviewStatus: "checked" });
    } catch (error) {
      if (!signal.aborted) {
        this.nextReview = Date.now() + 20_000;
        this.update({ reviewStatus: "checked", aiMessage: error instanceof Error && !/abort|JSON|terminated|fetch/i.test(error.message)
          ? error.message : "해설 제안을 확인하지 못했어요." });
      }
    } finally {
      if (!signal.aborted) {
        this.reviewing = false;
        this.schedule();
      }
    }
  }

  private emitExplanation(value: Explanation | null) {
    this.explanation = value;
    this.change.explanation(value);
  }

  explainRecent() {
    const segments = this.state.segments.filter(({ text }) => hasSpeechContent(text));
    const latest = segments.at(-1);
    const id = `${recentExplanationId}:${this.recording}`;
    if (!latest) return;
    if (this.explanation?.item.id === id && this.explanation.state === "loading") return true;
    const recent = segments.filter(({ endMs }) => latest.endMs - endMs < 45_000).slice(-10);
    const evidence = [...recent].reverse().find(({ text }) => conceptKey(text).length >= 8
      && !/^(?:해설|설명).{0,12}(?:줘|하지|줄)/u.test(text)) ?? latest;
    const item: Suggestion = {
      id, segmentId: evidence.id, quote: evidence.text,
      concept: "방금 내용 해설", followUps: [], startMs: evidence.startMs,
    };
    const demo = this.state.demo;
    const context = { demo, recent, evidence };
    this.manualExplanation = { item, context, request: "recent" };
    return this.generate(item, context, "recent");
  }

  explainUtterance(segmentId: string) {
    const segments = this.state.segments;
    const index = segments.findIndex(({ id }) => id === segmentId);
    const evidence = segments[index];
    const id = `${utteranceExplanationPrefix}${this.recording}:${segmentId}`;
    if (!evidence || !hasSpeechContent(evidence.text)) return;
    if (this.explanation?.item.id === id && this.explanation.state !== "error") return true;
    const recent = segments.slice(Math.max(0, index - 5), index + 3)
      .filter((segment) => Math.abs(segment.startMs - evidence.startMs) <= 45_000);
    const item: Suggestion = {
      id, segmentId, quote: evidence.text,
      concept: "발화 해설", followUps: [], startMs: evidence.startMs,
    };
    const context = { demo: this.state.demo, recent, evidence };
    this.manualExplanation = { item, context, request: "utterance" };
    return this.generate(item, context, "utterance");
  }

  ask(question: string) {
    const recent = this.state.segments.slice(-10);
    const demo = this.state.demo;
    const item: Suggestion = {
      id: "chat-question", segmentId: "", quote: question, concept: "강의 질문", followUps: [], startMs: 0,
    };
    return this.generate(item, { demo, recent }, "question");
  }

  explain(id: string, followUp?: string) {
    const opened = this.explanation?.item.id === id ? this.explanation : null;
    if (opened && opened.followUp === followUp && opened.state !== "error") return true;
    if (followUp === undefined && this.manualExplanation?.item.id === id) {
      const { item, context, request } = this.manualExplanation;
      return this.generate(item, context, request);
    }
    const active = this.activeConcept?.item.id === id ? this.activeConcept : undefined;
    const item = active?.item ?? this.state.suggestions.find((candidate) => candidate.id === id);
    const context = active?.context ?? this.suggestionContext.get(id);
    if (item && context && (followUp === undefined || item.followUps.includes(followUp))) {
      this.activeConcept = active ?? { item, context };
      return this.generate(item, context, "concept", followUp);
    }
  }

  private async generate(item: Suggestion, context: ExplanationContext, request: ExplainInput["request"], followUp?: string) {
    this.explaining?.abort();
    clearTimeout(this.explanationTimer);
    if (request !== "concept") this.activeConcept = undefined;
    const active = this.activeConcept;
    const { demo, ...lecture } = context;
    const question = request === "question" ? item.quote
      : request === "concept" ? followUp ?? conceptQuestion(item.concept) : item.concept;
    const turn = ++this.turn;
    const base = () => ({
      turn, item: active?.item ?? item,
      evidence: lecture.evidence, question, followUp,
    });
    if (followUp === undefined && active?.basicText !== undefined) {
      this.emitExplanation({ ...base(), state: "ready", text: active.basicText });
      return;
    }
    const controller = new AbortController();
    this.explaining = controller;
    const { signal } = controller;
    this.emitExplanation({ ...base(), state: "loading", text: "" });
    let text = "";
    let queued = false;
    try {
      const final = await (demo ? demoModel : this.model).explain({
        item, ...lecture, request, followUp, history: request === "question" ? this.chatHistory : undefined,
      }, signal, (chunk) => {
        if (signal.aborted) return;
        text += chunk;
        if (queued) return;
        queued = true;
        this.explanationTimer = setTimeout(() => {
          queued = false;
          if (!signal.aborted) this.emitExplanation({ ...base(), state: "loading", text });
        }, 42);
      });
      if (!signal.aborted) {
        clearTimeout(this.explanationTimer);
        if (active && followUp === undefined) active.basicText = final;
        this.chatHistory = [...this.chatHistory, { question, answer: final }].slice(-6);
        this.emitExplanation({ ...base(), state: "ready", text: final });
      }
    } catch (error) {
      if (!signal.aborted) {
        clearTimeout(this.explanationTimer);
        const message = error instanceof Error && /^GPT|^OpenAI|^해설/u.test(error.message) ? error.message : "해설을 받지 못했어요. 다시 시도해 주세요.";
        this.emitExplanation({ ...base(), state: "error", text: message });
      }
    }
  }

  private pauseReview() {
    clearTimeout(this.reviewTimer);
    clearTimeout(this.demoTimer);
    this.reviewTimer = undefined;
    this.reviewing = false;
    this.pending.clear();
    this.run.abort();
  }

  dispose() {
    this.pauseReview();
    this.explaining?.abort();
    clearTimeout(this.explanationTimer);
  }
}
