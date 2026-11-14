import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type CSSProperties, type Ref } from "react";
import { CHAT_TRANSCRIPT_LIMIT, DEFAULT_CHAT_FONT_SIZE, type ChatConfig, type ChatEvent } from "../shared/chat.js";
import { ChatSettings } from "./chat-settings.js";
import { ChatTurn, type Turn } from "./chat-turn.js";
import { DarkMonoIcon } from "./dark-mono-icon.js";
import { LetHimCookIcon } from "./lethimcook-icon.js";
import { FocusModeIcon } from "./focus-mode-icon.js";
import "./chat-sidebar.css";
import "./lethimcook-chat.css";

const starters = ["이번 주 남은 과제 알려줘", "최근 장학 공지 찾아줘", "오늘 성림학사 식단은?"];

type ChatReference = { id: string; course_id: string; course_name: string; title: string };
export type ChatSidebarHandle = { ask: (question: string) => void };

function updateMessageEdges(viewport: HTMLDivElement) {
  const remaining = viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop;
  viewport.toggleAttribute("data-overflow-top", viewport.scrollTop > 1);
  viewport.toggleAttribute("data-overflow-bottom", remaining > 1);
}

export function ChatSidebar({ assignmentMode = false, darkMono = false, letHimCook = false, focusMode = false, references = [], ref, onOpenSettings, savedConfig, queuedQuestion, onQuestionReceived }: {
  assignmentMode?: boolean; darkMono?: boolean; letHimCook?: boolean; focusMode?: boolean; references?: ChatReference[];
  ref?: Ref<ChatSidebarHandle>;
  onOpenSettings?: () => void;
  savedConfig?: ChatConfig;
  queuedQuestion?: { text: string };
  onQuestionReceived?: (question: { text: string }) => void;
}) {
  const compact = darkMono || letHimCook;
  const Icon = focusMode ? FocusModeIcon : letHimCook ? LetHimCookIcon : DarkMonoIcon;
  const variant = letHimCook ? " chat-sidebar--let-him-cook" : darkMono ? " chat-sidebar--dark-mono" : "";
  const [loadedConfig, setConfig] = useState<ChatConfig | null>(null);
  const config = savedConfig ?? loadedConfig;
  const fontSize = config?.fontSize ?? DEFAULT_CHAT_FONT_SIZE;
  const [configError, setConfigError] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [newTurnId, setNewTurnId] = useState<string>();
  const [draft, setDraft] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [showReferences, setShowReferences] = useState(false);
  const [searchQuestion, setSearchQuestion] = useState("");
  const [clock, setClock] = useState(Date.now);
  const request = useRef<string | null>(null);
  const composing = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const messages = useRef<HTMLDivElement>(null);
  const messageContent = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);
  const scrollPosition = useRef<number | undefined>(undefined);
  const scrollFrame = useRef(0);
  const followBottom = useRef<(() => void) | undefined>(undefined);
  const flightOrigin = useRef<{ id: string; bounds: DOMRect } | undefined>(undefined);
  const flight = useRef<Animation | undefined>(undefined);
  const answerFrame = useRef(0);
  const pendingAnswer = useRef("");
  const receivedQuestion = useRef<typeof queuedQuestion>(undefined);

  async function loadConfig() {
    setConfigError(false);
    try {
      const [next, transcript] = await Promise.allSettled([window.ast.getChatConfig(), window.ast.getChatTranscript()]);
      if (next.status === "fulfilled") setConfig(next.value);
      if (transcript.status === "fulfilled") {
        setTurns((current) => [
          ...transcript.value.turns.filter((saved) => !current.some((turn) => turn.id === saved.id)),
          ...current,
        ].slice(-CHAT_TRANSCRIPT_LIMIT));
        setStorageError(transcript.value.storageError);
      }
      setConfigError(next.status === "rejected" || transcript.status === "rejected");
    }
    catch { setConfigError(true); }
  }

  useEffect(() => {
    void loadConfig();
    const unsubscribe = window.ast.onChatEvent((event: ChatEvent) => {
      if (event.requestId !== request.current) return;
      if (event.type === "answer") {
        pendingAnswer.current += event.text;
        if (!answerFrame.current) answerFrame.current = requestAnimationFrame(() => {
          answerFrame.current = 0;
          const text = pendingAnswer.current;
          pendingAnswer.current = "";
          setTurns((current) => current.map((turn) => turn.id === event.requestId ? { ...turn, answer: turn.answer + text } : turn));
        });
        return;
      }
      const state = event.type === "done" || event.type === "error" || event.type === "cancelled" ? event.type : undefined;
      if (event.type === "status" || state) clearPendingAnswer();
      setTurns((current) => current.map((turn) => {
        if (turn.id !== event.requestId) return turn;
        if (event.type === "read") return { ...turn, readAt: event.readAt };
        if (event.type === "status") return { ...turn, status: event.text, generating: false, answer: "" };
        if (event.type === "generating") return { ...turn, generating: true };
        if (event.type === "result") {
          return turn.results.includes(event.text) ? turn : { ...turn, results: [...turn.results, event.text] };
        }
        if (!state) return turn;
        return { ...turn, state, answer: event.text, sources: event.sources ?? [],
          cost: event.cost ?? turn.cost, readAt: event.readAt ?? turn.readAt, answeredAt: event.answeredAt };
      }));
      if (state) {
        if (event.storageError !== undefined) setStorageError(event.storageError);
        request.current = null;
        setActiveId(null);
      }
    });
    const updateClock = () => setClock(Date.now());
    const timer = window.setInterval(updateClock, 10_000);
    document.addEventListener("visibilitychange", updateClock);
    return () => {
      unsubscribe();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", updateClock);
      clearPendingAnswer();
      cancelAnimationFrame(scrollFrame.current);
    };
  }, []);

  useEffect(() => () => { void window.ast.setChatComposing?.(false).catch(() => {}); }, []);

  useLayoutEffect(() => {
    const target = messages.current;
    const content = messageContent.current;
    if (!target || !content) return;
    function follow(instant = false) {
      scrollFrame.current = 0;
      if (!target) return;
      if (autoScroll.current && !flight.current) {
        const bottom = target.scrollHeight - target.clientHeight;
        const remaining = bottom - target.scrollTop;
        const jump = instant || !newTurnId || matchMedia("(prefers-reduced-motion: reduce)").matches;
        target.scrollTop = jump || remaining < 2 ? bottom : target.scrollTop + Math.max(1, remaining * .3);
        scrollPosition.current = target.scrollTop;
        if (bottom - target.scrollTop >= 1) schedule();
      }
      updateMessageEdges(target);
    }
    function schedule() {
      if (!scrollFrame.current) scrollFrame.current = requestAnimationFrame(() => follow());
    }
    followBottom.current = schedule;
    follow(flightOrigin.current?.id === newTurnId);
    const observer = new ResizeObserver(schedule);
    observer.observe(content);
    observer.observe(target);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(scrollFrame.current);
      scrollFrame.current = 0;
      followBottom.current = undefined;
    };
  }, [newTurnId, showSettings]);

  useLayoutEffect(() => {
    const origin = flightOrigin.current;
    if (!origin || origin.id !== newTurnId) return;
    flightOrigin.current = undefined;
    const bubble = messages.current?.querySelector<HTMLElement>(".chat-turn:last-child .chat-user-message");
    const sidebar = bubble?.closest<HTMLElement>(".chat-sidebar");
    if (!bubble || !sidebar || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const destination = bubble.getBoundingClientRect();
    const container = sidebar.getBoundingClientRect();
    if (!destination.width || !origin.bounds.width) return;
    const copy = bubble.cloneNode(true) as HTMLElement;
    copy.classList.add("chat-message-flight");
    copy.setAttribute("aria-hidden", "true");
    Object.assign(copy.style, {
      left: `${destination.left - container.left - sidebar.clientLeft}px`,
      top: `${destination.top - container.top - sidebar.clientTop}px`,
      width: `${destination.width}px`,
      height: `${destination.height}px`,
    });
    sidebar.append(copy);
    bubble.dataset.flying = "true";
    const dx = origin.bounds.left + origin.bounds.width / 2 - destination.left - destination.width / 2;
    const dy = origin.bounds.top - destination.top;
    const animation = copy.animate([
      { opacity: .45, transform: `translate(${dx}px, ${dy}px) scale(.85)` },
      { opacity: 1, transform: `translate(${dx * .22}px, ${dy * .26}px) scale(.96)`, offset: .57 },
      { opacity: 1, transform: "translate(0, 0) scale(1)" },
    ], { duration: 440, easing: "cubic-bezier(.2,.72,.24,1)", fill: "both" });
    flight.current = animation;
    function cleanup() {
      copy.remove();
      if (bubble) delete bubble.dataset.flying;
      if (flight.current === animation) {
        flight.current = undefined;
        followBottom.current?.();
      }
    }
    void animation.finished.then(cleanup, cleanup);
    return () => { animation.cancel(); cleanup(); };
  }, [newTurnId]);

  useEffect(() => {
    if (!input.current) return;
    input.current.style.height = "auto";
    input.current.style.height = Math.min(input.current.scrollHeight, 150) + "px";
  }, [draft, fontSize]);

  function openSettings() {
    setShowReferences(false);
    setNewTurnId(undefined);
    if (onOpenSettings) onOpenSettings();
    else setShowSettings((value) => !value);
  }

  function fail(id: string, message: string) {
    if (request.current !== id) return;
    clearPendingAnswer();
    request.current = null;
    setActiveId(null);
    setTurns((current) => current.map((turn) => turn.id === id ? { ...turn, state: "error", answer: message } : turn));
  }

  function clearPendingAnswer() {
    cancelAnimationFrame(answerFrame.current);
    answerFrame.current = 0;
    pendingAnswer.current = "";
  }

  async function send(question = draft, preserveDraft = false) {
    const text = question.trim();
    if (!text || request.current || resetting) return;
    if (!config?.hasApiKey) { openSettings(); return; }
    setShowSettings(false);
    setShowReferences(false);
    const id = crypto.randomUUID();
    const origin = input.current?.getBoundingClientRect();
    if (origin) flightOrigin.current = { id, bounds: origin };
    request.current = id;
    setActiveId(id);
    setNewTurnId(id);
    autoScroll.current = true;
    const turn: Turn = { id, question: text, answer: "", sentAt: Date.now(), state: "working", status: "질문을 확인하고 있어요…", results: [], sources: [] };
    // A retry is a new billable attempt; keep the original answer and its cost.
    setTurns((current) => [...current, turn].slice(-CHAT_TRANSCRIPT_LIMIT));
    if (!preserveDraft) setDraft("");
    try {
      const result = await window.ast.sendChat(id, text);
      if (!result.ok) fail(id, result.message ?? "메시지를 보내지 못했어요. 다시 시도해 주세요.");
    } catch { fail(id, "비서와 연결하지 못했어요. 다시 시도해 주세요."); }
  }

  function ask(question: string) {
    input.current?.focus();
    if (request.current || resetting || !config?.hasApiKey) {
      setSearchQuestion(question);
      if (config && !config.hasApiKey) openSettings();
      return;
    }
    setSearchQuestion("");
    void send(question, true);
  }

  useImperativeHandle(ref, () => ({ ask }));

  useEffect(() => {
    if (!queuedQuestion || receivedQuestion.current === queuedQuestion || activeId || resetting || (!config && !configError)) return;
    receivedQuestion.current = queuedQuestion;
    onQuestionReceived?.(queuedQuestion);
    if (config?.hasApiKey) {
      void send(queuedQuestion.text, true);
    } else {
      setDraft((current) => current ? `${current}\n\n${queuedQuestion.text}` : queuedQuestion.text);
      if (config) openSettings();
    }
  }, [queuedQuestion, onQuestionReceived, config, configError, activeId, resetting]);

  async function cancel() {
    const id = request.current;
    if (!id) return;
    try {
      await window.ast.cancelChat(id);
      if (request.current === id) {
        clearPendingAnswer();
        request.current = null;
        setActiveId(null);
        setTurns((current) => current.map((turn) => turn.id === id ? { ...turn, state: "cancelled", answer: "답변 생성을 중지했어요." } : turn));
      }
    } catch { fail(id, "중지 상태를 확인하지 못했어요. 잠시 후 다시 시도해 주세요."); }
  }

  async function fresh() {
    if (request.current || resetting) return;
    setResetting(true);
    try {
      await window.ast.resetChat();
      setTurns([]);
      setNewTurnId(undefined);
      setStorageError(false);
      setDraft("");
      setSearchQuestion("");
      setSourceError(false);
      setShowSettings(false);
      setShowReferences(false);
      input.current?.focus();
    } catch { setSourceError(true); }
    finally { setResetting(false); }
  }

  async function openSource(url: string) {
    setSourceError(false);
    try { if (!await window.ast.openChatSource(url)) setSourceError(true); }
    catch { setSourceError(true); }
  }

  function chooseQuestion(question: string) {
    setDraft(question);
    input.current?.focus();
  }

  function chooseReference(item: ChatReference) {
    const reference = `‘${item.course_name}’의 ‘${item.title}’ 과제 자료를 참고해줘.`;
    setDraft((current) => current.trim() ? `${current.trimEnd()}\n${reference}` : reference);
    setShowReferences(false);
    input.current?.focus();
  }

  const newChat = <button type="button" className="chat-text-button chat-new" onClick={() => void fresh()} disabled={!!activeId || resetting || !config} title="새 대화">
    {compact && <Icon name="reset" />}<span className={compact ? "chat-sr-only" : undefined}>대화 지우기</span>
  </button>;
  const settings = <button type="button" className={`chat-text-button${compact ? " chat-scope" : ""}`} aria-expanded={onOpenSettings ? undefined : showSettings}
    onClick={openSettings} disabled={!!activeId || (!config && !onOpenSettings)}>
    {compact && <Icon name="scope" />}<span>{compact ? "대화 설정" : "설정"}</span>{compact && <Icon name="chevron" />}
  </button>;
  const sendControl = activeId
    ? <button className="chat-send" type="button" onClick={() => void cancel()} aria-label="답변 생성 중지">■</button>
    : <button className="chat-send" type="submit" disabled={!draft.trim() || !config?.hasApiKey || resetting} aria-label="메시지 보내기">
        {compact ? <Icon name="send" /> : "↑"}
      </button>;

  return (
    <aside className={`chat-sidebar${variant}`} style={{ "--chat-font-size": `${fontSize}px` } as CSSProperties} aria-labelledby="chat-title">
      {darkMono && !letHimCook && <div className="chat-glass-art" aria-hidden="true">
        <DarkMonoIcon name="leftReflection" className="chat-reflection-left" />
        <DarkMonoIcon name="bottomReflection" className="chat-reflection-bottom" />
      </div>}
      <header className="chat-header">
        <div className="chat-identity">
          {compact ? <div className="chat-identity-avatar"><Icon name="avatar" /></div> : <span className="chat-spark" aria-hidden="true">✦</span>}
          <div><h2 id="chat-title">{compact ? "AST" : <>AST 비서 <span>v0</span></>}</h2><p>{compact ? "학습 에이전트" : "학교생활을 함께 정리해요"}</p></div>
          {compact && newChat}
        </div>
        <div className="chat-header-actions">{!compact && newChat}{settings}</div>
      </header>
      {showSettings && config ? <ChatSettings config={config} onClose={() => setShowSettings(false)} onSaved={(next) => { setConfig(next); setShowSettings(false); input.current?.focus(); }} /> : (
        <div className="chat-messages" ref={messages} role="log" aria-label="비서와의 대화" aria-live="polite" onScroll={() => {
          const target = messages.current;
          if (!target) return;
          updateMessageEdges(target);
          if (target.scrollTop !== scrollPosition.current) {
            flight.current?.cancel();
            autoScroll.current = target.scrollHeight - target.scrollTop - target.clientHeight < 65;
          }
        }}>
          <div ref={messageContent}>
            {turns.length === 0 && !compact && <div className="chat-welcome">
              <span className="chat-welcome-spark" aria-hidden="true">✦</span>
              <h3>무엇을 확인해 볼까요?</h3>
              <p>{assignmentMode ? "과제 원문에 대해 물어보세요." : "과제, 공지, 시간표와 식단을 물어보세요."}</p>
              <div className="chat-starters">{(assignmentMode ? ["제출 조건을 정리해줘", "과제 첨부 PDF 읽어줘"] : starters).map((question) => <button type="button" key={question} onClick={() => chooseQuestion(question)}>{question}<span aria-hidden="true">↗</span></button>)}</div>
            </div>}
            {turns.map((turn) => (
              <ChatTurn
                key={turn.id}
                turn={turn}
                clock={clock}
                newTurn={turn.id === newTurnId}
                onOpenSource={(url) => void openSource(url)}
                onRetry={(question) => void send(question, true)}
                retryDisabled={!!activeId}
                darkMono={darkMono}
                letHimCook={letHimCook}
                focusMode={focusMode}
              />
            ))}
          </div>
        </div>
      )}
      <footer className="chat-footer">
        {configError && <p className="chat-error" role="alert">채팅을 불러오지 못했어요. <button className="chat-text-button" type="button" onClick={() => void loadConfig()}>다시 시도</button></p>}
        {storageError && <p className="chat-error" role="alert">채팅 기록을 읽거나 저장하지 못했어요.</p>}
        {sourceError && <p className="chat-error" role="alert">요청을 처리하지 못했어요. 다시 시도해 주세요.</p>}
        {searchQuestion && <button className="chat-setup" type="button" title={searchQuestion}
          disabled={!!activeId || resetting || !config?.hasApiKey} onClick={() => ask(searchQuestion)}>검색 질문 보내기 <span aria-hidden="true">↗</span></button>}
        {config && !config.hasApiKey && !showSettings && <button type="button" className="chat-setup" onClick={openSettings}>API 키 설정 안내 <span aria-hidden="true">↗</span></button>}
        {compact && !showSettings && <div className="chat-followups">
          <p>{turns.length ? "이어서 묻기" : "추천 질문"}</p>
          {starters.slice(0, 2).map((question) => <button key={question} type="button" onClick={() => chooseQuestion(question)}>{question}<Icon name="followup" /></button>)}
        </div>}
        {compact && showReferences && <div className="chat-reference-picker" aria-label="참고할 과제 자료" onKeyDown={(event) => {
          if (event.key === "Escape") { setShowReferences(false); input.current?.focus(); }
        }}>
          <p>참고할 과제 자료</p>
          {references.length ? [...new Map(references.map((item) => [`${item.course_id}:${item.id}`, item])).values()].map((item) =>
            <button type="button" key={`${item.course_id}:${item.id}`} onClick={() => chooseReference(item)}>{item.title}<small>{item.course_name}</small></button>)
            : <p>e-Class에 연결하면 조회한 과제 자료를 선택할 수 있어요.</p>}
        </div>}
        <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void send(); }}>
          <textarea ref={input} aria-label="비서에게 질문" placeholder="학교생활을 물어보세요" value={draft} rows={compact ? 1 : 2} maxLength={8000}
            onFocus={() => void window.ast.setChatComposing?.(true).catch(() => {})}
            onBlur={() => void window.ast.setChatComposing?.(false).catch(() => {})}
            onChange={(event) => setDraft(event.target.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); void send(); }
          }} />
          {compact ? <>
            <button type="button" className="chat-attach" aria-label="과제 자료 참조 추가" aria-expanded={showReferences} disabled={!!activeId}
              onClick={() => setShowReferences(!showReferences)}><Icon name="attach" /></button>
            {sendControl}
          </> : <div className="chat-composer-actions"><span>Enter 전송 · Shift+Enter 줄바꿈</span>{sendControl}</div>}
        </form>
        {!compact && <p className="chat-footer-note">중요한 일정은 원문도 확인해 주세요.</p>}
      </footer>
    </aside>
  );
}
