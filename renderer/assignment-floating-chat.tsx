import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type PointerEvent } from "react";
import { ChatSidebar } from "./chat-sidebar.js";
import { LetHimCookIcon } from "./lethimcook-icon.js";
import "./assignment-floating-chat.css";

type Point = { x: number; y: number };
type Drag = { id: number; start: Point; origin: Point; panel?: PanelBounds };
type PanelBounds = { left: number; top: number; width: number; height: number };
type PanelSize = Pick<PanelBounds, "width" | "height">;
type ResizeCorner = "top-left" | "bottom-right";
type PanelResize = { id: number; start: Point; bounds: PanelBounds };
type ChatMotion = {
  spotlight: Animation;
  panel: Animation;
  towardOpen: boolean;
  revision: number;
};
const edge = 10;
const orbSize = 50;
const orbRight = 12;
const orbBottom = 17;
const panelEdge = 14;
const defaultPanelSize = { width: 390, height: 620 };
const minPanelSize = { width: 280, height: 340 };
const resizeHandles = [
  ["top-left", "채팅 창 왼쪽 위 크기 조절"],
  ["bottom-right", "채팅 창 오른쪽 아래 크기 조절"],
] as const;
const spotlightDuration = 270;
const panelDelay = 150;
const panelDuration = 340;
const motionDuration = panelDelay + panelDuration;

