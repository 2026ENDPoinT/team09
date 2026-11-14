import type { CampusNoticeBoard, CampusNoticeDetail, CampusNoticeError, CampusNoticePage, SchoolCampusNoticeBoard } from "../shared/campus-notices.js";
import { campusNoticeBoards, isSchoolCampusNoticeBoard } from "../shared/campus-notices.js";
import type { DepartmentNoticeBoard } from "../shared/seoultech-department-notices.js";
import type { CourseClassroomData, CourseClassroomInfo, CourseNoticePage, CourseRecentNotices } from "../shared/course-classroom.js";
import type { CampusBriefing, CourseBriefing, CourseNoticeDetail, CourseRoster, CourseTimetable, Dorm, DormMenu, DormMenuPeriod, HomeSnapshot, LmsBridgeError, OverviewResult, PrefetchStatus, StudentProfile, StudentProfileDetails } from "../shared/lms.js";
import { shiftTimetableDate, timetableWeekStart } from "../shared/timetable-week.js";
import { ReadCache, StaleReadError, type ReadOptions } from "./data-cache.js";
import type { VerifiedAccount } from "./account-data.js";
import { AccountScreenCache } from "./account-screen-cache.js";
import { HomeSync, emptyHome } from "./home-sync.js";
import { BackgroundReadDeferred } from "./lms-access.js";
import { CampusNoticeIndex } from "./campus-notice-index.js";
import { CourseNoticeIndex } from "./course-notice-index.js";

export type ScreenRequest = <T>(tool: string, args: Record<string, unknown>, timeout: number, errorMessage: string,
  signal?: AbortSignal, mayStart?: () => boolean) => Promise<T | CampusNoticeError>;
type LoadOptions = { force?: boolean; background?: boolean; persistKey?: string };

function seoulToday() {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts();
  return ["year", "month", "day"].map((type) => parts.find((part) => part.type === type)!.value).join("-");
}
function failed(value: unknown) {
  return !!value && typeof value === "object" && ("status" in value && ["error", "login_required"].includes(String(value.status)) ||
    "unavailable" in value && Array.isArray(value.unavailable) && value.unavailable.length > 0);
}

export class ScreenData {
  private cache = new ReadCache();
  private revision = 0;
  private batch = 0;
  private authenticating = false;
  private stopped = false;
  private verifiedAccount: VerifiedAccount | undefined;
  private courseRoster: CourseRoster | undefined;
  private verifiedProfile: StudentProfile | undefined;
  private disk?: AccountScreenCache;
  private readonly accountCaches = new Map<string, AccountScreenCache>();
  private readonly campusNotices: CampusNoticeIndex;
  private readonly departmentNotices: CampusNoticeIndex;
  private courseNotices?: CourseNoticeIndex;
  private home?: HomeSync;
  private snapshot: PrefetchStatus = { state: "idle", completed: 0, total: 0, sessionRevision: 0 };

  constructor(private request: ScreenRequest, private notify: (status: PrefetchStatus) => void,
    private readonly accountOptions?: { directory: (account: VerifiedAccount) => string; busy: () => boolean; publicDirectory?: string }) {
    this.campusNotices = new CampusNoticeIndex(
      (board, startPage, background) => this.cache.read(`notice-list:${board}:${startPage}`,
        () => this.request<CampusNoticePage>("list_campus_notices", { board, start_page: startPage, pages: startPage === 1 ? 3 : 1 },
          60_000, "공지 목록을 불러오지 못했어요."),
        { lane: "campus", background, retain: false }),
      ({ board, board_id, id }, background) => this.cache.read(`notice-detail:${board}:${board_id}:${id}`,
        () => this.request<CampusNoticeDetail>("get_campus_notice", { board, board_id, notice_id: id }, 45_000, "공지 본문을 불러오지 못했어요."),
        { lane: "campus", background, retain: false }),
      accountOptions?.publicDirectory,
    );
    this.departmentNotices = new CampusNoticeIndex(
      (board, startPage, background) => this.cache.read(`notice-list:${board}:${startPage}`,
        () => this.request<CampusNoticePage>("list_department_notices",
          { source_id: board, start_page: startPage, pages: startPage === 1 ? 3 : 1 }, 60_000, "소속 공지 목록을 불러오지 못했어요."),
        { lane: "campus", background, retain: false }),
      ({ board, board_id, id }, background) => this.cache.read(`notice-detail:${board}:${board_id}:${id}`,
        () => this.request<CampusNoticeDetail>("get_department_notice",
          { source_id: board, board_id, notice_id: id }, 45_000, "공지 본문을 불러오지 못했어요."),
        { lane: "campus", background, retain: false }),
      accountOptions?.publicDirectory, Date.now, true,
    );
  }

