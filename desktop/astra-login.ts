import type { AstraLoginStatus, LoginResult, LoginSettings, LoginWindowResult } from "../shared/lms.js";
import type { ScreenData, ScreenRequest } from "./screen-data.js";
import { verifiedAccount } from "./account-data.js";

type CaptureStatus = { status: "idle" | "pending" | "captured" | "closed"; message: string };
const probeInterval = 800;
const authenticatedMessage = "ASTRA 로그인을 확인했어요.";

/** Coordinates the login browser and the main window's verified LMS session. */
export function createAstraLogin(screenData: ScreenData, request: ScreenRequest, notify: (status: AstraLoginStatus) => void, requireAccount = false) {
  let status: AstraLoginStatus = { state: "idle", message: "ASTRA로 로그인해 주세요." };
  let revision = screenData.status.sessionRevision;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let operation: Promise<unknown> | undefined;
  let retryConfirmation = false;
  let startupSettings: (() => Promise<LoginSettings>) | undefined;
  let stopped = false;
  let displayName: string | undefined;

  function publish(state: AstraLoginStatus["state"], message: string, displayName?: string) {
    const courseRoster = state === "authenticated" ? screenData.roster : undefined;
    const studentProfile = state === "authenticated" ? screenData.studentProfile : undefined;
    if (stopped || (status.state === state && status.message === message && status.displayName === displayName &&
        status.courseRoster === courseRoster && status.studentProfile === studentProfile)) return;
    status = {
      state, message, ...(displayName ? { displayName } : {}), ...(courseRoster ? { courseRoster } : {}),
      ...(studentProfile ? { studentProfile } : {}),
    };
    notify(status);
  }

  function clearTimer() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  }

  function current(expected: number) {
    return !stopped && expected === screenData.status.sessionRevision;
  }

  function snapshot(): AstraLoginStatus {
    if (stopped) return status;
    if (screenData.confirmedSessionRevision !== undefined) {
      const name = requireAccount ? screenData.account?.displayName : displayName;
      const courseRoster = screenData.roster;
      const studentProfile = screenData.studentProfile;
      return {
        state: "authenticated", message: authenticatedMessage, ...(name ? { displayName: name } : {}),
        ...(courseRoster ? { courseRoster } : {}), ...(studentProfile ? { studentProfile } : {}),
      };
    }
    if (revision !== screenData.status.sessionRevision) {
      return { state: "idle", message: "ASTRA로 로그인해 주세요." };
    }
    return status;
  }

  function sessionChanged() {
    const nextRevision = screenData.status.sessionRevision;
    if (revision === nextRevision) return;
    revision = nextRevision;
    retryConfirmation = false;
    clearTimer();
    const next = snapshot();
    if (next.state === "authenticated") publish(next.state, next.message, next.displayName);
    else {
      displayName = undefined;
      publish("idle", "ASTRA로 로그인해 주세요.");
    }
  }

  function serialize<T>(work: () => Promise<T>): Promise<T> {
    const promise = work().finally(() => { if (operation === promise) operation = undefined; });
    operation = promise;
    return promise;
  }

  function scheduleProbe() {
    clearTimer();
    if (stopped || status.state !== "waiting") return;
    timer = setTimeout(() => {
      timer = undefined;
      if (operation) { scheduleProbe(); return; }
      void serialize(() => probe(false));
    }, probeInterval);
    timer.unref();
  }

  async function open(): Promise<LoginWindowResult> {
    clearTimer();
    retryConfirmation = false;
    screenData.invalidateSession();
    revision = screenData.status.sessionRevision;
    const expected = revision;
    publish("opening", "ASTRA 로그인 창을 열고 있어요.");
    let result: LoginWindowResult;
    try {
      result = await screenData.authenticate(() => request<LoginWindowResult>(
        "start_desktop_login", {}, 45_000, "로그인 창을 열지 못했어요. 다시 시도해 주세요.",
      ));
    } catch {
      result = { status: "error", message: "로그인 창을 열지 못했어요. 다시 시도해 주세요." };
    }
    if (current(expected)) {
      if (result.status === "error") publish("error", result.message);
      else {
        publish("waiting", "열린 창에서 ASTRA 로그인을 완료해 주세요.");
        scheduleProbe();
      }
    }
    return result;
  }

  async function confirm(useSaved: boolean, atStartup = false): Promise<LoginResult> {
    clearTimer();
    const expected = screenData.status.sessionRevision;
    revision = expected;
    publish("verifying", atStartup ? "저장된 ASTRA 로그인을 확인하고 있어요." : "ASTRA 로그인을 확인하고 있어요.");
    let result: LoginResult;
    try {
      result = await screenData.authenticate(() => request<LoginResult>(
        "confirm_desktop_login", useSaved ? {} : { use_saved: false }, 45_000,
        "로그인 상태를 확인하지 못했어요. 다시 시도해 주세요.",
      ));
    } catch {
      result = { status: "error", message: "로그인 상태를 확인하지 못했어요. 다시 시도해 주세요." };
    }
    if (!current(expected)) return { status: "login_required", message: "로그인 상태가 바뀌었어요. 다시 확인해 주세요." };
    const account = verifiedAccount(result);
    if (result.status === "authenticated" && requireAccount && !account) {
      result = { status: "login_required", message: "계정을 확인하지 못했어요. ASTRA에서 다시 로그인해 주세요." };
    }
    retryConfirmation = !useSaved && result.status === "error";
    if (result.status === "authenticated") {
      displayName = result.display_name;
      screenData.warm(account, result.course_roster, result.student_profile);
      revision = screenData.status.sessionRevision;
      publish("authenticated", authenticatedMessage, displayName);
    } else if (atStartup && result.status === "login_required") {
      publish("idle", "ASTRA로 로그인해 주세요.");
    } else {
      publish("error", result.message);
    }
    return result;
  }

  async function prepareStartup(): Promise<boolean> {
    if (!startupSettings) return true;
    publish("verifying", "로그인 유지 설정을 확인하고 있어요.");
    let settings: LoginSettings;
    try {
      settings = await startupSettings();
    } catch {
      startupSettings = undefined;
      publish("error", "로그인 유지 설정을 불러오지 못했어요. ASTRA로 로그인해 주세요.");
      return false;
    }
    if (stopped) return false;
    if (settings.keepLogin) {
      startupSettings = undefined;
      await confirm(true, true);
      return true;
    }
    const errorMessage = "저장된 로그인 세션을 지우지 못했어요. 다시 시도해 주세요.";
    try {
      const result = await screenData.authenticate(() => request<{ status: "cleared" }>(
        "clear_desktop_login", {}, 15_000, errorMessage,
      ));
      if (result.status === "cleared") {
        startupSettings = undefined;
        publish("idle", "ASTRA로 로그인해 주세요.");
        return true;
      }
    } catch {
      // The next login attempt retries cleanup before opening a browser.
    }
    publish("error", errorMessage);
    return false;
  }

  async function probe(manual: boolean): Promise<AstraLoginStatus> {
    clearTimer();
    const expected = revision;
    let result: CaptureStatus | { status: "error"; message: string };
    try {
      result = await request<CaptureStatus>(
        "get_desktop_login_status", manual ? { recheck: true } : {}, 8_000,
        "로그인 감지를 확인하지 못했어요. 다시 눌러 주세요.",
      );
    } catch {
      result = { status: "error", message: "로그인 감지를 확인하지 못했어요. 다시 눌러 주세요." };
    }
    if (!current(expected)) return snapshot();
    if (result.status === "captured") {
      await confirm(false);
    } else if (result.status === "closed" || result.status === "idle") {
      if (manual) await open();
      else publish("error", result.message);
    } else {
      // Even after a transient probe error, the browser attempt can be checked again.
      publish("waiting", result.message);
      scheduleProbe();
    }
    return snapshot();
  }

  return {
    snapshot, sessionChanged,
    initialize(loadSettings: () => Promise<LoginSettings>) {
      startupSettings = loadSettings;
      return serialize(prepareStartup);
    },
    async start(): Promise<AstraLoginStatus> {
      if (stopped) return snapshot();
      if (operation) {
        await operation;
        // A click that arrived during an automatic probe still gets one manual recheck.
        if (status.state === "waiting" && !operation) return serialize(() => probe(true));
        return snapshot();
      }
      if (status.state === "waiting") return serialize(() => probe(true));
      if (retryConfirmation) return serialize(async () => { await confirm(false); return snapshot(); });
      return serialize(async () => {
        if (startupSettings && (!await prepareStartup() || snapshot().state === "authenticated")) return snapshot();
        if (!stopped) await open();
        return snapshot();
      });
    },
    async openLegacy(): Promise<LoginWindowResult> {
      if (operation) await operation;
      if (stopped) return { status: "error", message: "앱을 종료하고 있어요." };
      if (status.state === "waiting") return { status: "already_open", message: status.message };
      return serialize(async () => {
        if (!await prepareStartup() || stopped) return { status: "error", message: status.message };
        return open();
      });
    },
    async confirmLegacy(): Promise<LoginResult> {
      if (operation) await operation;
      if (stopped) return { status: "error", message: "앱을 종료하고 있어요." };
      if (screenData.confirmedSessionRevision !== undefined) return { status: "authenticated", message: snapshot().message };
      if (status.state === "waiting") {
        const checked = await serialize(() => probe(true));
        return { status: checked.state === "authenticated" ? "authenticated" : "login_required", message: checked.message };
      }
      if (retryConfirmation) return serialize(() => confirm(false));
      return serialize(async () => {
        if (startupSettings) {
          await prepareStartup();
          const next = snapshot();
          return { status: next.state === "authenticated" ? "authenticated" : next.state === "error" ? "error" : "login_required", message: next.message };
        }
        screenData.invalidateSession();
        return confirm(true);
      });
    },
    shutdown() { stopped = true; clearTimer(); },
  };
}