export function AssignmentFloatingChat() {
  const [open, setOpen] = useState(false);
  const [moving, setMoving] = useState(false);
  const [started, setStarted] = useState(false);
  const [draft, setDraft] = useState("");
  const [questions, setQuestions] = useState<{ text: string }[]>([]);
  const [position, setPosition] = useState<Point>();
  const [areaSize, setAreaSize] = useState({ width: 0, height: 0 });
  const [customPanel, setCustomPanel] = useState<PanelBounds>();
  const [resizing, setResizing] = useState(false);
  const [draggingOrb, setDraggingOrb] = useState(false);
  const layer = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const orb = useRef<HTMLButtonElement>(null);
  const spotlight = useRef<HTMLFormElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const returnFocus = useRef<"orb" | "spotlight" | undefined>(undefined);
  const drag = useRef<Drag | undefined>(undefined);
  const dragged = useRef(false);
  const panelResize = useRef<PanelResize | undefined>(undefined);
  const motion = useRef<ChatMotion | undefined>(undefined);
  const acknowledge = useCallback((question: { text: string }) => {
    setQuestions((current) => current.filter((item) => item !== question));
  }, []);

  useEffect(() => {
    if (open) panel.current?.querySelector("textarea")?.focus({ preventScroll: true });
  }, [open]);

  useEffect(() => {
    if (open || moving || !returnFocus.current) return;
    if (returnFocus.current === "spotlight" && document.activeElement === orb.current) {
      input.current?.focus({ preventScroll: true });
    }
    returnFocus.current = undefined;
  }, [open, moving]);

  useLayoutEffect(() => {
    const area = layer.current;
    if (!area) return;
    function measure() {
      if (!area) return;
      const { clientWidth: width, clientHeight: height } = area;
      if (!width || !height) return;
      setAreaSize((current) => current.width === width && current.height === height ? current : { width, height });
      setPosition((point) => point && clampPosition(point, area));
    }
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    return () => observer.disconnect();
  }, []);

  useEffect(() => () => cancelMotion(motion.current), []);

  useEffect(() => {
    if (open || moving) return;
    const form = spotlight.current;
    if (!form) return;
    const clear = () => form.removeAttribute("data-near");
    function check(event: globalThis.PointerEvent) {
      if (!form) return;
      const { left, right, top, bottom } = form.getBoundingClientRect();
      const near = 24;
      form.toggleAttribute("data-near", event.clientX >= left - near && event.clientX <= right + near &&
        event.clientY >= top - near && event.clientY <= bottom + near);
    }
    document.addEventListener("pointermove", check);
    document.documentElement.addEventListener("pointerleave", clear);
    window.addEventListener("blur", clear);
    return () => {
      document.removeEventListener("pointermove", check);
      document.documentElement.removeEventListener("pointerleave", clear);
      window.removeEventListener("blur", clear);
    };
  }, [open, moving]);

  function animateChat(towardOpen: boolean) {
    const active = motion.current;
    if (active?.towardOpen === towardOpen) return;
    const form = spotlight.current;
    const button = orb.current;
    const dialog = panel.current;
    if (!form || !button || !dialog) return;
    const current = active ?? {
      spotlight: form.animate(spotlightKeyframes(form, button), {
        duration: spotlightDuration, endDelay: motionDuration - spotlightDuration,
        easing: "cubic-bezier(.5, .08, .36, 1)", fill: "both",
      }),
      panel: dialog.animate(panelKeyframes(openBelow), {
        duration: panelDuration, delay: panelDelay, easing: "cubic-bezier(.2, .82, .24, 1)", fill: "both",
      }),
      towardOpen,
      revision: 0,
    };
    motion.current = current;

    for (const animation of [current.spotlight, current.panel]) {
      if (!active && !towardOpen) animation.currentTime = motionDuration;
      if (active || !towardOpen) animation.reverse();
    }
    current.towardOpen = towardOpen;
    const revision = ++current.revision;
    void Promise.all([current.spotlight.finished, current.panel.finished]).then(() => {
      if (motion.current === current && current.revision === revision) setMoving(false);
    }, () => {});
  }

  function setChatOpen(nextOpen: boolean) {
    const animate = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (animate) animateChat(nextOpen);
    setMoving(animate);
    setOpen(nextOpen);
  }

  function openChat(origin: "orb" | "spotlight") {
    returnFocus.current = origin;
    setStarted(true);
    setChatOpen(true);
  }

  function closeChat(origin?: "orb") {
    if (origin) returnFocus.current = origin;
    orb.current?.focus({ preventScroll: true });
    setChatOpen(false);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || moving) return;
    setQuestions((current) => [...current, { text: question }]);
    setDraft("");
    openChat("spotlight");
  }

  function startDrag(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || !layer.current) return;
    const area = layer.current.getBoundingClientRect();
    const button = event.currentTarget.getBoundingClientRect();
    drag.current = {
      id: event.pointerId,
      start: { x: event.clientX, y: event.clientY },
      origin: { x: button.left - area.left, y: button.top - area.top },
      panel: customPanel ? bounds : undefined,
    };
    dragged.current = false;
    setDraggingOrb(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveDrag(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current;
    const area = layer.current;
    if (!current || current.id !== event.pointerId || !area) return;
    const x = event.clientX - current.start.x;
    const y = event.clientY - current.start.y;
    if (!dragged.current && Math.hypot(x, y) < 5) return;
    dragged.current = true;
    const next = clampPosition({ x: current.origin.x + x, y: current.origin.y + y }, area);
    if (current.panel) setCustomPanel({ ...current.panel,
      left: current.panel.left + next.x - current.origin.x, top: current.panel.top + next.y - current.origin.y });
    setPosition(next);
  }

  function endDrag(event: PointerEvent<HTMLButtonElement>) {
    if (drag.current?.id !== event.pointerId) return;
    drag.current = undefined;
    setDraggingOrb(false);
  }

  const anchor = position ?? { x: areaSize.width - orbSize - orbRight, y: areaSize.height - orbSize - orbBottom };
  const above = anchor.y - edge - panelEdge;
  const below = areaSize.height - anchor.y - orbSize - edge - panelEdge;
  const openBelow = above < 320 && below > above;
  const area = {
    width: Math.max(0, areaSize.width - (position ? 0 : orbRight - edge)),
    height: position ? areaSize.height : Math.max(0, areaSize.height - orbSize - orbBottom + panelEdge),
  };
  const width = Math.max(0, Math.min(defaultPanelSize.width, area.width - panelEdge * 2 - edge));
  const height = Math.max(0, Math.min(defaultPanelSize.height, (openBelow ? below : above) - edge));
  const bounds = customPanel ? fitPanel(customPanel, area) : {
    left: clamp(anchor.x + orbSize - width, panelEdge, area.width - width - panelEdge - edge),
    top: openBelow ? anchor.y + orbSize + edge : anchor.y - edge - height,
    width, height,
  };
  const panelLayout = {
    ...bounds,
    transformOrigin: `${anchor.x + orbSize / 2 - bounds.left}px ${openBelow ? "top" : "bottom"}`,
  } satisfies CSSProperties;

  function startResize(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || moving || panelResize.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    panelResize.current = { id: event.pointerId, start: { x: event.clientX, y: event.clientY }, bounds };
    setResizing(true);
  }

  function moveResize(event: PointerEvent<HTMLButtonElement>, corner: ResizeCorner) {
    const resize = panelResize.current;
    if (!resize || resize.id !== event.pointerId) return;
    setCustomPanel(resizePanel(resize.bounds, corner, {
      x: event.clientX - resize.start.x, y: event.clientY - resize.start.y,
    }, area));
  }

  function endResize(event: PointerEvent<HTMLButtonElement>) {
    if (panelResize.current?.id !== event.pointerId) return;
    panelResize.current = undefined;
    setResizing(false);
  }

  function resizeWithKeyboard(event: KeyboardEvent<HTMLButtonElement>, corner: ResizeCorner) {
    const step = event.shiftKey ? 32 : 8;
    const x = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
    const y = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
    if (!x && !y) return;
    event.preventDefault();
    setCustomPanel(resizePanel(bounds, corner, { x, y }, area));
  }

  useLayoutEffect(() => {
    if (!moving) {
      cancelMotion(motion.current);
      motion.current = undefined;
      return;
    }

    // Closing from an open chat needs the re-mounted Spotlight before measuring the path.
    animateChat(open);
    const current = motion.current;
    const form = spotlight.current;
    const button = orb.current;
    if (!current || !form || !button) return;
    (current.spotlight.effect as KeyframeEffect).setKeyframes(spotlightKeyframes(form, button));
    (current.panel.effect as KeyframeEffect).setKeyframes(panelKeyframes(openBelow));
  });

  return <div className="assignment-floating-chat" ref={layer} data-resizing={resizing || undefined} data-dragging-orb={draggingOrb || undefined} onKeyDown={(event) => {
    if (!open || event.key !== "Escape" || event.nativeEvent.isComposing) return;
    event.stopPropagation();
    closeChat();
  }}>
    {(!open || moving) && <form className="assignment-chat-spotlight" ref={spotlight} onSubmit={submit}
      aria-label="과제 비서에게 질문" inert={moving}>
      <LetHimCookIcon name="search" />
      <input ref={input} value={draft} maxLength={8000} placeholder="이 과제에 대해 물어보세요" aria-label="과제 비서에게 질문"
        onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
          if (event.key === "Enter" && (event.nativeEvent.isComposing || event.keyCode === 229)) event.preventDefault();
        }} />
      <button type="submit" disabled={!draft.trim()} aria-label="질문 보내기"><LetHimCookIcon name="send" /></button>
    </form>}
    <button type="button" className="assignment-chat-orb" ref={orb}
      style={position && { left: position.x, top: position.y, right: "auto", bottom: "auto" }}
      aria-label={open ? "과제 비서 닫기" : "과제 비서 열기"} aria-expanded={open} aria-controls="assignment-chat-panel" title="과제 비서 · 드래그해서 이동"
      onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={endDrag}
      onClick={(event) => {
        if (event.detail && dragged.current) return;
        if (open) closeChat("orb");
        else openChat("orb");
      }}>
      <LetHimCookIcon name="avatar" />
    </button>
    <div className="assignment-chat-panel" id="assignment-chat-panel" ref={panel} hidden={!open && !moving} inert={!open}
      role="dialog" aria-label="과제 비서" style={panelLayout} data-open-below={openBelow || undefined}>
      <button type="button" className="assignment-chat-close" onClick={() => closeChat()} aria-label="과제 비서 닫기">×</button>
      {started && <ChatSidebar assignmentMode queuedQuestion={questions[0]} onQuestionReceived={acknowledge} />}
      {resizeHandles.map(([corner, label]) => <button key={corner} type="button" className="assignment-chat-resize" data-corner={corner}
        aria-label={label} title={label} disabled={!open || moving}
        onPointerDown={startResize} onPointerMove={(event) => moveResize(event, corner)}
        onPointerUp={endResize} onPointerCancel={endResize} onLostPointerCapture={endResize}
        onKeyDown={(event) => resizeWithKeyboard(event, corner)} />)}
    </div>
  </div>;
}