  get status() { return { ...this.snapshot }; }
  get account() { return this.confirmedSessionRevision === undefined ? undefined : this.verifiedAccount; }
  get roster() { return this.confirmedSessionRevision === undefined ? undefined : this.courseRoster; }
  get studentProfile() { return this.confirmedSessionRevision === undefined ? undefined : this.verifiedProfile; }

  get confirmedSessionRevision(): number | undefined {
    if (!this.stopped && !this.authenticating && this.revision > 0) return this.revision;
  }

  shutdown() {
    this.stopped = true;
    this.batch++;
    this.cache.resetAll();
    this.home?.stop();
    this.courseNotices?.stop();
    const pending = Promise.all([this.campusNotices.stop(), this.departmentNotices.stop(),
      ...[...this.accountCaches.values()].map((cache) => cache.flush())]);
    this.accountCaches.clear();
    this.disk = undefined;
    return pending;
  }

  async homeSnapshot(): Promise<HomeSnapshot | null> {
    const home = this.home;
    if (!home) return null;
    await home.ready;
    return !this.stopped && home === this.home ? home.snapshot() : emptyHome();
  }

  refreshHome() { return this.home?.refresh(); }

  private publish(status: Omit<PrefetchStatus, "sessionRevision">) {
    this.snapshot = { ...status, sessionRevision: this.revision };
    this.notify(this.status);
  }

  invalidateSession() {
    this.batch++;
    this.revision++;
    this.authenticating = true;
    this.verifiedAccount = undefined;
    this.courseRoster = undefined;
    this.verifiedProfile = undefined;
    this.clearDepartmentNoticeSelection();
    this.home?.stop();
    this.home = undefined;
    this.courseNotices?.stop();
    this.courseNotices = undefined;
    this.disk = undefined;
    this.cache.resetPrivate();
    this.publish({ state: "idle", completed: 0, total: 0 });
  }

  authenticate<T>(loader: () => Promise<T>): Promise<T> {
    return this.cache.read(`authenticate:${this.revision}`, loader, { lane: "lms", private: true, force: true });
  }

  async readStudentProfile(expectedRevision: unknown, refresh: boolean): Promise<StudentProfileDetails | LmsBridgeError> {
    const revision = this.confirmedSessionRevision;
    const loginRequired = { status: "login_required", message: "내 정보를 확인하려면 e-Class에 다시 로그인해 주세요." } as const;
    if (revision === undefined || expectedRevision !== revision || (this.accountOptions && !this.account)) return loginRequired;

    const current = () => revision === this.confirmedSessionRevision;
    const error = { status: "error", message: "e-Class에서 내 정보를 불러오지 못했어요. 다시 시도해 주세요." } as const;
    try {
      // Contact details stay in the process-local cache for this verified session.
      const result = await this.cache.read(`student-profile:${revision}`,
        () => this.request<StudentProfileDetails>("get_student_profile", {}, 12_000, error.message, undefined, current),
        { lane: "lms", private: true, force: refresh });
      return current() ? result : loginRequired;
    } catch {
      return current() ? error : loginRequired;
    }
  }

  private async read<T>(key: string, tool: string, args: Record<string, unknown>, timeout: number,
    options: ReadOptions & { persistKey?: string; memoryOnly?: boolean; mayStart?: () => boolean }): Promise<T | LmsBridgeError> {
    if (this.stopped) return { status: "error", message: "앱을 종료하고 있어요." };
    if (options.private && this.authenticating) return { status: "login_required", message: "로그인 확인을 마치면 자동으로 불러와요." };
    const disk = options.memoryOnly ? undefined : this.disk;
    const revision = this.revision;
    const persistedKey = options.persistKey ?? key.replace(/^\d{4}-\d{2}-\d{2}:/, "");
    try {
      if (disk) await disk.ready;
      if (this.stopped || disk && revision !== this.revision) throw new StaleReadError();
      const cached = this.cache.fresh<T>(key, options.private) ?? disk?.get<T>(persistedKey);
      const lookup = this.cache.read(key,
        () => this.request<T>(tool, args, timeout, "정보를 불러오지 못했어요. 다시 시도해 주세요.", undefined, options.mayStart),
        options).then((result) => {
        if (!failed(result) && revision === this.revision && !this.stopped) disk?.set(persistedKey, result);
        return result;
      });
      // Notice dialogs and other single-item readers await the response so an updated
      // body can replace the saved one on the same open operation.
      const isDetail = tool === "get_course_notice" || tool === "get_campus_notice";
      if (cached && !isDetail && !options.force && !options.background) {
        void lookup.catch(() => {});
        return cached;
      }
      const result = await lookup;
      if (cached && result && typeof result === "object" && "status" in result && result.status === "error") return cached;
      return result;
    } catch (error) {
      if (error instanceof BackgroundReadDeferred) throw error;
      return { status: "error", message: error instanceof StaleReadError ? "로그인 상태가 바뀌었어요. 다시 조회해 주세요." : "정보를 불러오지 못했어요. 다시 시도해 주세요." };
    }
  }

