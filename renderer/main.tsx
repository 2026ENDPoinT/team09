import { useCallback, useEffect, useEffectEvent, useLayoutEffect, useRef, useState, type ComponentProps } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import type { CourseOverview, CourseStats, HomeSnapshot, LmsBridge, PrefetchStatus } from "../shared/lms.js";
import { residenceDiningHall, type StudentPreferences } from "../shared/student-preferences.js";
import type { ChatConfig } from "../shared/chat.js";
import type { WorkspaceAction, WorkspaceActionStatus, WorkspaceMode, WorkspaceScreen } from "../shared/chat-workspace.js";
import type { CourseNoticeSettings } from "../shared/course-notice-index.js";
import { assignmentDueTime, defaultAssignmentVisibility, isAssignmentVisible, visibleCourseBriefing, type AssignmentVisibility } from "../shared/assignment-visibility.js";
import { Settings } from "./settings.js";
import { campusNoticeKey, type CampusNotice, type CampusNoticeDetail } from "../shared/campus-notices.js";
import { Briefing } from "./briefing.js";
import { CampusNotices, NoticeDetail } from "./campus-notices.js";
import { CourseClassroom, type AssignmentScroll } from "./course-classroom.js";
import { CourseNoticeDialog } from "./course-notice.js";
import { CourseNoticeIndexScreen } from "./course-notice-index.js";
import { DormMenuView } from "./dorm-menu.js";
import { MyProfile } from "./my-profile.js";
import { ChatSidebar, type ChatSidebarHandle } from "./chat-sidebar.js";
import { Timetable } from "./timetable.js";
import { Dashboard, type DashboardAssignment, type DashboardNotice } from "./dashboard.js";
import { FocusFiles, FocusHome, FocusNavigation, type FocusScreen, type PdfStudyGuide } from "./focus-workspace.js";
import { FocusLectures } from "./focus-lectures.js";
import { useFocusLibrary } from "./use-focus-library.js";
import { WorkspaceSearch } from "./workspace-search.js";
import { WorkspaceSplitter, useWorkspaceWidths } from "./workspace-splitter.js";
import { WorkspaceModeSwitch } from "./workspace-mode.js";
import { useScreenRead } from "./use-screen-read.js";
import "./styles.css";
import "./dark-mono.css";
import "./lethimcook.css";
import "./workspace-motion.css";
import "./workspace-mode.css";
import { AstraWelcome } from "./astra-welcome.js";
import { useAstraLogin } from "./use-astra-login.js";

declare global {
  interface Window {
    ast: LmsBridge;
  }
}

type Phase = "idle" | "connected" | "login_required";

const phaseLabels: Record<Phase, string> = {
  idle: "로그인 확인 전",
  connected: "e-Class 연결됨",
  login_required: "로그인 필요",
};

const countingMessage = "과목별 목록을 확인하고 있어요.";

const courseCardCounts = [["course_notice", "공지"], ["assignment", "과제"], ["material", "강의자료"]] as const;

const defaultMessage = "ASTRA에 로그인하면 수강 정보를 확인할 수 있어요.";