function spotlightKeyframes(form: HTMLElement, orb: HTMLElement): Keyframe[] {
  const from = form.getBoundingClientRect();
  const to = orb.getBoundingClientRect();
  const transform = new DOMMatrixReadOnly(getComputedStyle(form).transform);
  const dx = to.left + (to.width - from.width) / 2 - from.left + transform.m41;
  const dy = to.top + (to.height - from.height) / 2 - from.top + transform.m42;
  return [
    { transform: "translate3d(0, 0, 0) scale(1)", opacity: 1 },
    { transform: `translate3d(${dx * .55}px, ${dy * .55}px, 0) scale(.58, .85)`, opacity: .95, offset: .48 },
    { transform: `translate3d(${dx}px, ${dy}px, 0) scale(.06, .12)`, opacity: 0 },
  ];
}

function panelKeyframes(openBelow: boolean): Keyframe[] {
  return [
    {
      clipPath: openBelow ? "inset(0 0 100% round 18px)" : "inset(100% 0 0 round 18px)",
      transform: `translateY(${openBelow ? -7 : 7}px) scale(.86, .94)`,
      opacity: 0,
    },
    { clipPath: "inset(0 round 18px)", transform: "none", opacity: 1 },
  ];
}

function cancelMotion(motion: ChatMotion | undefined) {
  motion?.spotlight.cancel();
  motion?.panel.cancel();
}

