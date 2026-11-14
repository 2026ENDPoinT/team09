import type { AccountScreenCache } from "./account-screen-cache.js";
import { BackgroundReadDeferred } from "./lms-access.js";
import type { CourseNoticePage } from "../shared/course-classroom.js";
import { COURSE_NOTICE_BODY_BATCH, type CourseNoticeIndexedBody, type CourseNoticeIndexSnapshot, type IndexedCourseNotice } from "../shared/course-notice-index.js";
import { asKoreanTime } from "../shared/assignment-visibility.js";
import type { CourseNotice, CourseRoster, LmsBridgeError } from "../shared/lms.js";
import { SCREEN_FRESHNESS_MS } from "../shared/screen-freshness.js";

type Course = CourseRoster["courses"][number];
type SavedCourse = { entries: IndexedCourseNotice[] };
type NoticeReader = <T>(tool: string, args: Record<string, unknown>, foreground: () => boolean) => Promise<T | LmsBridgeError>;

const waitUntilIdle = () => new Promise<void>((resolve) => setTimeout(resolve, 1000).unref());
const cacheKey = (courseId: string) => `course-notice-index-v1:${courseId}`;
const sameListing = (before: CourseNotice, after: CourseNotice) => before.title === after.title &&
  before.content === after.content && before.created_at === after.created_at;
const order = ({ notice: a }: IndexedCourseNotice, { notice: b }: IndexedCourseNotice) =>
  (asKoreanTime(b.created_at)?.getTime() ?? 0) - (asKoreanTime(a.created_at)?.getTime() ?? 0);

export class CourseNoticeIndex {
  private readonly byCourse = new Map<string, Map<string, IndexedCourseNotice>>();
  private version = 0;
  private loading = true;
  private partial = false;
  private checkedAt?: number;
  private error?: LmsBridgeError;
  private stopped = false;
  private manual = false;
  private expedite?: () => void;
  private running?: Promise<void>;
  private timer?: ReturnType<typeof setTimeout>;
  private readonly ready: Promise<void>;

  constructor(private readonly courses: Course[], private readonly disk: AccountScreenCache | undefined,
    private readonly read: NoticeReader, private readonly beforeStart: Promise<unknown>,
    private readonly interval = SCREEN_FRESHNESS_MS) {
    this.ready = (disk?.ready ?? Promise.resolve()).then(() => {
      if (this.stopped) return;
      for (const course of courses) {
        const saved = disk?.get<SavedCourse>(cacheKey(course.id));
        const entries = Array.isArray(saved?.entries) ? saved.entries : [];
        this.byCourse.set(course.id, new Map(entries.map(({ notice, body }) => [notice.id, {
          notice: { ...notice, course_id: course.id, course_name: course.name }, body,
        }])));
      }
      this.loading = courses.length > 0;
      this.version++;
    });
  }

  async snapshot(afterVersion?: number): Promise<CourseNoticeIndexSnapshot | null> {
    await this.ready;
    if (afterVersion === this.version) return null;
    return {
      version: this.version, courses: this.courses.map(({ id, name, category }) => ({ id, name, category })),
      entries: this.error?.status === "login_required" ? [] : [...this.byCourse.values()].flatMap((entries) => [...entries.values()]).sort(order),
      loading: this.loading, partial: this.partial, checkedAt: this.checkedAt, error: this.error,
    };
  }

  entry(courseId: string, noticeId: string) {
    return this.error?.status === "login_required" ? undefined : this.byCourse.get(courseId)?.get(noticeId);
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
    this.expedite?.();
  }

  refresh(manual = false): Promise<void> {
    if (!this.courses.length || this.stopped || this.error?.status === "login_required") return Promise.resolve();
    this.manual ||= manual;
    if (manual) this.expedite?.();
    if (this.running) return this.running;
    clearTimeout(this.timer);
    this.loading = true;
    this.version++;
    const run = this.ready.then(async () => {
      if (!this.manual && !this.stopped) {
        // Start after the home loads, unless the user requests a refresh first.
        const expedited = new Promise<void>((resolve) => { this.expedite = resolve; });
        await Promise.race([this.beforeStart, expedited]);
        this.expedite = undefined;
      }
      if (this.stopped) return;
      this.partial = false;
      for (const course of this.courses) {
        if (this.stopped || this.error?.status === "login_required") break;
        await this.syncCourse(course);
      }
      if (!this.partial && !this.error && !this.stopped) this.checkedAt = Date.now();
    }).catch(() => { this.partial = true; }).finally(() => {
      this.manual = false;
      this.running = undefined;
      this.loading = false;
      this.version++;
      if (!this.stopped && this.error?.status !== "login_required") {
        this.timer = setTimeout(() => void this.refresh(), this.interval);
        this.timer.unref();
      }
    });
    this.running = run;
    return run;
  }

  private async request<T>(tool: string, args: Record<string, unknown>): Promise<T | undefined> {
    while (!this.stopped && !this.error) {
      try {
        const result = await this.read<T>(tool, args, () => this.manual);
        if (this.stopped) return;
        if (result && typeof result === "object" && "status" in result) {
          const error = result as LmsBridgeError;
          if (error.status === "login_required") this.error = error;
          else this.partial = true;
          return;
        }
        return result as T;
      } catch (error) {
        if (this.stopped) return;
        if (!(error instanceof BackgroundReadDeferred)) { this.partial = true; return; }
        await waitUntilIdle();
      }
    }
  }

  private async syncCourse(course: Course) {
    const entries = this.byCourse.get(course.id)!;
    const seen = new Set<string>();
    let complete = false;
    let dirty = false;

    for (let page = 1; !this.stopped; page++) {
      const result = await this.request<CourseNoticePage>("get_course_notice_page", { course_id: course.id, page });
      if (!result) break;
      const missing: string[] = [];
      for (const notice of result.notices) {
        if (seen.has(notice.id)) continue;
        seen.add(notice.id);
        const item = { ...notice, course_id: course.id, course_name: course.name, page };
        const previous = entries.get(item.id);
        const current = previous && sameListing(previous.notice, item);
        const body = current ? previous.body : undefined;
        if (!current || previous.notice.page !== page) {
          entries.set(item.id, { notice: item, body });
          dirty = true;
          this.version++;
        }
        if (!body) missing.push(item.id);
      }
      for (let start = 0; start < missing.length; start += COURSE_NOTICE_BODY_BATCH) {
        const ids = missing.slice(start, start + COURSE_NOTICE_BODY_BATCH);
        const result = await this.request<{ bodies: CourseNoticeIndexedBody[] }>("get_course_notice_bodies",
          { course_id: course.id, page, notice_ids: ids });
        if (!result) break;
        const bodies = new Map(result.bodies.map((body) => [body.id, body]));
        for (const id of ids) {
          const body = bodies.get(id);
          if (body) {
            entries.set(id, { notice: entries.get(id)!.notice, body });
            dirty = true;
            this.version++;
          } else this.partial = true;
        }
      }
      if (!result.has_next || this.error) {
        complete = !result.partial && !this.error;
        if (result.partial) this.partial = true;
        break;
      }
    }
    if (this.stopped) return;
    if (complete) {
      for (const id of entries.keys()) if (!seen.has(id)) dirty = entries.delete(id) || dirty;
    }
    if (dirty) {
      this.disk?.set(cacheKey(course.id), { entries: [...entries.values()] } satisfies SavedCourse);
      this.version++;
    }
  }
}