function CourseCard({ item, onCourse }: { item: CourseStats; onCourse: (id: string) => void }) {
  const { course, counts } = item;

  return (
    <article className="course">
      <div className="course-heading">
        <div>
          <h3><button type="button" className="course-entry" aria-label={`${course.name} 강의실 들어가기`}
            onClick={() => onCourse(course.id)}>{course.name}</button></h3>
          {course.professor && <p>{course.professor}</p>}
        </div>
        <span className="course-card-chevron" aria-hidden="true">›</span>
      </div>
      <dl className="course-counts">
        {courseCardCounts.map(([kind, label]) => (
          <div key={kind}>
            <dt>{label}</dt>
            <dd aria-label={counts[kind] == null ? "확인 전" : undefined}>{counts[kind] ?? "—"}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

function Summary({ overview, onCourse }: { overview: CourseOverview; onCourse: (id: string) => void }) {
  if (!overview.courses.length) return <div className="empty"><p>조회된 수강 과목이 없어요.</p></div>;
  const groups = [
    { category: "regular", title: "정규과목" },
    { category: "non_regular", title: "비정규과목" },
  ] as const;
  return (
    <div className="course-groups">
      {groups.map(({ category, title }) => {
        const courses = overview.courses.filter(({ course }) => course.category === category);
        if (!courses.length) return null;
        return <section key={category} className="course-section" aria-label={title}>
          <h2>{title} <span>{courses.length}개</span></h2>
          <div className="course-grid">
            {courses.map((item) => <CourseCard key={item.course.id} item={item} onCourse={onCourse} />)}
          </div>
        </section>;
      })}
      {overview.non_regular == null && <p className="course-overview-note">비정규과목은 확인하지 못했어요.</p>}
    </div>
  );
}

async function readOverview(refresh: boolean) {
  const result = await window.ast.getCourseOverview(refresh);
  return result.status === "ok" ? result.overview : result;
}

function useClassroom(revision: number, authenticated: boolean, visible: boolean) {
  const { data, loading, error, loadedAt, refresh } = useScreenRead(String(revision), authenticated, readOverview, authenticated && visible);
  const phase: Phase = error?.status === "login_required" ? "login_required" : authenticated ? "connected" : "idle";
  return {
    phase, busy: authenticated && loading, notice: error?.message ?? (data ? "수강 과목과 강의실 목록을 조회했어요." : defaultMessage),
    error: !!error, overview: authenticated ? data : null, checkedAt: loadedAt, refresh,
  };
}

function Classroom({ phase, busy, notice, error, overview, checkedAt, refresh, onCourse }:
  ReturnType<typeof useClassroom> & { onCourse: (id: string) => void }) {
  return (
    <>
        <section className="intro" aria-labelledby="page-title">
          <div>
            <h1 id="page-title">내 강의실</h1>
            {overview && <p className="subtitle">수강 과목 {overview.courses.length}개</p>}
          </div>
          <div className="actions">
            {phase === "connected" && (
              <button className="button" type="button" onClick={refresh} disabled={busy}>새로고침</button>
            )}
          </div>
        </section>
        <div className={`status${!busy && error ? " status--attention" : ""}`} role="status" aria-live="polite">
          <span className={`status-dot${phase === "connected" ? " status-dot--connected" : ""}`} aria-hidden="true" />
          <strong>{phaseLabels[phase]}</strong>
          <span>{busy ? countingMessage : error || !overview ? notice
            : checkedAt ? `${new Intl.DateTimeFormat("ko-KR", { hour: "numeric", minute: "2-digit" }).format(checkedAt)} 확인` : ""}</span>
        </div>
        {overview ? (
          <Summary overview={overview} onCourse={onCourse} />
        ) : (
          <section className="empty" aria-label="과목 조회 안내">
            <h2>{busy ? "과목별 목록 조회 중" : "과목별 조회 결과"}</h2>
            <p>
              {busy
                ? "과제, 강의자료, 게시판 등의 목록을 확인하고 있어요."
                : notice}
            </p>
          </section>
        )}
    </>
  );
}

const noticeScreens = [
  ["class-notice-index", "수업 공지"],
  ["campus-notices", "대학생활 공지"],
] as const;

type Screen = Exclude<WorkspaceScreen, "focus-files">;
type CourseTarget = { courseId: string; assignmentScroll?: AssignmentScroll };
const macWindowChrome = navigator.platform.startsWith("Mac");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const readBriefing = (refresh: boolean) => window.ast.getCourseBriefing(refresh);
const readTimetable = (refresh: boolean) => window.ast.getCourseTimetable(undefined, refresh);

function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [mode, setMode] = useState<WorkspaceMode>("normal");
  const focusMode = screen === "home" && mode === "focus";
  const [focusScreen, setFocusScreen] = useState<FocusScreen>("home");
  const [focusGuide, setFocusGuide] = useState<PdfStudyGuide>();
  const [focusFolder, setFocusFolder] = useState<string | null>(null);
  const [focusHomeFolder, setFocusHomeFolder] = useState<string | null>(null);
  const [openedScreens, setOpenedScreens] = useState(() => new Set<Screen>());
  const [dormMenuVersion, setDormMenuVersion] = useState(0);
  const [collapsed, setCollapsed] = useState(false);
  const [sidebarMoving, setSidebarMoving] = useState(false);
  const sidebarCollapsed = collapsed && !focusMode;
  const widths = useWorkspaceWidths(sidebarCollapsed);
  const [accountOpen, setAccountOpen] = useState(false);
  const [focusChatSettings, setFocusChatSettings] = useState(false);
  const [savedChatConfig, setSavedChatConfig] = useState<{ revision: number; value: ChatConfig }>();
  const [savedAssignmentSettings, setSavedAssignmentSettings] = useState<{ revision: number; value: AssignmentVisibility }>();
  const [savedCourseNoticeSettings, setSavedCourseNoticeSettings] = useState<{ revision: number; value: CourseNoticeSettings }>();
  const [deadlineClock, updateDeadlineClock] = useState(0);
  const [courseTarget, setCourseTarget] = useState<CourseTarget>();
  const [selectedNotice, setSelectedNotice] = useState<DashboardNotice | null>(null);
  const [campusSelection, setCampusSelection] = useState<{ notice: CampusNotice; detail?: CampusNoticeDetail } | null>(null);
  const [recent, setRecent] = useState<DashboardAssignment[]>([]);
  const [resourceError, setResourceError] = useState<string>();
  const [entry, setEntry] = useState<"welcome" | "entering" | "open">("welcome");
  const [storedPreferences, setStoredPreferences] = useState<{ revision: number; value: StudentPreferences | null }>();
  const [preferencesErrorRevision, setPreferencesErrorRevision] = useState<number>();
  const [setupShown, setSetupShown] = useState(false);
  const login = useAstraLogin();
  const [prefetch, setPrefetch] = useState<PrefetchStatus>({
    state: "idle", completed: 0, total: 0, sessionRevision: 0,
  });
  const [savedHome, setSavedHome] = useState<{ revision: number; value: HomeSnapshot | null }>();
  const session = useRef(0);
  const authenticated = login.status.state === "authenticated" && prefetch.state !== "idle";
  const revision = prefetch.sessionRevision;
  const focusLibrary = useFocusLibrary(revision, focusMode && (focusScreen === "home" || focusScreen === "files") && entry === "open");
  const timetableVisible = screen === "timetable" || (focusMode && focusScreen === "timetable");
  const homeReady = savedHome?.revision === revision;
  const home = authenticated && homeReady ? savedHome.value : null;
  const preferences = authenticated && storedPreferences?.revision === revision ? storedPreferences.value : undefined;
  const preferencesError = preferencesErrorRevision === revision;
  const fallback = authenticated && homeReady && !home;
  const legacyClassroom = useClassroom(prefetch.sessionRevision, fallback, false);
  const connected = authenticated && (home ? home.error?.status !== "login_required" : legacyClassroom.phase !== "login_required");
  const classroom = home ? {
    ...legacyClassroom, phase: connected ? "connected" as const : "login_required" as const,
    overview: connected ? home.overview : null, busy: false, error: !!home.error,
    notice: home.error?.message ?? "수강 목록을 확인했어요.", checkedAt: home.checkedAt ?? Date.now(),
    refresh: () => void window.ast.refreshHome(),
  } : legacyClassroom;
  const briefing = useScreenRead(String(prefetch.sessionRevision), fallback && connected, readBriefing, false);
  const timetable = useScreenRead(String(prefetch.sessionRevision), fallback && connected, readTimetable, false);
  const courseBriefing = home?.briefing ?? briefing.data;
  const assignmentSettings = savedAssignmentSettings?.revision === revision ? savedAssignmentSettings.value : defaultAssignmentVisibility;
  const assignmentSettingsReady = authenticated && savedAssignmentSettings?.revision === revision;
  const readCourseNoticeSettings = useCallback(() => window.ast.getCourseNoticeSettings(revision), [revision]);
  const storedCourseNoticeSettings = useScreenRead(String(revision), authenticated, readCourseNoticeSettings, false);
  const courseNoticeSettings = savedCourseNoticeSettings?.revision === revision ? savedCourseNoticeSettings.value : storedCourseNoticeSettings.data;
  const now = new Date();
  const visibleBriefing = connected ? visibleCourseBriefing(courseBriefing, assignmentSettings, now) : null;
  const visibleRecent = recent.filter(({ due_at }) => isAssignmentVisible(due_at, assignmentSettings, now));
  const roster = authenticated ? login.status.courseRoster : undefined;
  const studentProfile = authenticated ? login.status.studentProfile : undefined;
  const displayName = authenticated ? login.status.displayName?.trim() : undefined;
  const homeLoginError = [briefing.error, timetable.error].find((error) => error?.status === "login_required");
  const loginError = home?.error?.status === "login_required" ? home.error.message
    : classroom.phase === "login_required" ? classroom.notice : homeLoginError?.message;
  const needsSetup = authenticated && !loginError && preferences === null;
  const residence = preferences?.residence;
  const preferredDorm = residence ? residenceDiningHall[residence] : undefined;
  const courses = (home?.overview ?? classroom.overview)?.courses.map(({ course }) => course) ?? roster?.courses ?? [];
  const regularCourses = courses.filter(({ category }) => category === "regular");
  const inCourse = screen === "course" || screen === "course-notices";
  const activeCourse = inCourse ? courses.find(({ id }) => id === courseTarget?.courseId) : undefined;
  const courseNotices = connected ? courseBriefing?.recent_notices ?? [] : [];
  const assignments = visibleBriefing?.pending_assignments ?? [];
  const workspace = useRef<HTMLDivElement>(null);
  const main = useRef<HTMLDivElement>(null);
  const normalHomeScroll = useRef<number | null>(null);
  const screenTransition = useRef<ViewTransition | null>(null);
  const screenRequest = useRef(0);
  const pendingAssignment = useRef<{ request: number; cancel: () => void } | undefined>(undefined);
  const headerMark = useRef<HTMLSpanElement>(null);
  const accountTrigger = useRef<HTMLButtonElement>(null);
  const accountPanel = useRef<HTMLDivElement>(null);
  const chat = useRef<ChatSidebarHandle>(null);
  const homeVersion = prefetch.homeVersion;

  useLayoutEffect(() => {
    if (focusMode || normalHomeScroll.current === null) return;
    if (screen === "home" && entry === "open") main.current?.scrollTo(0, normalHomeScroll.current);
    normalHomeScroll.current = null;
  }, [entry, focusMode, screen]);

  useLayoutEffect(() => {
    if (!sidebarMoving) return;
    const transition = workspace.current?.getAnimations().find((animation) =>
      animation instanceof CSSTransition && animation.transitionProperty === "grid-template-columns");
    if (!transition) {
      setSidebarMoving(false);
      return;
    }
    let active = true;
    const end = () => { if (active) setSidebarMoving(false); };
    void transition.finished.then(end, end);
    return () => { active = false; };
  }, [collapsed, sidebarMoving]);

  useEffect(() => {
    if (!authenticated) return;
    let active = true;
    const save = (value: HomeSnapshot | null) => {
      if (!active || session.current !== revision) return;
      setSavedHome((current) => !value && current?.revision === revision ? current : { revision, value });
    };
    void window.ast.getHomeSnapshot().then(save, () => save(null));
    return () => { active = false; };
  }, [authenticated, revision, homeVersion]);

  const entered = useCallback(() => {
    setEntry((stage) => stage === "entering" ? "open" : stage);
    setSetupShown(false);
  }, []);
  const applyPreferences = useCallback((value: StudentPreferences | null) => {
    if (session.current === revision) setStoredPreferences({ revision, value });
  }, [revision]);
  const readPreferences = useCallback(async () => {
    setPreferencesErrorRevision(undefined);
    try {
      applyPreferences(await window.ast.getStudentPreferences());
    } catch {
      if (session.current === revision) setPreferencesErrorRevision(revision);
    }
  }, [applyPreferences, revision]);

  useEffect(() => { if (authenticated) void readPreferences(); }, [authenticated, readPreferences]);
  useEffect(() => {
    if (!authenticated) return;
    let active = true;
    void (async () => window.ast.getAssignmentSettings())().then((value) => {
      if (active && session.current === revision) setSavedAssignmentSettings({ revision, value });
    }, () => {
      if (active && session.current === revision) setSavedAssignmentSettings({ revision, value: defaultAssignmentVisibility });
    });
    return () => { active = false; };
  }, [authenticated, revision]);

  useEffect(() => {
    if (!connected) return;
    const time = Date.now();
    const next = [...(courseBriefing?.pending_assignments ?? []), ...(courseBriefing?.completed_assignments ?? []), ...recent]
      .map(({ due_at }) => assignmentDueTime(due_at)?.getTime() ?? 0)
      .reduce((next, due) => due >= time ? Math.min(next, due + 1) : next, time + 60_000);
    const advance = () => updateDeadlineClock((tick) => tick + 1);
    const timer = window.setTimeout(advance, next - time);
    function onVisibility() { if (!document.hidden) advance(); }
    document.addEventListener("visibilitychange", onVisibility);
    return () => { window.clearTimeout(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [courseBriefing, connected, deadlineClock, recent]);

  useEffect(() => {
    if (needsSetup) setSetupShown(true);
    else if (!authenticated || loginError) setSetupShown(false);
  }, [authenticated, loginError, needsSetup]);

  useEffect(() => {
    if (connected && homeReady && assignmentSettingsReady && preferences && !loginError && entry === "welcome") setEntry("entering");
  }, [assignmentSettingsReady, connected, entry, homeReady, loginError, preferences]);

  useEffect(() => {
    if (entry !== "welcome" && (!authenticated || loginError)) {
      cancelAssignmentNavigation();
      setAccountOpen(false);
      normalHomeScroll.current = null;
      setMode("normal");
      setEntry("welcome");
    }
  }, [entry, authenticated, loginError]);

  useEffect(() => {
    let active = true;
    let receivedEvent = false;
    const unsubscribe = window.ast.onPrefetchStatus((status) => {
      receivedEvent = true;
      if (active) updatePrefetch(status);
    });
    void window.ast.getPrefetchStatus().then((status) => {
      if (active && !receivedEvent) updatePrefetch(status);
    }, () => {});
    return () => { active = false; unsubscribe(); };
  }, []);

  function updatePrefetch(status: PrefetchStatus) {
    if (session.current !== status.sessionRevision) {
      screenTransition.current?.skipTransition();
      cancelAssignmentNavigation();
      session.current = status.sessionRevision;
      setRecent([]);
      setSelectedNotice(null);
      setResourceError(undefined);
      setFocusFolder(null);
      setFocusHomeFolder(null);
      setFocusScreen("home");
      setFocusGuide(undefined);
      setSetupShown(false);
      if (status.state === "idle") {
        setCourseTarget(undefined);
        setMode("normal");
        setScreen("home");
      }
    }
    setPrefetch(status);
  }

  useEffect(() => {
    const root = document.documentElement;
    const onPointerDown = () => root.setAttribute("data-pointer-input", "");
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey && !event.ctrlKey && !event.metaKey) root.removeAttribute("data-pointer-input");
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown, true);
      root.removeAttribute("data-pointer-input");
    };
  }, []);

  useEffect(() => {
    if (accountOpen) accountPanel.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [accountOpen]);

  function animateWorkspace(type: "ast-screen" | "ast-mode", update: () => void) {
    const transition = document.startViewTransition({ types: [type], update });
    screenTransition.current = transition;
    void transition.ready.catch(() => {});
    const clear = () => {
      if (screenTransition.current === transition) screenTransition.current = null;
    };
    void transition.finished.then(clear, clear);
    return transition;
  }

  function openScreen(next: Screen, target?: CourseTarget, animate = true, signal?: AbortSignal) {
    cancelAssignmentNavigation();
    const request = ++screenRequest.current;
    const revision = session.current;
    screenTransition.current?.skipTransition();

    const update = () => {
      setOpenedScreens((current) => current.has(next) ? current : new Set([...current, next]));
      setScreen(next);
      if (next !== "home") {
        setMode("normal");
        setFocusGuide(undefined);
      }
      setAccountOpen(false);
      setResourceError(undefined);
      setCourseTarget(target);
      main.current?.scrollTo(0, 0);
    };

    if (!animate || (next === screen && target?.courseId === courseTarget?.courseId) || entry !== "open" || sidebarMoving || reducedMotion.matches || !document.startViewTransition) {
      update();
      return;
    }

    return animateWorkspace("ast-screen", () => {
      if (!signal?.aborted && request === screenRequest.current && revision === session.current) flushSync(update);
    });
  }

  function openCourse(id: string) {
    openScreen("course", { courseId: id });
  }

  function openHomeDormMenu() {
    setDormMenuVersion((version) => version + 1);
    openScreen("dorm-menu");
  }

  function openSettings(focusChat = false) {
    setFocusChatSettings(focusChat);
    openScreen("settings");
  }

  function toggleSidebar() {
    screenTransition.current?.skipTransition();
    setSidebarMoving(!reducedMotion.matches);
    setCollapsed((current) => !current);
  }

  function signInAgain() {
    openScreen("home", undefined, false);
    normalHomeScroll.current = null;
    setMode("normal");
    setEntry("welcome");
    void login.start();
  }

  function changeMode(next: WorkspaceMode, options?: { home: true; signal: AbortSignal }) {
    if (!options && mode === next && !screenTransition.current?.types?.has("ast-mode")) return;
    const request = ++screenRequest.current;
    const revision = session.current;
    screenTransition.current?.skipTransition();
    if (!options && mode === next) return;
    cancelAssignmentNavigation();
    const update = () => {
      setSidebarMoving(false);
      setAccountOpen(false);
      if (next === "focus" && !focusMode) {
        normalHomeScroll.current = screen === "home" ? main.current?.scrollTop ?? 0 : null;
      }
      if (options) {
        setScreen("home");
        setCourseTarget(undefined);
        setResourceError(undefined);
        if (next === "normal") normalHomeScroll.current = null;
      }
      if (next === "focus" || options) {
        setFocusScreen("home");
        setFocusGuide(undefined);
        main.current?.scrollTo(0, 0);
      }
      setMode(next);
    };

    if ((screen === "home" && mode === next) || reducedMotion.matches || sidebarMoving || !document.startViewTransition) {
      update();
      return;
    }

    return animateWorkspace("ast-mode", () => {
      if (!options?.signal.aborted && request === screenRequest.current && revision === session.current) flushSync(update);
    });
  }

  function openFocusScreen(next: FocusScreen, guide?: PdfStudyGuide) {
    setFocusScreen(next);
    setFocusGuide(guide);
    if (next !== focusScreen) main.current?.scrollTo(0, 0);
  }

  function importFocusPdf(folderId: string | null, embedded = false) {
    const revision = session.current;
    void focusLibrary.importPdf(folderId, importedFolder => {
      if (session.current !== revision) return;
      if (embedded) {
        setFocusHomeFolder(importedFolder);
        return;
      }
      setFocusFolder(importedFolder);
      openFocusScreen("files");
    });
  }

  const focusFilesProps = {
    library: focusLibrary.library,
    busy: focusLibrary.busy,
    loading: focusLibrary.loading,
    message: focusLibrary.message,
    onEdit: focusLibrary.edit,
    onOpenPdf: (id: string) => { void focusLibrary.openPdf(id); },
    onReload: () => { void focusLibrary.reload(); },
  };

  function cancelAssignmentNavigation() {
    const pending = pendingAssignment.current;
    if (!pending) return;
    pendingAssignment.current = undefined;
    pending.cancel();
    void window.ast.cancelPreparedAssignment(pending.request).catch(() => {});
  }

  async function openAssignment(item: DashboardAssignment, showError = true, preparedRequest?: number): Promise<boolean> {
    if (preparedRequest === undefined) cancelAssignmentNavigation();
    const revision = session.current;
    setResourceError(undefined);
    try {
      const opened = await (preparedRequest === undefined
        ? window.ast.openAssignment({ assignmentId: item.id, courseId: item.course_id })
        : window.ast.showPreparedAssignment(preparedRequest));
      if (session.current !== revision) return false;
      if (opened) {
        setRecent((current) => [item, ...current.filter((previous) => previous.id !== item.id || previous.course_id !== item.course_id)].slice(0, 12));
        return true;
      }
    } catch {
      // Report a browser failure in the screen that launched it.
    }
    if (showError && session.current === revision) setResourceError("과제 창을 열지 못했어요.");
    return false;
  }

  async function openClassroomAssignment(item: DashboardAssignment, signal?: AbortSignal): Promise<WorkspaceActionStatus> {
    const revision = session.current;
    const target = { courseId: item.course_id, assignmentId: item.id };
    if (signal?.aborted || !courses.some(({ id }) => id === target.courseId)) return "unavailable";
    const transition = openScreen("course", { courseId: target.courseId }, true, signal);
    const request = screenRequest.current;
    const current = () => pendingAssignment.current?.request === request && session.current === revision && !signal?.aborted;
    const cancel = () => {
      if (pendingAssignment.current?.request !== request) return;
      cancelAssignmentNavigation();
      setCourseTarget((previous) => previous?.courseId === target.courseId && previous.assignmentScroll
        ? { courseId: target.courseId } : previous);
    };
    const abort = () => {
      if (transition && screenTransition.current === transition) transition.skipTransition();
      cancel();
    };
    const scrolled = new Promise<"ok" | "assignment_missing" | "cancelled">((resolve) => {
      pendingAssignment.current = { request, cancel: () => resolve("cancelled") };
      void Promise.resolve(transition?.finished).catch(() => {}).then(() => {
        if (!current()) return resolve("cancelled");
        setCourseTarget({ courseId: target.courseId, assignmentScroll: {
          id: item.id, onComplete: () => resolve("ok"), onMissing: () => resolve("assignment_missing"),
        } });
      });
    });
    signal?.addEventListener("abort", abort, { once: true });
    const prepared = window.ast.prepareAssignment(target, request, revision).catch(() => false);
    try {
      const result = await scrolled;
      if (!current()) return "cancelled";
      if (result === "assignment_missing") {
        cancel();
        setResourceError("강의실에서 해당 과제 위치를 찾지 못했어요.");
        return result;
      }
      if (result !== "ok") return result;
      const ready = await prepared;
      if (!current()) return "cancelled";
      if (!ready) {
        cancel();
        setResourceError("과제 창을 열지 못했어요.");
        return "browser_failed";
      }
      const opened = await openAssignment(item, true, request);
      if (!current()) return "cancelled";
      if (!opened) cancel();
      return opened ? "ok" : "browser_failed";
    } finally {
      signal?.removeEventListener("abort", abort);
      if (pendingAssignment.current?.request === request) pendingAssignment.current = undefined;
    }
  }

  const runChatWorkspaceAction = useEffectEvent(async (action: WorkspaceAction, signal: AbortSignal): Promise<WorkspaceActionStatus> => {
    if (entry !== "open" || signal.aborted) return "unavailable";
    let transition: ViewTransition | undefined;
    if (action.kind === "change-mode") {
      flushSync(() => { transition = changeMode(action.mode, { home: true, signal }); });
    } else {
      const course = action.courseId && courses.find(({ id }) => id === action.courseId);
      if (action.kind === "assignment") {
        if (!course) return "unavailable";
        return openClassroomAssignment({ id: action.assignmentId, course_id: course.id, course_name: course.name,
          title: action.title, due_at: action.dueAt, submitted: null }, signal);
      }
      const { screen: next } = action;
      if ((next === "course" || next === "course-notices") && !course) return "unavailable";
      if (next === "profile" && !connected) return "unavailable";
      if (next === "settings") setFocusChatSettings(false);
      if (next === "focus-files" || (focusMode && (next === "home" || next === "timetable"))) {
        flushSync(() => {
          openScreen("home", undefined, false);
          setMode("focus");
          openFocusScreen(next === "focus-files" ? "files" : next);
        });
        return "ok";
      }
      flushSync(() => { transition = openScreen(next, course ? { courseId: course.id } : undefined, true, signal); });
    }
    const request = screenRequest.current;
    const stop = () => transition?.skipTransition();
    signal.addEventListener("abort", stop, { once: true });
    try {
      await transition?.finished.catch(() => {});
      return !signal.aborted && request === screenRequest.current && session.current === revision ? "ok" : "cancelled";
    } finally {
      signal.removeEventListener("abort", stop);
    }
  });

  useEffect(() => {
    const running = new Map<string, AbortController>();
    const unsubscribe = window.ast.onChatWorkspaceAction(({ id, action }) => {
      if (!action) {
        running.get(id)?.abort();
        return;
      }
      const controller = new AbortController();
      running.set(id, controller);
      void runChatWorkspaceAction(action, controller.signal).catch(() => "unavailable" as const).then((status) => {
        running.delete(id);
        if (!controller.signal.aborted) void window.ast.completeChatWorkspaceAction(id, status).catch(() => {});
      });
    });
    return () => {
      unsubscribe();
      for (const controller of running.values()) controller.abort();
    };
  }, []);

  const searchProps: Omit<ComponentProps<typeof WorkspaceSearch>, "placement"> = {
    courses, notices: courseNotices, assignments: [...visibleRecent, ...assignments],
    onCourse: openCourse, onNotice: setSelectedNotice, onCampusNotice: (notice, detail) => setCampusSelection({ notice, detail }),
    onAssignment: (item) => void openAssignment(item), onAsk: (question) => chat.current?.ask(question),
  };

  return (
    <div className="ast-entry-shell" data-entry={entry}>
    <div className={`ast-workspace ast-dark-mono ast-let-him-cook${macWindowChrome ? " ast-window-chrome" : ""}${sidebarCollapsed ? " ast-nav-collapsed" : ""}`} ref={workspace}
      style={widths.style} inert={entry !== "open"} data-mode={focusMode ? "focus" : "normal"} data-sidebar-moving={sidebarMoving || undefined}>
      <header className="ast-chrome">
        <div className="ast-identity">
          <button type="button" className="ast-sidebar-toggle" onClick={toggleSidebar} disabled={focusMode}
            aria-controls="ast-sidebar" aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed ? "사이드바 열기" : "사이드바 닫기"}>
            <span className="ast-sidebar-icon" aria-hidden="true" />
          </button>
          <button type="button" className="ast-wordmark" onClick={() => focusMode ? openFocusScreen("home") : openScreen("home")} aria-label="AST 홈">
            <span ref={headerMark} className="ast-wordmark-art ast-header-mark" aria-hidden="true" />
          </button>
          <span>서울과학기술대학교</span>
        </div>
        <WorkspaceSearch {...searchProps} focusMode={focusMode} />
        <div className="ast-account" onKeyDown={(event) => {
          if (event.key === "Escape" && accountOpen) { setAccountOpen(false); accountTrigger.current?.focus(); }
        }}>
          <button ref={accountTrigger} type="button" className="ast-account-trigger" aria-expanded={accountOpen} onClick={() => setAccountOpen(!accountOpen)}>
            {displayName || (connected ? "e-Class 연결됨" : "e-Class 연결")} <span aria-hidden="true">▾</span>
          </button>
          {accountOpen && <div className="ast-account-panel" ref={accountPanel}>
            {connected && <button type="button" onClick={() => openScreen("profile")}>내 정보</button>}
            <button type="button" onClick={() => openSettings()}>설정</button>
            {connected && <button type="button" disabled={classroom.busy} onClick={() => {
              classroom.refresh();
              if (!home) { briefing.refresh(); timetable.refresh(); }
            }}>학습 정보 새로고침</button>}
            <p role="status">{classroom.busy ? countingMessage : classroom.notice}</p>
          </div>}
        </div>
      </header>
      <aside className="ast-navigation" id="ast-sidebar" hidden={sidebarCollapsed} inert={sidebarCollapsed}>
        {focusMode ? <FocusNavigation screen={focusScreen} onOpen={openFocusScreen} /> : <>
          <nav className="app-nav" aria-label="대학생활">
            <button type="button" aria-pressed={screen === "home"} onClick={() => openScreen("home")}>홈 화면</button>
            <button type="button" aria-pressed={screen === "classroom" || inCourse} onClick={() => openScreen("classroom")}>내 강의실</button>
            {regularCourses.length > 0 && <ul className="ast-course-nav" aria-label="수강 중인 정규과목">
              {regularCourses.map((course) => <li key={course.id}>
                <button type="button" aria-current={activeCourse?.id === course.id ? "page" : undefined}
                  onClick={() => openCourse(course.id)}>{course.name}</button>
              </li>)}
            </ul>}
            <button type="button" aria-pressed={screen === "timetable"} onClick={() => openScreen("timetable")}>시간표 및 캘린더</button>
            <button type="button" aria-pressed={noticeScreens.some(([key]) => screen === key)} onClick={() => openScreen("class-notice-index")}>
              공지 모아보기
            </button>
            <ul className="ast-course-nav" aria-label="공지 모아보기 하위 메뉴">
              {noticeScreens.map(([key, label]) => <li key={key}>
                <button type="button" aria-current={screen === key ? "page" : undefined} onClick={() => openScreen(key)}>{label}</button>
              </li>)}
            </ul>
          </nav>
          <nav className="app-nav ast-other-nav" aria-label="기타 메뉴">
            <button type="button" aria-pressed={screen === "dorm-menu"} onClick={() => openScreen("dorm-menu")}>기숙사 식단</button>
            {connected && <button type="button" aria-pressed={screen === "profile"} onClick={() => openScreen("profile")}>내 정보</button>}
            <button type="button" aria-pressed={screen === "settings"} onClick={() => openSettings()}>설정</button>
          </nav>
        </>}
      </aside>
      {!sidebarCollapsed && !focusMode && <WorkspaceSplitter pane="sidebar" {...widths.sidebar} onResize={(width) => { setSidebarMoving(false); widths.change("sidebar", width); }} />}
      <div className="ast-main" data-home={screen === "home" || undefined} ref={main}>
      <main>
        {focusMode && focusScreen === "home" && <FocusHome name={displayName} onGuide={guide => openFocusScreen("files", guide)} library={
            <FocusFiles {...focusFilesProps} embedded folderId={focusHomeFolder} onOpenFolder={id => {
              setFocusHomeFolder(id);
              if (id) void focusLibrary.edit({ kind: "visit-folder", id });
            }} onImport={() => importFocusPdf(focusHomeFolder, true)} />
          } />}
        {focusMode && focusScreen === "files" && <FocusFiles {...focusFilesProps} folderId={focusFolder}
          guide={focusGuide ? { kind: focusGuide, dismiss: () => setFocusGuide(undefined) } : undefined}
          onOpenFolder={setFocusFolder} onImport={() => importFocusPdf(focusFolder)} />}
        {focusMode && focusScreen === "lectures" && <FocusLectures key={revision} revision={revision}/>}
        {screen === "home" && <Dashboard key={revision} hidden={focusMode} overview={classroom.overview} roster={roster} displayName={displayName}
          dorm={preferredDorm} visible={entry === "open"}
          briefing={visibleBriefing} timetable={connected ? home?.timetable ?? timetable.data : null}
          briefingLoading={!courseBriefing && briefing.loading} timetableLoading={!home?.timetable && timetable.loading}
          assignmentsLoading={home?.assignmentsLoading ?? (!courseBriefing && briefing.loading)}
          checkedAt={home?.checkedAt} changes={home?.changes}
          connected={connected} status={classroom.error ? classroom.notice : undefined}
          dataError={connected ? briefing.error?.message ?? timetable.error?.message : undefined}
          onConnect={() => openSettings()}
          onTimetable={() => openScreen("timetable")} onClassroom={() => openScreen("classroom")}
          onCourse={openCourse} onBriefing={() => openScreen("briefing")} onDormMenu={openHomeDormMenu}
          onDiningSettings={() => openSettings()} onCourseNotices={() => openScreen("class-notice-index")}
          onNotice={setSelectedNotice} onAssignment={(item) => void openAssignment(item)} onClassroomAssignment={(item) => void openClassroomAssignment(item)} />}
        {resourceError && <p className="notice-inline-error ast-resource-error" role="status">{resourceError}</p>}
        <div hidden={screen !== "classroom"}>
          <Classroom {...classroom} onCourse={openCourse} />
        </div>
        {inCourse && connected && entry === "open" && (activeCourse ? (
          <CourseClassroom key={`${revision}:${activeCourse.id}`} course={activeCourse} revision={revision} noticeMode={screen === "course-notices"}
            assignmentScroll={courseTarget?.assignmentScroll}
            onBack={() => openScreen("classroom")} onShowNotices={() => openScreen("course-notices", { courseId: activeCourse.id })}
            onShowClassroom={() => openCourse(activeCourse.id)} onOpenNotice={setSelectedNotice} onSignIn={signInAgain}
            onOpenAssignment={(item) => openAssignment({ id: item.id, course_id: activeCourse.id, course_name: activeCourse.name,
              title: item.title, due_at: item.due_at, submitted: item.status === "not_submitted" ? false : null }, false)} />
        ) : <div className="empty"><p>수강 과목을 다시 선택해 주세요.</p>
          <button className="button" type="button" onClick={() => openScreen("classroom")}>내 강의실</button></div>)}
        {screen === "settings" && entry === "open" && <Settings key={revision} revision={revision} connected={connected}
          displayName={displayName} preferences={preferences} assignmentSettings={assignmentSettings} focusChat={focusChatSettings}
          courseNoticeSettings={courseNoticeSettings} courseNoticeSettingsLoading={storedCourseNoticeSettings.loading}
          onSignIn={signInAgain} onPreferencesSaved={applyPreferences}
          onChatSaved={(value) => { if (session.current === revision) setSavedChatConfig({ revision, value }); }}
          onAssignmentsSaved={(value) => { if (session.current === revision) setSavedAssignmentSettings({ revision, value }); }}
          onCourseNoticeSettingsSaved={(value) => { if (session.current === revision) setSavedCourseNoticeSettings({ revision, value }); }} />}
        {screen === "profile" && connected && entry === "open" &&
          <MyProfile key={revision} revision={revision} displayName={displayName} profile={studentProfile}
            onOpenSettings={() => openSettings()} roster={classroom.overview ? {
              regular: classroom.overview.regular, non_regular: classroom.overview.non_regular, courses,
            } : roster} onSignIn={signInAgain} />}
        {prefetch.state === "loading" && <span className="chat-sr-only" role="status">다른 화면도 미리 불러오고 있어요 · {prefetch.completed}/{prefetch.total}</span>}
        {selectedNotice && <CourseNoticeDialog key={selectedNotice.course_id + ":" + selectedNotice.id} notice={selectedNotice} onDismiss={() => setSelectedNotice(null)} />}
        {(openedScreens.has("timetable") || timetableVisible) && (
          <div className="ast-timetable-screen" hidden={!timetableVisible}>
            <Timetable key={prefetch.sessionRevision} visible={timetableVisible} assignmentSettings={assignmentSettings} now={now} home={home}
              mode={focusMode ? "focus" : "normal"} courses={courses}
              onSignIn={signInAgain} onOpenAssignment={(item) => void openAssignment(item)} />
          </div>
        )}
        {openedScreens.has("briefing") && (
          <div hidden={screen !== "briefing"}>
            <Briefing key={prefetch.sessionRevision} visible={screen === "briefing"} assignmentSettings={assignmentSettings} now={now} home={home}
              onSignIn={signInAgain} onOpenCampusNotices={() => openScreen("campus-notices")} />
          </div>
        )}
        {openedScreens.has("class-notice-index") && <div hidden={screen !== "class-notice-index"}>
          <CourseNoticeIndexScreen key={revision} revision={revision} visible={screen === "class-notice-index" && entry === "open"}
            includeNonRegular={authenticated && courseNoticeSettings?.includeNonRegular === true} onSignIn={signInAgain} />
        </div>}
        {openedScreens.has("campus-notices") && <div hidden={screen !== "campus-notices"}>
          <CampusNotices key={revision + ":" + (preferences?.departmentId ?? "")} visible={screen === "campus-notices"} preferences={preferences} />
        </div>}
        {campusSelection && <NoticeDetail key={campusNoticeKey(campusSelection.notice)} notice={campusSelection.notice}
          initialDetail={campusSelection.detail} onDismiss={() => setCampusSelection(null)} />}
        {openedScreens.has("dorm-menu") && <div hidden={screen !== "dorm-menu"}>
          <DormMenuView key={`${revision}:${dormMenuVersion}`} visible={screen === "dorm-menu" && entry === "open"} preferredDorm={preferredDorm} />
        </div>}
      </main>
      </div>
      {screen === "home" && entry === "open" && <WorkspaceModeSwitch mode={mode} onChange={changeMode}
        focusCalendar={focusMode && focusScreen === "timetable"} />}
      <WorkspaceSplitter pane="chat" {...widths.chat} onResize={(width) => { setSidebarMoving(false); widths.change("chat", width); }} />
      <div className="ast-chat-pane" id="ast-chat-pane"><ChatSidebar key={revision} ref={chat} letHimCook focusMode={focusMode} references={[...visibleRecent, ...assignments]}
        onOpenSettings={() => openSettings(true)} savedConfig={savedChatConfig?.revision === revision ? savedChatConfig.value : undefined} /></div>
    </div>
    {entry !== "open" && <AstraWelcome stage={entry} titlebar={macWindowChrome} destination={headerMark}
      state={loginError || preferencesError && authenticated ? "error" : login.status.state}
      message={loginError ?? (authenticated ? preferencesError ? "저장된 설정을 불러오지 못했어요." : "계정 설정을 확인하고 있어요." : login.status.message)}
      setup={needsSetup || setupShown && authenticated && !loginError}
      setupCompleted={!!preferences} sessionRevision={revision} displayName={login.status.displayName}
      studentProfile={login.status.studentProfile}
      onSetupComplete={applyPreferences}
      retryPreferences={preferencesError && authenticated && !loginError}
      onLogin={() => void (preferencesError && authenticated && !loginError ? readPreferences() : login.start())} onEntered={entered} />}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