  overview(options: LoadOptions = {}) {
    if (this.home) return this.homeOverview(options);
    return this.read<OverviewResult>(seoulToday() + ":overview", "get_course_overview", { include_attendance: true }, 180_000, { ...options, lane: "lms", private: true });
  }

  private async homeOverview(options: LoadOptions): Promise<OverviewResult> {
    if (options.force) await this.refreshHome();
    const home = await this.homeSnapshot();
    return home?.error?.status === "login_required" ? home.error : home?.overview
      ? { status: "ok", overview: home.overview } : { status: "error", message: "수강 정보를 불러오고 있어요." };
  }

  async timetable(onDate?: string, options: LoadOptions = {}) {
    const today = seoulToday();
    const selected = onDate ?? today;
    const day = new Date(selected + "T00:00:00Z");
    if (Number.isNaN(day.getTime()) || day.toISOString().slice(0, 10) !== selected) return { status: "error", message: "올바른 날짜를 선택해 주세요." } as LmsBridgeError;
    const monday = timetableWeekStart(selected);
    const sunday = shiftTimetableDate(monday, 6);
    // e-Class weeks start on Sunday. Adjacent app weeks share one e-Class response.
    const sourceWeeks = [shiftTimetableDate(monday, -1), sunday];
    const home = options.background ? this.home : undefined;
    const revision = this.revision;
    if (home) await home.priorityReady;
    const [first, last] = await Promise.all(sourceWeeks.map(async (sourceWeek) => {
      const saved = home?.snapshot().timetable;
      if (!options.force && saved?.week_start === sourceWeek && revision === this.revision) return saved;
      const key = `${today}:${home ? "calendar" : "timetable"}:${sourceWeek}`;
      const load = () => this.read<CourseTimetable>(key, "get_course_timetable",
        { on_date: sourceWeek, include_rooms: !home }, 60_000, { ...options, lane: "lms", private: true,
          mayStart: home ? () => revision === this.revision && !this.stopped && !this.accountOptions?.busy() : undefined });
      while (!this.stopped && revision === this.revision) {
        try { return await load(); }
        catch (error) {
          if (!(error instanceof BackgroundReadDeferred)) throw error;
          await new Promise<void>((resolve) => { setTimeout(resolve, 1000).unref(); });
        }
      }
      return { status: "login_required", message: "로그인 상태가 바뀌었어요. 다시 조회해 주세요." } as const;
    }));
    if ("status" in last && last.status === "login_required") return last;
    if ("status" in first) return first;
    if ("status" in last) return last;
    return {
      ...first, on_date: selected, week_start: monday, week_end: sunday,
      entries: [...first.entries.filter((entry) => entry.date >= monday && entry.date < sunday),
        ...last.entries.filter((entry) => entry.date === sunday)],
    };
  }

  courseBriefing(options: LoadOptions = {}) {
    if (this.home) return this.homeBriefing(options);
    return this.read<CourseBriefing>(seoulToday() + ":course-briefing", "get_course_briefing", {}, 180_000, { ...options, lane: "lms", private: true });
  }
  private async homeBriefing(options: LoadOptions): Promise<CourseBriefing | LmsBridgeError> {
    if (options.force) await this.refreshHome();
    const home = await this.homeSnapshot();
    return home?.error?.status === "login_required" ? home.error : home?.briefing ??
      { status: "error", message: "과제와 수업 공지를 불러오고 있어요." };
  }
  private async readClassroom<T>(expectedRevision: number, key: string, tool: string, args: Record<string, unknown>,
    options: { force: boolean; retain?: boolean }, timeout: number): Promise<T | LmsBridgeError> {
    const current = () => expectedRevision === this.confirmedSessionRevision;
    const loginRequired = { status: "login_required", message: "강의실을 보려면 e-Class에 다시 로그인해 주세요." } as const;
    if (!current()) return loginRequired;
    try {
      const result = await this.read<T>(key, tool, args, timeout,
        { ...options, lane: "lms", private: true, memoryOnly: true, mayStart: current });
      return current() ? result : loginRequired;
    } catch (error) {
      if (error instanceof BackgroundReadDeferred && !current()) return loginRequired;
      throw error;
    }
  }

