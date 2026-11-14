import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { chatQuestionLimit, clock, type ChatView, type Explanation, type LiveBridge } from "../../shared/live-lecture.js";
import "./lecture-chat.css";

type Turn = Explanation & { interrupted?: boolean };
const motionDuration = 490;

function SendIcon() {
  return <span className="send-arrow" aria-hidden="true"/>;
}

function Avatar() {
  return <span className="chat-avatar" aria-hidden="true"/>;
}

export function LectureChat({ api }: { api: LiveBridge }) {
  const [view, setView] = useState<ChatView>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [moving, setMoving] = useState(false);
  const spotlight = useRef<HTMLFormElement>(null);
  const panel = useRef<HTMLElement>(null);
  const composer = useRef<HTMLInputElement>(null);
  const orb = useRef<HTMLButtonElement>(null);
  const messages = useRef<HTMLDivElement>(null);
  const latest = useRef<HTMLElement>(null);
  const followScroll = useRef(true);
  const focusComposer = useRef(false);
  const motion = useRef<{ animations: Animation[] } | undefined>(undefined);
  const previous = useRef<ChatView | undefined>(undefined);
  const resize = useRef<{ id: number; x: number; y: number; width: number; height: number } | undefined>(undefined);

  useEffect(() => {
    let receivedView = false;
    let receivedTurn = false;
    function receive(data: Explanation | null) {
      setTurns((items) => {
        if (!data) return [];
        const tail = items.at(-1);
        if (tail?.turn === data.turn) return [...items.slice(0, -1), data];
        const finished = tail?.state === "loading" ? [...items.slice(0, -1), { ...tail, interrupted: true }] : items;
        return [...finished.slice(-39), data];
      });
    }
    const stop = api.subscribe((event) => {
      if (event.type === "chat-view") { receivedView = true; setView(event.view); }
      if (event.type === "explanation") { receivedTurn = true; receive(event.explanation); }
    });
    void api.chatView().then((initial) => { if (!receivedView) setView(initial); });
    void api.explanation().then((initial) => { if (!receivedTurn) receive(initial); });
    return () => {
      stop();
      for (const animation of motion.current?.animations ?? []) animation.cancel();
    };
  }, [api]);

  useLayoutEffect(() => {
    if (!view) return;
    const prior = previous.current;
    previous.current = view;
    if (!prior || prior.open === view.open) return;
    const finish = () => {
      if (!view.open) void api.finishChatClose(view.revision);
      else if (focusComposer.current) composer.current?.focus({ preventScroll: true });
      focusComposer.current = false;
    };
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !spotlight.current || !panel.current) {
      for (const animation of motion.current?.animations ?? []) animation.cancel();
      motion.current = undefined;
      setMoving(false);
      finish();
      return;
    }
    const existing = motion.current;
    const dx = view.orb.left + view.orb.width / 2 - (view.spotlight.left + view.spotlight.width / 2);
    const dy = view.orb.top + view.orb.height / 2 - (view.spotlight.top + view.spotlight.height / 2);
    const animations = existing?.animations ?? [
      spotlight.current.animate([
        { transform: "translate3d(0, 0, 0) scale(1)", opacity: 1 },
        { transform: `translate3d(${dx * .55}px, ${dy * .55}px, 0) scale(.58, .85)`, opacity: .95, offset: .48 },
        { transform: `translate3d(${dx}px, ${dy}px, 0) scale(.06, .12)`, opacity: 0 },
      ], { duration: 270, endDelay: 220, easing: "cubic-bezier(.5,.08,.36,1)", fill: "both" }),
      panel.current.animate([
        { clipPath: "inset(100% 0 0 round 18px)", transform: "translateY(7px) scale(.18,.78)", opacity: 0 },
        { clipPath: "inset(0 round 18px)", transform: "none", opacity: 1 },
      ], { duration: 340, delay: 150, easing: "cubic-bezier(.2,.82,.24,1)", fill: "both" }),
    ];
    for (const animation of animations) {
      if (!existing && !view.open) animation.currentTime = motionDuration;
      if (existing || !view.open) animation.reverse();
    }
    const current = { animations };
    motion.current = current;
    setMoving(true);
    void Promise.all(animations.map((animation) => animation.finished)).then(() => {
      if (motion.current !== current) return;
      motion.current = undefined;
      for (const animation of animations) animation.cancel();
      setMoving(false);
      finish();
    }, () => {});
  }, [api, view]);

  const active = turns.at(-1);
  useLayoutEffect(() => {
    followScroll.current = true;
    latest.current?.scrollIntoView({ block: "start" });
  }, [active?.turn, view?.open]);
  useLayoutEffect(() => {
    const container = messages.current;
    const turn = latest.current;
    if (container && turn && followScroll.current && turn.getBoundingClientRect().bottom > container.getBoundingClientRect().bottom) {
      container.scrollTop = container.scrollHeight;
    }
  }, [active?.text]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || moving) return;
    setDraft("");
    focusComposer.current = !view?.open;
    void api.ask(question);
  }

  function setOpen(open: boolean) {
    focusComposer.current = open;
    if (!open) orb.current?.focus({ preventScroll: true });
    void api.setChatOpen(open);
  }

  function protectComposition(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && (event.nativeEvent.isComposing || event.keyCode === 229)) event.preventDefault();
  }

  function answer(item: Turn, question?: string) {
    void api.explain(item.item.id, question);
  }

  if (!view) return null;
  return <div className="lecture-chat" data-open={view.open} data-moving={moving} onKeyDown={(event) => {
    if (view.open && event.key === "Escape" && !event.nativeEvent.isComposing) setOpen(false);
  }}>
    <form className="lecture-spotlight" ref={spotlight} style={view.spotlight} onSubmit={submit} inert={moving || view.open} aria-label="스포트라이트 질문">
      <span className="search-icon" aria-hidden="true"/>
      <input value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={protectComposition}
        placeholder="이 강의에 대해 물어보세요" aria-label="이 강의에 대해 물어보세요" maxLength={chatQuestionLimit}/>
      <button className="chat-send" type="submit" aria-label="질문 보내기" disabled={!draft.trim()}><SendIcon/></button>
    </form>
    <button className="lecture-orb" type="button" ref={orb} style={view.orb} aria-expanded={view.open} aria-controls="lecture-chat-panel"
      aria-label={view.open ? "강의 채팅 접기" : "강의 채팅 열기"} onClick={() => setOpen(!view.open)}><Avatar/></button>
    <section id="lecture-chat-panel" className="lecture-chat-panel" ref={panel} style={view.panel} inert={!view.open}
      role="dialog" aria-labelledby="lecture-chat-title">
      <header className="chat-header">
        <Avatar/><h1 id="lecture-chat-title">강의 채팅</h1>
        <button type="button" className="icon close" aria-label="강의 채팅 접기" onClick={() => setOpen(false)}>×</button>
      </header>
      <div className="chat-messages" ref={messages} onWheel={() => { followScroll.current = false; }} onPointerDown={() => { followScroll.current = false; }}>
        {!active && <p className="chat-empty">강의에 대해 질문하거나 강의록에서 밑줄 친 개념을 눌러보세요.</p>}
        {turns.map((item) => {
          const current = item.turn === active?.turn;
          const loading = item.state === "loading" && !item.interrupted;
          const followUps = item.item.followUps.filter((question) => question !== item.followUp);
          return <article className="chat-turn" key={item.turn} ref={current ? latest : undefined}>
            <h2 className="chat-question">{item.question ?? item.item.concept}</h2>
            <div className={current ? "explanation chat-answer" : "chat-answer"} aria-busy={loading}>
              {item.text || (item.interrupted ? "답변이 중단됐어요." : "강의 맥락을 살펴보고 있어요…")}
              {loading && item.text && <span className="cursor" aria-hidden="true"/>}
            </div>
            {item.interrupted && item.text && <p className="chat-interrupted">답변이 중단됐어요.</p>}
            {current && item.state === "error" && <button type="button" className="quiet retry" onClick={() => {
              if (item.item.id === "chat-question") void api.ask(item.item.quote);
              else answer(item, item.followUp);
            }}>다시 시도</button>}
            {item.evidence && <blockquote>
              <div><time>{clock(item.evidence.startMs)}</time> · {item.evidence.speaker === null ? "화자 확인 중" : `화자 ${item.evidence.speaker}`}</div>
              <p>{item.evidence.text}</p>
            </blockquote>}
            {current && item.state === "ready" && (followUps.length > 0 || item.followUp) && <section className="follow-ups" aria-label="이어서 궁금한 점">
              {item.followUp && <button type="button" className="back-to-basic" onClick={() => answer(item)}>기본 해설</button>}
              {followUps.length > 0 && <h2>이어서 궁금한 점</h2>}
              {followUps.map((question) => <button type="button" key={question} onClick={() => answer(item, question)}>
                <span>{question}</span><span aria-hidden="true">→</span>
              </button>)}
            </section>}
          </article>;
        })}
      </div>
      <form className="chat-composer" onSubmit={submit} aria-label="강의 채팅 질문">
        <input ref={composer} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={protectComposition}
          placeholder="이 강의에 대해 물어보세요" aria-label="강의 채팅 질문 입력" maxLength={chatQuestionLimit}/>
        <button className="chat-send" type="submit" aria-label="질문 보내기" disabled={!draft.trim()}><SendIcon/></button>
      </form>
      <button type="button" className="chat-resize" aria-label="강의 채팅 창 크기 조절" title="채팅 창 크기 조절"
        onPointerDown={(event) => {
          if (event.button !== 0 || moving) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          resize.current = { id: event.pointerId, x: event.screenX, y: event.screenY, width: view.panel.width, height: view.panel.height };
          void api.captureChatPointer(true);
        }} onPointerMove={(event) => {
          const drag = resize.current;
          if (drag?.id === event.pointerId) void api.resize(Math.round(drag.width + drag.x - event.screenX), Math.round(drag.height + drag.y - event.screenY));
        }} onLostPointerCapture={() => { resize.current = undefined; void api.captureChatPointer(false); }}
        onKeyDown={(event) => {
          const dx = event.key === "ArrowLeft" ? 24 : event.key === "ArrowRight" ? -24 : 0;
          const dy = event.key === "ArrowUp" ? 24 : event.key === "ArrowDown" ? -24 : 0;
          if (dx || dy) { event.preventDefault(); void api.resize(view.panel.width + dx, view.panel.height + dy); }
        }}><span aria-hidden="true"/></button>
    </section>
  </div>;
}
