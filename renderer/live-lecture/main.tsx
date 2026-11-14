import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { clock, conceptKey, conceptQuestion, hasSpeechContent, type LiveBridge, type LiveState, type Segment, type Suggestion } from "../../shared/live-lecture.js";
import { prepareMicrophone } from "./mic.js";
import "./style.css";
import { LectureChat } from "./lecture-chat.js";
import { LectureRecordView } from "./record-view.js";

declare global {
  interface Window { lecture: LiveBridge }
}
const api = window.lecture;
const initial: LiveState = {
  phase: "idle", segments: [], captions: [], suggestions: [], startedAt: null, elapsedMs: 0,
  message: "", aiMessage: "", reviewStatus: "waiting", gaps: 0, demo: false,
};
const working = new Set(["connecting", "listening", "reconnecting"]);

function ResizeGrip({ label }: { label: string }) {
  const drag = useRef<{ pointer: number; x: number; y: number; width: number; height: number } | null>(null);
  const frame = useRef<number>(0);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  function resizeTo(x: number, y: number, immediately = false) {
    const start = drag.current;
    if (!start) return;
    cancelAnimationFrame(frame.current);
    const width = Math.round(start.width + start.x - x);
    const height = Math.round(start.height + y - start.y);
    const resize = () => { void api.resize(width, height); };
    if (immediately) resize();
    else frame.current = requestAnimationFrame(resize);
  }

  return <button type="button" className="resize-grip" aria-label={label} title={label}
    onPointerDown={(event) => {
      if (event.button !== 0 || drag.current) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { pointer: event.pointerId, x: event.screenX, y: event.screenY, width: window.outerWidth, height: window.outerHeight };
    }}
    onPointerMove={(event) => {
      if (drag.current?.pointer === event.pointerId) resizeTo(event.screenX, event.screenY);
    }}
    onPointerUp={(event) => {
      if (drag.current?.pointer !== event.pointerId) return;
      resizeTo(event.screenX, event.screenY, true);
      drag.current = null;
    }}
    onLostPointerCapture={(event) => {
      if (drag.current?.pointer !== event.pointerId) return;
      cancelAnimationFrame(frame.current);
      drag.current = null;
    }}
    onKeyDown={(event) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      const width = window.outerWidth + (event.key === "ArrowLeft" ? 24 : event.key === "ArrowRight" ? -24 : 0);
      const height = window.outerHeight + (event.key === "ArrowDown" ? 24 : event.key === "ArrowUp" ? -24 : 0);
      void api.resize(width, height);
    }}><span aria-hidden="true"/></button>;
}

function Speaker({ speaker }: { speaker: number | null }) {
  return <span className={"speaker " + (speaker === 1 ? "primary-speaker" : "")}>{speaker === null ? "화자 확인 중" : "화자 " + speaker}</span>;
}

function TranscriptText({ segment, matches, open }: { segment: Segment; matches: Suggestion[]; open: (id: string) => void }) {
  const positions = matches.flatMap((item) => (item.positions ?? []).map((index) => ({ item, index })))
    .sort((a, b) => a.index - b.index || b.item.quote.length - a.item.quote.length);
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const { item, index } of positions) {
    if (index < cursor) continue;
    parts.push(segment.text.slice(cursor, index));
    parts.push(<button type="button" className={item.followUps.length ? "highlight highlight-featured" : "highlight"} key={item.id + ":" + index}
      title={item.concept + " 해설 열기"} onClick={() => open(item.id)}>{item.quote}</button>);
    cursor = index + item.quote.length;
  }
  parts.push(segment.text.slice(cursor));
  return parts;
}