  courseClassroom(courseId: string, revision: number, force: boolean) {
    return this.readClassroom<CourseClassroomData>(revision, `course-classroom:${courseId}`, "get_course_classroom",
      { course_id: courseId }, { force }, 40_000);
  }

  courseClassroomInfo(courseId: string, revision: number, force: boolean) {
    return this.readClassroom<CourseClassroomInfo>(revision, `${seoulToday()}:course-classroom-info:${courseId}`,
      "get_course_classroom_info", { course_id: courseId }, { force }, 25_000);
  }

  courseRecentNotices(courseId: string, revision: number, force: boolean) {
    return this.readClassroom<CourseRecentNotices>(revision, `course-recent-notices:${courseId}`, "get_course_recent_notices",
      { course_id: courseId }, { force }, 35_000);
  }

  courseNoticePage(courseId: string, page: number, revision: number, query: string, force: boolean) {
    return this.readClassroom<CourseNoticePage>(revision, `course-notice-page:${courseId}:${page}:${query}`, "get_course_notice_page",
      { course_id: courseId, page, ...(query ? { query } : {}) }, { force, retain: !query }, 45_000);
  }

  async courseNoticeIndex(revision: number, afterVersion?: number) {
    if (revision !== this.confirmedSessionRevision) return { status: "login_required", message: "수업 공지를 보려면 e-Class에 로그인해 주세요." } as const;
    const result = await this.courseNotices?.snapshot(afterVersion);
    if (revision !== this.confirmedSessionRevision) return { status: "login_required", message: "수업 공지를 보려면 e-Class에 로그인해 주세요." } as const;
    return result === undefined ? { status: "error", message: "수강 목록을 확인하지 못했어요." } as const : result;
  }

  refreshCourseNoticeIndex(revision: number) {
    if (revision !== this.confirmedSessionRevision || !this.courseNotices) return false;
    void this.courseNotices.refresh(true);
    return true;
  }

  hasIndexedCourseNotice(courseId: string, noticeId: string) {
    return this.confirmedSessionRevision !== undefined && Boolean(this.courseNotices?.entry(courseId, noticeId));
  }

  courseNotice(courseId: string, noticeId: string, options: LoadOptions = {}, page?: number) {
    const key = `course-notice:${courseId}:${noticeId}`;
    const version = this.home?.noticeVersion(courseId, noticeId);
    const versionedKey = version ? `${key}:${version}` : key;
    return this.read<CourseNoticeDetail>(versionedKey, "get_course_notice",
      { course_id: courseId, notice_id: noticeId, ...(page === undefined ? {} : { page }) },
      65_000, { ...options, persistKey: versionedKey, lane: "lms", private: true });
  }
  campusBriefing(options: LoadOptions = {}) {
    return this.read<CampusBriefing>(seoulToday() + ":campus-briefing", "get_campus_briefing", {}, 105_000, { ...options, lane: "campus" });
  }
  campusList(board: CampusNoticeBoard, startPage: number, options: LoadOptions = {}) {
    return this.noticeIndexFor(board).list(board, startPage, options.force, options.background);
  }
  campusDetail(board: CampusNoticeBoard, boardId: string, noticeId: string, options: LoadOptions = {}) {
    return this.noticeIndexFor(board).detail({ board, board_id: boardId, id: noticeId }, options.background);
  }
  private noticeIndexFor(board: CampusNoticeBoard) {
    return isSchoolCampusNoticeBoard(board) ? this.campusNotices : this.departmentNotices;
  }
  campusNoticeIndex(afterRevision?: number, departmentBoards?: readonly DepartmentNoticeBoard[]) {
    return departmentBoards ? this.departmentNotices.snapshot(afterRevision, departmentBoards) : this.campusNotices.snapshot(afterRevision);
  }
  syncCampusNoticeIndex(force = false, departmentBoards?: readonly DepartmentNoticeBoard[]) {
    if (departmentBoards) this.departmentNotices.sync(force, departmentBoards);
    else this.campusNotices.sync(force);
  }
  clearDepartmentNoticeSelection() { this.departmentNotices.sync(false, []); }
  async dorm(dorm: Dorm, period: DormMenuPeriod, options: LoadOptions = {}) {
    const today = seoulToday();
    const result = await this.read<DormMenu>(`${today}:dorm:${dorm}`, "get_dorm_menu", { dorm, period: "week", on_date: today }, 25_000,
      { ...options, persistKey: `dorm:${dorm}:${timetableWeekStart(today)}`, lane: "dorm" });
    return "days" in result ? { ...result, period, days: period === "today" ? result.days.filter((day) => day.date === today) : result.days } : result;
  }