function clampPosition(point: Point, area: HTMLElement): Point {
  return {
    x: Math.max(edge, Math.min(point.x, area.clientWidth - orbSize - edge)),
    y: Math.max(edge, Math.min(point.y, area.clientHeight - orbSize - edge)),
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(value, max));
}

function fitPanel(bounds: PanelBounds, area: PanelSize): PanelBounds {
  const width = clamp(bounds.width, 0, area.width - 2 * panelEdge);
  const height = clamp(bounds.height, 0, area.height - 2 * panelEdge);
  return {
    width, height,
    left: clamp(bounds.left, panelEdge, area.width - panelEdge - width),
    top: clamp(bounds.top, panelEdge, area.height - panelEdge - height),
  };
}

function resizePanel(bounds: PanelBounds, corner: ResizeCorner, delta: Point, area: PanelSize): PanelBounds {
  const right = bounds.left + bounds.width;
  const bottom = bounds.top + bounds.height;
  if (corner === "top-left") {
    const left = clamp(bounds.left + delta.x, panelEdge, right - Math.min(bounds.width, minPanelSize.width));
    const top = clamp(bounds.top + delta.y, panelEdge, bottom - Math.min(bounds.height, minPanelSize.height));
    return fitPanel({ left, top, width: right - left, height: bottom - top }, area);
  }
  const maxWidth = area.width - panelEdge - bounds.left;
  const maxHeight = area.height - panelEdge - bounds.top;
  const width = clamp(bounds.width + delta.x, Math.min(bounds.width, minPanelSize.width), maxWidth);
  const height = clamp(bounds.height + delta.y, Math.min(bounds.height, minPanelSize.height), maxHeight);
  return fitPanel({ ...bounds, width, height }, area);
}
