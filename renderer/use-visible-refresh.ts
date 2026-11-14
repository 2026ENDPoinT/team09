import { useEffect, useEffectEvent, useRef } from "react";
import { SCREEN_FRESHNESS_MS } from "../shared/screen-freshness.js";

export function useVisibleRefresh(visible: boolean, refresh: () => void, loadedAt = 0, key = "") {
  const lastAttempt = useRef({ key, time: Date.now() });
  const refreshCurrent = useEffectEvent(refresh);

  useEffect(() => {
    if (!visible) return;
    if (lastAttempt.current.key !== key) lastAttempt.current = { key, time: loadedAt || Date.now() };
    let timer: number;
    function schedule() {
      window.clearTimeout(timer);
      if (document.hidden) return;
      const due = Math.max(loadedAt, lastAttempt.current.time) + SCREEN_FRESHNESS_MS;
      timer = window.setTimeout(() => {
        lastAttempt.current.time = Date.now();
        refreshCurrent();
        schedule();
      }, Math.max(0, due - Date.now()));
    }
    schedule();
    document.addEventListener("visibilitychange", schedule);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", schedule);
    };
  }, [visible, loadedAt, key]);
}