  warm(account?: VerifiedAccount, roster?: CourseRoster, profile?: StudentProfile) {
    this.verifiedAccount = account;
    this.courseRoster = roster;
    this.verifiedProfile = profile;
    this.authenticating = false;
    this.revision++;
    this.home?.stop();
    this.home = undefined;
    this.courseNotices?.stop();
    this.courseNotices = undefined;
    this.disk = undefined;
    if (account && this.accountOptions) {
      let disk = this.accountCaches.get(account.key);
      if (!disk) {
        disk = new AccountScreenCache(this.accountOptions.directory(account));
        this.accountCaches.set(account.key, disk);
      }
      this.disk = disk;
    }
    const batch = ++this.batch;
    const background = { background: true };
    const today = seoulToday();
    if (this.disk && roster && this.accountOptions) {
      const revision = this.revision;
      this.home = new HomeSync(roster, this.disk, (name, args, background) => this.cache.read(
        `home:${revision}:${name}:${JSON.stringify(args)}`,
        () => this.request(name, args, 60_000, "학습 정보를 불러오지 못했어요.", undefined,
          () => revision === this.revision && !this.stopped && (!background || !this.accountOptions!.busy())),
        { lane: "lms", private: true, force: true, background }),
        this.accountOptions.busy, () => {
          if (revision !== this.revision || this.stopped) return;
          this.publish({ ...this.snapshot, homeVersion: (this.snapshot.homeVersion ?? 0) + 1 });
        });
    }
    const home = this.home ? [() => this.home!.refresh()] : [
      () => this.overview(),
      () => this.timetable(),
      () => this.courseBriefing(),
    ];
    const otherScreens = [
      ...Object.keys(campusNoticeBoards).map((board) => () => this.campusList(board as SchoolCampusNoticeBoard, 1, background)),
      () => this.campusBriefing(background),
      ...(["kb", "seonglim", "surim"] as const).map((dorm) => () => this.dorm(dorm, "week", background)),
      ...this.home ? [] : [
        () => this.timetable(shiftTimetableDate(today, -7), background),
        () => this.timetable(shiftTimetableDate(today, 7), background),
      ],
    ];
    const total = home.length + otherScreens.length;
    let completed = 0;
    let hasFailure = false;
    this.publish({ state: "loading", completed, total });
    const track = (job: () => Promise<unknown>) =>
      job().then((result) => { hasFailure ||= failed(result); }, () => { hasFailure = true; }).finally(() => {
        if (batch !== this.batch) return;
        completed++;
        this.publish({ state: completed === total ? hasFailure ? "partial" : "ready" : "loading", completed, total, homeVersion: this.snapshot.homeVersion });
      });
    // Queue the home reads first on the LMS lane. Public data has separate lanes.
    const homeReads = Promise.all(home.map(track));
    void Promise.all(otherScreens.map(track));
    if (roster) {
      const revision = this.revision;
      this.courseNotices = new CourseNoticeIndex(roster.courses, this.disk, (tool, args, foreground) => this.cache.read(
        `course-notice-index:${revision}:${tool}:${JSON.stringify(args)}`,
        () => {
          const mayStart = () => revision === this.confirmedSessionRevision && (foreground() || !this.accountOptions?.busy());
          if (!mayStart()) throw new BackgroundReadDeferred();
          return this.request(tool, args, 25_000, "수업 공지를 불러오지 못했어요.", undefined, mayStart);
        }, { lane: "lms", private: true, background: !foreground(), retain: false }), homeReads);
      void this.courseNotices.refresh();
    }
  }
}
