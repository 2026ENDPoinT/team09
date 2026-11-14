import type { CourseBriefing, CourseNotice, CourseNoticeDetail, CourseRoster, CourseStats, CourseTimetable, HomeSnapshot, LmsBridgeError } from "../shared/lms.js";
import { asKoreanTime } from "../shared/assignment-visibility.js";
import { SCREEN_FRESHNESS_MS } from "../shared/screen-freshness.js";
import type { AccountScreenCache } from "./account-screen-cache.js";
import { BackgroundReadDeferred } from "./lms-access.js";

type AssignmentIndex = { id: string; title: string; submitted: boolean | null; signature: string };
type NoticeIndex = Omit<CourseNotice, "created_at" | "course_name"> & { created_at: string | null };
type CourseIndex = {
  assignments: AssignmentIndex[];
  notices: NoticeIndex[];
  counts: Record<string, number>;
  learning_activity: CourseStats["learning_activity"];
  signature: string;
};
type AssignmentDetail = { id: string; due_at: string | null; late_due_at?: string | null; submitted: boolean | null; submitted_at: string | null };
type CourseDetail = { assignments: (AssignmentDetail & { signature?: string })[]; stats: CourseStats | null };
type CourseRecord = {
  index: Omit<CourseIndex, "assignments"> & { assignments?: AssignmentIndex[] };
  details: Record<string, AssignmentDetail & { signature: string }>;
  stats?: CourseStats;
  statsSignature?: string;
  attendanceAt?: number;
  retryStatsAfter?: number;
  retryAttendanceAfter?: number;
};
type TimetableRecord = { data: CourseTimetable; signature: string; roomsChecked: boolean };
type SavedHome = {
  checkedAt?: number;
  timetable?: TimetableRecord;
  courses: Record<string, CourseRecord>;
  changes: HomeSnapshot["changes"];
};

const formatter = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", dateStyle: "short" });
const empty = (): HomeSnapshot => ({ overview: null, briefing: null, timetable: null, changes: [] });
const sleep = (ms: number) => new Promise<void>((resolve) => { const timer = setTimeout(resolve, ms); timer.unref(); });
const attendanceRefresh = 24 * 60 * 60_000;

export class HomeSync {
  private saved: SavedHome = { courses: {}, changes: [] };
  private stopped = false;
  private initial = true;
  private timer?: ReturnType<typeof setTimeout>;
  private running?: Promise<void>;
  private error?: LmsBridgeError;
  private timetable?: CourseTimetable;
  readonly ready: Promise<void>;
  readonly priorityReady: Promise<void>;
  private finishPriority!: () => void;

  constructor(private readonly roster: CourseRoster, private readonly cache: AccountScreenCache,
    private readonly request: <T>(name: string, args: Record<string, unknown>, background: boolean) => Promise<T | LmsBridgeError>,
    private readonly busy: () => boolean, private readonly publish: () => void,
    private readonly interval = SCREEN_FRESHNESS_MS) {
    this.ready = cache.ready.then(() => {
      this.saved = cache.get<SavedHome>("home-summary") ?? this.saved;
      this.timetable = this.saved.timetable?.data;
    });
    this.priorityReady = new Promise<void>((resolve) => { this.finishPriority = resolve; });
  }

  noticeVersion(courseId: string, id: string) {
    return this.saved.changes.find((item) => item.kind === "notice" && item.courseId === courseId && item.id === id)?.changedAt;
  }

