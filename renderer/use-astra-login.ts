import { useCallback, useEffect, useRef, useState } from "react";
import type { AstraLoginStatus } from "../shared/lms.js";

const initial: AstraLoginStatus = { state: "idle", message: "" };

export function useAstraLogin() {
  const [status, setStatus] = useState<AstraLoginStatus>(initial);
  const pendingClick = useRef(false);
  const eventRevision = useRef(0);

  useEffect(() => {
    let active = true;
    const revision = eventRevision.current;
    const unsubscribe = window.ast.onAstraLoginStatus((next) => {
      eventRevision.current++;
      if (active) setStatus(next);
    });
    void window.ast.getAstraLoginStatus().then((next) => {
      if (active && revision === eventRevision.current) setStatus(next);
    }, () => {});
    return () => { active = false; unsubscribe(); };
  }, []);

  const start = useCallback(async () => {
    if (pendingClick.current) return;
    pendingClick.current = true;
    const revision = eventRevision.current;
    setStatus((current) => current.state === "waiting" ? current : { state: "opening", message: "" });
    try {
      const next = await window.ast.startAstraLogin();
      if (revision === eventRevision.current) setStatus(next);
    } catch {
      if (revision === eventRevision.current) setStatus({ state: "error", message: "로그인 상태를 확인하지 못했어요. 다시 시도해 주세요." });
    } finally {
      pendingClick.current = false;
    }
  }, []);

  return { status, start };
}