function UtterancePrompt({ id, explain, dismiss }: { id: string; explain: () => void; dismiss: () => void }) {
  const prompt = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { prompt.current?.scrollIntoView({ block: "nearest" }); }, []);
  return <div className="utterance-prompt" id={id} ref={prompt} role="group" aria-label="이 발화를 설명할까요?">
    <p role="status">이 발화를 설명할까요?</p>
    <div>
      <button type="button" className="quiet" onClick={dismiss}>취소</button>
      <button type="button" className="utterance-confirm" onClick={explain}>설명하기</button>
    </div>
  </div>;
}

const ConfirmedSpeech = memo(function ConfirmedSpeech({ segments, suggestions, open, selected, select }: {
  segments: Segment[];
  suggestions: Suggestion[];
  open: (id: string) => void;
  selected?: string;
  select: (id?: string) => void;
}) {
  const bySegment = new Map<string, Suggestion[]>();
  for (const item of suggestions) {
    const entries = bySegment.get(item.segmentId);
    if (entries) entries.push(item);
    else bySegment.set(item.segmentId, [item]);
  }
  return segments.map((segment) => {
    const explainable = hasSpeechContent(segment.text);
    const expanded = selected === segment.id;
    const promptId = "utterance-prompt-" + segment.id;
    return <article className={"utterance" + (expanded ? " utterance-selected" : "")} key={segment.id}
      onKeyDown={expanded ? (event) => { if (event.key === "Escape") select(); } : undefined}>
      <div className={explainable ? "utterance-selectable" : undefined}
        onClick={explainable ? (event) => {
          if ((event.target as Element).closest("button") || window.getSelection()?.type === "Range") return;
          select(expanded ? undefined : segment.id);
        } : undefined}>
        <div className="utterance-meta">
          <Speaker speaker={segment.speaker}/><time>{clock(segment.startMs)}</time>
          {explainable && <button type="button" className="utterance-toggle" title="발화 해설"
            aria-label={clock(segment.startMs) + " 발화 해설"} aria-expanded={expanded}
            aria-controls={expanded ? promptId : undefined} onClick={() => select(expanded ? undefined : segment.id)}>↳</button>}
        </div>
        <p><TranscriptText segment={segment} matches={bySegment.get(segment.id) ?? []} open={open}/></p>
      </div>
      {expanded && <UtterancePrompt id={promptId} dismiss={() => select()} explain={() => {
        select();
        void api.explainUtterance(segment.id);
      }}/>}
    </article>;
  });
});

function suggestionCards(suggestions: Suggestion[]) {
  const byConcept = new Map<string, Suggestion>();
  for (const item of suggestions) {
    const key = conceptKey(item.concept);
    const previous = byConcept.get(key);
    const featured = item.followUps.length > 0;
    const previousFeatured = Boolean(previous?.followUps.length);
    if (!previous || (featured && !previousFeatured)
      || (featured === previousFeatured && item.startMs >= previous.startMs)) {
      byConcept.set(key, item);
    }
  }
  return [...byConcept.values()].sort((a, b) => Number(b.followUps.length > 0) - Number(a.followUps.length > 0)
    || b.startMs - a.startMs);
}

