import { useLayoutEffect, useRef, type RefObject } from "react";
import type { StudentPreferences } from "../shared/student-preferences.js";
import type { StudentProfile } from "../shared/lms.js";
import { StudentSetup } from "./student-setup.js";
import astraMark from "./assets/login/astra-mark.png";
import "./astra-welcome.css";

type Props = {
  stage: "welcome" | "entering";
  state: "idle" | "opening" | "waiting" | "verifying" | "authenticated" | "error";
  message: string;
  titlebar: boolean;
  destination: RefObject<HTMLSpanElement | null>;
  setup: boolean;
  setupCompleted: boolean;
  sessionRevision: number;
  displayName?: string;
  studentProfile?: StudentProfile;
  retryPreferences: boolean;
  onSetupComplete: (preferences: StudentPreferences) => void;
  onLogin: () => void;
  onEntered: () => void;
};

export function AstraWelcome({
  stage, state, message, titlebar, destination, setup, setupCompleted, sessionRevision, displayName, studentProfile, retryPreferences, onSetupComplete, onLogin, onEntered,
}: Props) {
  const mark = useRef<HTMLSpanElement>(null);
  const entering = stage === "entering";
  const busy = state === "verifying" || state === "authenticated";
  const blocked = state === "opening" || busy || entering;

  useLayoutEffect(() => {
    if (!entering) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = mark.current?.getBoundingClientRect();
    const to = destination.current?.getBoundingClientRect();
    if (reduceMotion || !from?.width || !to?.width || !mark.current) {
      onEntered();
      return;
    }
    const move = mark.current.animate([
      { transform: "translate(0, 0) scale(1)" },
      { transform: `translate(${to.left - from.left}px, ${to.top - from.top}px) scale(${to.width / from.width})` },
    ], { duration: 1020, easing: "cubic-bezier(.65, .04, .18, 1)", fill: "forwards" });
    let active = true;
    void move.finished.then(() => { if (active) onEntered(); }, () => {});
    return () => { active = false; move.cancel(); };
  }, [entering, destination, onEntered]);

  const label = retryPreferences ? "설정 다시 불러오기" : busy ? state === "verifying" ? "로그인 중…" : "홈 준비 중…" : state === "opening" ? "로그인 창 여는 중…"
    : state === "waiting" ? "로그인 다시 확인" : state === "error" ? "ASTRA 로그인 다시 시도" : "ASTRA로 로그인";

  return (
    <section className={`astra-welcome${titlebar ? " astra-welcome--titlebar" : ""}${entering ? " astra-welcome--entering" : ""}${state === "verifying" ? " astra-welcome--busy" : ""}${setup ? " astra-welcome--setup" : ""}`}
      aria-label={setup ? "AST 첫 로그인 설정" : "AST 시작 화면"} aria-hidden={entering} inert={entering}>
      <div className="astra-welcome-landscape" aria-hidden="true" />
      <div className="astra-welcome-center">
        <span className="astra-welcome-mark" ref={mark} role="img" aria-label="AST">
          <span className="ast-wordmark-art" aria-hidden="true" />
        </span>
        <div className="astra-welcome-action">
          {setup ? <div className="astra-setup-surface">
            <div className="astra-setup-button-echo" aria-hidden="true"><img src={astraMark} alt="" width="23" height="23" />로그인 중…</div>
            <StudentSetup key={sessionRevision} displayName={displayName} profile={studentProfile} completed={setupCompleted}
              sessionRevision={sessionRevision} onComplete={onSetupComplete} />
          </div> : <>
            <button className="astra-login-button" type="button" onClick={onLogin} disabled={blocked} aria-busy={state === "opening" || busy}>
              <img src={astraMark} alt="" width="23" height="23" />
              <span>{label}</span>
            </button>
            <p className="astra-welcome-status" data-error={state === "error"} role="status">{state === "idle" ? "" : message}</p>
          </>}
        </div>
      </div>
    </section>
  );
}