  snapshot(): HomeSnapshot {
    const now = new Date();
    const today = formatter.format(now);
    const cutoff = Date.parse(today) - 6 * 86_400_000;
    const pending: CourseBriefing["pending_assignments"] = [];
    const completed: CourseBriefing["completed_assignments"] = [];
    const notices: CourseNotice[] = [];
    const stats: CourseStats[] = [];
    const unavailable: string[] = [];
    let hasIndex = this.roster.courses.length === 0;
    let hasAssignmentIndex = false;
    for (const course of this.roster.courses) {
      const record = this.saved.courses[course.id];
      if (!record) unavailable.push(course.name);
      else {
        hasIndex = true;
        hasAssignmentIndex ||= record.index.assignments !== undefined;
        for (const notice of record.index.notices) {
          const date = asKoreanTime(notice.created_at);
          if (notice.created_at && date && Date.parse(formatter.format(date)) >= cutoff && date <= now) {
            notices.push({ ...notice, created_at: notice.created_at, course_name: course.name });
          }
        }
        for (const assignment of record.index.assignments ?? []) {
          const detail = record.details[assignment.id];
          const checked = detail?.signature === assignment.signature ? detail : undefined;
          const submitted = checked?.submitted ?? assignment.submitted;
          // A failed detail read can retain the last date. Only a matching detail confirms submission.
          const item = { id: assignment.id, course_id: course.id, course_name: course.name, title: assignment.title,
            due_at: detail?.due_at ?? null, late_due_at: detail?.late_due_at ?? null, deadline_checked: checked !== undefined };
          const submittedAt = asKoreanTime(checked?.submitted_at)?.getTime();
          if (submitted !== true) pending.push({ ...item, submitted });
          else if (checked?.submitted_at && submittedAt != null && submittedAt <= now.getTime() && now.getTime() - submittedAt <= 172_800_000) {
            completed.push({ ...item, submitted: true, submitted_at: checked.submitted_at });
          }
        }
      }
      const counts = { ...record?.stats?.counts, ...record?.index.counts };
      const known = Object.entries(counts).filter(([key, value]) => key !== "files" && value != null);
      stats.push({ course, counts, total_posts: known.length ? known.reduce((sum, [, value]) => sum + (value ?? 0), 0) : null,
        attendance: record?.stats?.attendance, learning_activity: record?.index.learning_activity });
    }
    notices.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    pending.sort((a, b) => (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999"));
    completed.sort((a, b) => b.submitted_at.localeCompare(a.submitted_at));
    const timetable = this.timetable;
    return { checkedAt: this.saved.checkedAt, changes: this.saved.changes.filter((item) =>
      this.roster.courses.some((course) => course.id === item.courseId)), error: this.error,
      assignmentsLoading: this.initial && !this.error && !hasAssignmentIndex && this.roster.courses.length > 0,
      timetable: timetable && today >= timetable.week_start && today <= timetable.week_end ? timetable : null,
      overview: { regular: this.roster.regular, non_regular: this.roster.non_regular, courses: stats },
      briefing: hasIndex ? { as_of: new Date(this.saved.checkedAt ?? Date.now()).toISOString(),
        pending_assignments: pending, completed_assignments: completed, recent_notices: notices, ...(unavailable.length ? { unavailable } : {}) } : null };
  }

  start() { void this.refresh(); }
  stop() { this.stopped = true; clearTimeout(this.timer); this.finishPriority(); }

  refresh(): Promise<void> {
    if (this.stopped) return Promise.resolve();
    if (this.running) return this.running;
    clearTimeout(this.timer);
    const run = this.ready.then(() => this.update()).catch(() => {
      if (!this.stopped) this.error = { status: "error", message: "일부 학습 정보를 갱신하지 못했어요." };
    }).finally(() => {
      this.finishPriority();
      this.running = undefined;
      if (this.stopped) return;
      this.initial = false;
      this.publish();
      if (this.error?.status === "login_required") return;
      this.timer = setTimeout(() => this.start(), this.interval);
      this.timer.unref();
    });
    this.running = run;
    return run;
  }

  private async read<T>(name: string, args: Record<string, unknown>): Promise<T | undefined> {
    const background = !this.initial;
    while (!this.stopped && this.error?.status !== "login_required") {
      if (background && this.busy()) { await sleep(1000); continue; }
      try {
        const result = await this.request<T>(name, args, background);
        if (this.stopped) return;
        if (result && typeof result === "object" && "status" in result) {
          const error = result as LmsBridgeError;
          if (error.status === "login_required") this.error = error;
          return;
        }
        return result as T;
      } catch (error) {
        if (!(error instanceof BackgroundReadDeferred)) throw error;
        await sleep(1000);
      }
    }
  }

  private commit() {
    if (this.stopped) return;
    this.cache.set("home-summary", this.saved);
    this.publish();
  }

  private async update() {
    if (this.stopped) return;
    const today = formatter.format(new Date());
    const timetable = await this.read<CourseTimetable>("get_course_timetable", { on_date: today, include_rooms: false });
    if (timetable) {
      const signature = JSON.stringify([timetable.week_start, timetable.entries]);
      if (signature !== this.saved.timetable?.signature) {
        const previous = this.saved.timetable?.data.entries ?? [];
        const sameSlot = (a: typeof previous[number], b: typeof previous[number]) =>
          a.course_id === b.course_id && a.weekday === b.weekday && a.start_time === b.start_time && a.end_time === b.end_time;
        const entries = timetable.entries.map((entry) => {
          const old = previous.find((candidate) => sameSlot(entry, candidate));
          return !entry.room && old?.room ? { ...entry, room: old.room, room_source: old.room_source } : entry;
        });
        this.saved.timetable = { data: { ...timetable, entries }, signature, roomsChecked: false };
      }
      this.timetable = this.saved.timetable?.data ?? timetable;
      this.commit();
    }
    let complete = !!timetable;
    const checkedCourses = new Set<string>();
    const assignmentUpdates = new Map<string, { index: AssignmentIndex[]; details: CourseRecord["details"] }>();
    for (const course of this.roster.courses) {
      const index = await this.read<CourseIndex>("get_home_course_index", { course_id: course.id });
      if (!index) { complete = false; continue; }
      checkedCourses.add(course.id);
      const { assignments, ...courseIndex } = index;
      const previous = this.saved.courses[course.id];
      if (index.counts.assignment > assignments.length) complete = false;
      else assignmentUpdates.set(course.id, { index: assignments, details: { ...previous?.details } });
      if (previous) {
        this.recordChanges(course, "notice", index.notices.filter((item) => {
          const old = previous.index.notices.find(({ id }) => id === item.id);
          return !old || old.title !== item.title || old.content !== item.content || old.created_at !== item.created_at;
        }));
      }
      this.saved.courses[course.id] = { ...previous, index: { ...courseIndex, assignments: previous?.index.assignments },
        details: previous?.details ?? {} };
      this.commit();
    }
    this.finishPriority();
    for (const course of this.roster.courses) {
      const update = assignmentUpdates.get(course.id);
      if (!update) continue;
      const { index, details } = update;
      const record = this.saved.courses[course.id];
      const changed = index.filter(({ id, signature }) => details[id]?.signature !== signature)
        .sort((a, b) => Number(a.submitted === true) - Number(b.submitted === true));
      const fetchStats = Date.now() >= (record.retryStatsAfter ?? 0) && record.statsSignature !== record.index.signature;
      const fetchAttendance = course.category === "regular" && Date.now() >= (record.retryAttendanceAfter ?? 0) &&
        Date.now() - (record.attendanceAt ?? 0) >= attendanceRefresh;
      if (!changed.length && !fetchStats && !fetchAttendance) continue;
      for (let start = 0; start < Math.max(1, changed.length); start += 4) {
        const batch = changed.slice(start, start + 4);
        const detail = await this.read<CourseDetail>("get_home_course_details", {
          course_id: course.id, assignment_ids: batch.map(({ id }) => id),
          include_stats: start === 0 && fetchStats, include_attendance: start === 0 && fetchAttendance,
        });
        if (!detail) continue;
        for (const item of detail.assignments) {
          const marker = batch.find(({ id }) => id === item.id);
          if (marker && (item.signature === undefined || item.signature === marker.signature)) {
            details[item.id] = { ...item, signature: marker.signature };
          }
        }
        if (detail.stats) {
          const counts = { ...record.stats?.counts };
          for (const [kind, count] of Object.entries(detail.stats.counts)) if (count != null) counts[kind] = count;
          record.stats = { ...detail.stats, counts, attendance: detail.stats.attendance ?? record.stats?.attendance };
          const statsComplete = !fetchStats || Object.values(detail.stats.counts).every((count) => count != null);
          const attendanceComplete = !fetchAttendance || !!detail.stats.attendance;
          if (start === 0 && fetchStats && statsComplete) record.statsSignature = record.index.signature;
          if (detail.stats.attendance) record.attendanceAt = Date.now();
          if (start === 0 && fetchStats) record.retryStatsAfter = statsComplete ? undefined : Date.now() + attendanceRefresh;
          if (start === 0 && fetchAttendance) record.retryAttendanceAfter = attendanceComplete ? undefined : Date.now() + attendanceRefresh;
        }
        this.commit();
      }
    }
    // Publish assignment lists and their deadlines together, including to the on-disk cache.
    if (this.stopped || this.error?.status === "login_required") return;
    for (const course of this.roster.courses) {
      const update = assignmentUpdates.get(course.id);
      if (!update) continue;
      const { index, details } = update;
      const record = this.saved.courses[course.id];
      const previous = record.index.assignments;
      const previousById = new Map(previous?.map((item) => [item.id, item]));
      if (index.some(({ id, signature }) => details[id]?.signature !== signature)) complete = false;
      if (previous) this.recordChanges(course, "assignment", index.filter((item) => {
        const old = previousById.get(item.id);
        return !old || old.title !== item.title || old.submitted === item.submitted &&
          record.details[item.id]?.signature !== item.signature && details[item.id]?.signature === item.signature;
      }));
      record.index.assignments = index;
      record.details = Object.fromEntries(index.flatMap(({ id }) => details[id] ? [[id, details[id]]] : []));
    }
    if (complete) {
      this.saved.checkedAt = Date.now();
      this.error = undefined;
    } else this.error = { status: "error", message: "일부 학습 정보를 갱신하지 못했어요. 마지막으로 확인한 내용을 표시해요." };
    this.commit();
    for (const change of this.saved.changes) {
      if (change.kind !== "notice" || !checkedCourses.has(change.courseId) ||
          !this.saved.courses[change.courseId]?.index.notices.some(({ id }) => id === change.id)) continue;
      const key = `course-notice:${change.courseId}:${change.id}:${change.changedAt}`;
      if (this.cache.get(key)) continue;
      const detail = await this.read<CourseNoticeDetail>("get_course_notice", {
        course_id: change.courseId, notice_id: change.id,
      });
      if (detail) this.cache.set(key, detail);
    }
    const stored = this.saved.timetable;
    if (timetable && stored && !stored.roomsChecked && stored.data.entries.some(({ room }) => !room)) {
      const enriched = await this.read<CourseTimetable>("get_course_timetable", { on_date: today, include_rooms: true });
      if (enriched) {
        stored.roomsChecked = true;
        const entries = enriched.entries.map((entry) => {
          const old = stored.data.entries.find((candidate) => candidate.course_id === entry.course_id &&
            candidate.date === entry.date && candidate.start_time === entry.start_time && candidate.end_time === entry.end_time);
          return !entry.room && old?.room ? { ...entry, room: old.room, room_source: old.room_source } : entry;
        });
        stored.data = { ...enriched, entries };
        this.timetable = stored.data;
        this.commit();
      }
    }
  }

  private recordChanges(course: CourseRoster["courses"][number], kind: HomeSnapshot["changes"][number]["kind"],
    items: { id: string; title: string }[]) {
    if (!items.length) return;
    const changedAt = Date.now();
    const changes = items.map(({ id, title }) => ({ kind, id, title, courseId: course.id, courseName: course.name, changedAt }));
    const key = (item: HomeSnapshot["changes"][number]) => [item.kind, item.courseId, item.id].join(":");
    const changed = new Set(changes.map(key));
    this.saved.changes = [...changes, ...this.saved.changes.filter((old) => !changed.has(key(old)))].slice(0, 30);
  }
}

export { empty as emptyHome };