function Overlay() {
  const [state, setState] = useState(initial);
  const [config, setConfig] = useState<{ soniox: boolean; openai: boolean }>();
  const [active, setActive] = useState<string>();
  const [utterance, selectUtterance] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [now, setNow] = useState(Date.now);
  const mic = useRef<Awaited<ReturnType<typeof prepareMicrophone>>>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const nearEnd = () => {
    const box = scroll.current;
    if (box) follow.current = box.scrollHeight - box.scrollTop - box.clientHeight < 35;
  };

  useEffect(() => {
    const remove = api.subscribe((event) => {
      if (event.type === "state") setState(event.state);
      else if (event.type === "captions") setState((value) => ({ ...value, captions: event.captions }));
      else if (event.type === "explanation") setActive(event.explanation?.item.id);
      else if (!event.view.open) setActive(undefined);
    });
    void api.state().then(setState);
    void api.config().then(setConfig);
    return () => { remove(); mic.current?.dispose(); };
  }, []);

  useEffect(() => {
    if (!state.startedAt) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [state.startedAt]);

  useEffect(() => {
    if (state.phase === "error" || state.phase === "ended" || state.phase === "paused") {
      mic.current?.dispose();
      mic.current = null;
    }
  }, [state.phase]);

  useLayoutEffect(() => {
    const box = scroll.current;
    if (box && follow.current && !utterance) box.scrollTop = box.scrollHeight;
  }, [state.segments, state.captions, utterance]);

  useEffect(() => {
    const box = scroll.current;
    if (!box) return;
    const observer = new ResizeObserver(() => {
      if (follow.current && !box.querySelector(".utterance-prompt")) box.scrollTop = box.scrollHeight;
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (utterance && !state.segments.some(({ id }) => id === utterance)) selectUtterance(undefined);
  }, [state.segments, utterance]);

  async function start(demo = false, resume = false) {
    setBusy(true);
    setNotice("");
    selectUtterance(undefined);
    follow.current = true;
    try {
      const request = resume ? api.resume : demo ? api.demo : api.start;
      if (demo || !config?.soniox || !config.openai) {
        const result = await request();
        if (!result.ok) setNotice(result.message);
        return;
      }
      const input = await prepareMicrophone();
      try {
        const result = await request();
        if (!result.ok) { setNotice(result.message); input.dispose(); return; }
        mic.current = input;
        input.start(api.audio, () => {
          mic.current?.dispose();
          mic.current = null;
          setNotice("마이크 연결이 끊겼어요. 장치를 확인한 뒤 강의 해설을 재개해 주세요.");
          void api.pause();
        });
      } catch (error) {
        input.dispose();
        await api.stop().catch(() => {});
        throw error;
      }
    } catch (error) {
      const name = error instanceof Error ? error.name : "";
      setNotice(name === "NotAllowedError"
        ? "시스템 설정에서 이 앱의 마이크 접근을 허용해 주세요."
        : "마이크를 열지 못했어요. 입력 장치와 연결 상태를 확인해 주세요.");
    } finally { setBusy(false); }
  }

  async function stop(pause = false) {
    setBusy(true);
    try {
      const input = mic.current;
      mic.current = null;
      try { if (input) await input.stop(); }
      finally { await (pause ? api.pause() : api.stop()); }
    } finally { setBusy(false); }
  }

  const live = working.has(state.phase);
  const paused = state.phase === "paused";
  const transitioning = state.phase === "pausing" || state.phase === "stopping";
  const canStart = !live && !paused && !transitioning;
  const visible = suggestionCards(state.suggestions);
  const canExplain = state.segments.some(({ text }) => hasSpeechContent(text));
  const emptySuggestion = state.reviewStatus === "checking" ? "최근 발화를 검토하고 있어요."
    : state.reviewStatus === "checked" ? "새 해설 제안이 없어요."
    : "확정된 발화에서 설명할 개념을 찾아요.";
  const hasSpeech = Boolean(state.segments.length || state.captions.length);
  const open = useCallback((id: string) => {
    selectUtterance(undefined);
    void api.explain(id);
  }, []);
  const status = state.demo && live ? "미리보기" : ({
    idle: "대기 중", connecting: "연결 중", listening: "듣는 중", reconnecting: "재연결 중",
    pausing: "일시 중지 중", paused: "일시 중지됨", stopping: "마무리 중", ended: "종료됨", error: "연결 확인",
  })[state.phase];

  return <div className="overlay">
    <header className="titlebar">
      <span className="brand-icon" aria-hidden="true"><i/><i/><i/><i/><i/></span>
      <h1>라이브 강의 해설</h1>
      <span className="grip" aria-hidden="true"><i/><i/><i/></span>
      <button type="button" className="icon close" title="창 닫기" aria-label="창 닫기" onClick={() => void api.close()}>×</button>
    </header>
    <div className="controls">
      <div className="status">
        <span className={"status-dot " + (live ? "live" : "")} />
        <span role="status">{status}</span>
        {(state.startedAt !== null || state.elapsedMs > 0) && <time>{clock(state.elapsedMs + (state.startedAt === null ? 0 : Math.max(0, now - state.startedAt)))}</time>}
      </div>
      <div className="control-actions">
        {canStart && <button type="button" className="quiet" disabled={busy} onClick={() => void start(true)}>미리보기</button>}
        {canStart && <button type="button" className="action" disabled={busy} onClick={() => void start()}>강의 해설 시작</button>}
        {(live || state.phase === "pausing") && <button type="button" className="action stop" disabled={busy || transitioning}
          onClick={() => void stop(true)}>강의 해설 일시 중지</button>}
        {paused && <button type="button" className="action" disabled={busy} onClick={() => void start(state.demo, true)}>강의 해설 재개</button>}
        {!canStart && <button type="button" className="action stop end-action" disabled={busy || transitioning}
          onClick={() => void stop()}>강의 해설 종료</button>}
      </div>
    </div>
    <main className="columns">
      <section className="transcript column" aria-labelledby="transcript-label">
        <div className="column-heading"><h2 id="transcript-label">강의록</h2>{state.segments.length > 0 && <span>{state.segments.length}개 발화</span>}</div>
        <div className="feed" ref={scroll} onScroll={nearEnd}>
          {!hasSpeech && <div className="empty">
            <div className="empty-bars" aria-hidden="true"><i/><i/><i/><i/><i/></div>
            <p>{live ? "발화를 기다리고 있어요." : "강의록이 여기에 표시돼요."}</p>
          </div>}
          <ConfirmedSpeech segments={state.segments} suggestions={state.suggestions} open={open}
            selected={utterance} select={selectUtterance}/>
          {state.captions.map((caption, index) => <article className="utterance provisional" key={index}>
            <div className="utterance-meta"><Speaker speaker={caption.speaker}/><span>인식 중</span></div><p>{caption.text}</p>
          </article>)}
        </div>
      </section>
      <section className="suggestions column" aria-labelledby="suggestion-label">
        <div className="column-heading">
          <h2 id="suggestion-label">해설 제안</h2>
          {state.reviewStatus === "checking" && visible.length > 0 && <span role="status">검토 중</span>}
        </div>
        {canExplain && <button type="button" className="quiet recent-explain" onClick={() => void api.explainRecent()}>
          <span aria-hidden="true">✦</span> 방금 내용 해설
        </button>}
        <div className="cards">
          {!visible.length && <div className="empty" role="status">
            <span className="empty-spark" aria-hidden="true">✧</span>
            <p>{emptySuggestion}</p>
          </div>}
          {visible.map((item) => <button type="button" className="card" key={conceptKey(item.concept)}
            title={item.concept + " 해설 열기"} aria-pressed={active === item.id} onClick={() => open(item.id)}>
            <span className="card-title">{conceptQuestion(item.concept)}</span>
            <span className="card-meta"><time>{clock(item.startMs)}</time><span aria-hidden="true">↘</span></span>
          </button>)}
        </div>
      </section>
    </main>
    {(notice || state.message || state.aiMessage || state.gaps > 0) && <div className="notice" role="status">
      {notice || state.message || state.aiMessage || `전사 연결이 끊겨 ${state.gaps}개 구간에 자막이 빠졌어요.`}
    </div>}
    <footer className="overlay-footer">
      <span className="providers">Soniox <span>·</span> GPT</span>
    </footer>
    <ResizeGrip label="강의록 창 크기 조절"/>
  </div>;
}

const chatWindow = location.hash === "#chat";
if (chatWindow) document.documentElement.classList.add("chat-window");
createRoot(document.getElementById("root")!).render(chatWindow ? <LectureChat api={api}/>
  : location.hash.startsWith("#record/") ? <LectureRecordView/> : <Overlay/>);
