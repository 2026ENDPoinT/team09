import { useEffect, useRef, useState, type CSSProperties } from "react";

const stackedAt = 760;
const minMain = 380;
const minSidebar = 120;
const minChat = 240;
const maxSidebar = 360;
const maxChat = 640;

type Pane = "sidebar" | "chat";

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(min, max), Math.max(min, value));
}

export function useWorkspaceWidths(collapsed: boolean) {
  const [windowWidth, setWindowWidth] = useState(() => window.innerWidth);
  const [preferred, setPreferred] = useState<Partial<Record<Pane, number>>>({});

  useEffect(() => {
    const resize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  const stacked = windowWidth <= stackedAt;
  const available = windowWidth - minMain;
  const sidebar = collapsed ? 0 : clamp(preferred.sidebar ?? clamp(windowWidth * .11, 154, 192),
    minSidebar, Math.min(maxSidebar, available - (stacked ? 0 : minChat)));
  const chatLimit = Math.min(maxChat, available - sidebar);
  const chat = stacked ? 0 : clamp(preferred.chat ?? clamp(windowWidth * .2, 288, 360), minChat, chatLimit);
  const sidebarLimit = Math.min(maxSidebar, available - chat);
  const style = { "--ast-sidebar-width": `${sidebar}px`, "--ast-chat-width": `${chat}px` } as CSSProperties;

  function change(pane: Pane, width: number) {
    const next = pane === "sidebar" ? clamp(width, minSidebar, sidebarLimit) : clamp(width, minChat, chatLimit);
    setPreferred((current) => current[pane] === next ? current : { ...current, [pane]: next });
  }

  return {
    style,
    sidebar: { width: sidebar, min: minSidebar, max: Math.max(minSidebar, sidebarLimit) },
    chat: { width: chat, min: minChat, max: Math.max(minChat, chatLimit) },
    change,
  };
}

export function WorkspaceSplitter({ pane, width, min, max, onResize }: {
  pane: Pane;
  width: number;
  min: number;
  max: number;
  onResize: (width: number) => void;
}) {
  const sidebar = pane === "sidebar";
  return <PaneSplitter className={`ast-pane-divider ast-pane-divider--${pane}`}
    label={sidebar ? "사이드바 너비" : "채팅 바 너비"} controls={sidebar ? "ast-sidebar" : "ast-chat-pane"}
    direction={sidebar ? 1 : -1} width={width} min={min} max={max} onResize={onResize} />;
}

export function PaneSplitter({ className, label, controls, width, min, max, onResize, direction = 1 }: {
  className: string;
  label: string;
  controls: string;
  width: number;
  min: number;
  max: number;
  onResize: (width: number) => void;
  direction?: 1 | -1;
}) {
  const drag = useRef<{ pointerId: number; x: number; width: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  return <div className={className} role="separator" aria-label={label} aria-orientation="vertical"
    aria-controls={controls} aria-valuenow={Math.round(width)}
    aria-valuemin={min} aria-valuemax={Math.round(max)} tabIndex={0} data-dragging={dragging || undefined}
    onPointerDown={(event) => {
      if (event.button !== 0 || drag.current) return;
      event.preventDefault();
      event.currentTarget.focus({ preventScroll: true });
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { pointerId: event.pointerId, x: event.clientX, width };
      setDragging(true);
    }}
    onPointerMove={(event) => {
      const start = drag.current;
      if (!start || start.pointerId !== event.pointerId) return;
      onResize(start.width + direction * (event.clientX - start.x));
    }}
    onLostPointerCapture={(event) => {
      if (drag.current?.pointerId !== event.pointerId) return;
      drag.current = null;
      setDragging(false);
    }}
    onKeyDown={(event) => {
      const key = event.key;
      if (key !== "ArrowLeft" && key !== "ArrowRight" && key !== "Home" && key !== "End") return;
      event.preventDefault();
      const step = event.shiftKey ? 40 : 10;
      onResize(key === "Home" ? min : key === "End" ? max : width + direction * (key === "ArrowLeft" ? -step : step));
    }} />;
}
