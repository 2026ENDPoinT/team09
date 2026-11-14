import { join } from "node:path";
import {
  campusNoticeBoards, campusNoticeKey, isSchoolCampusNoticeBoard,
  type CampusNotice, type CampusNoticeBoard, type CampusNoticeDetail, type CampusNoticeError,
  type CampusNoticeIndexEntry, type CampusNoticeIndexSnapshot, type CampusNoticePage,
} from "../shared/campus-notices.js";
import { departmentNoticeSource } from "../shared/seoultech-department-notices.js";
import { classifyCampusNotice } from "../shared/campus-notice-tags.js";
import { SCREEN_FRESHNESS_MS } from "../shared/screen-freshness.js";
import { AccountScreenCache } from "./account-screen-cache.js";

const schoolBoards = Object.keys(campusNoticeBoards) as CampusNoticeBoard[];
const listFreshness = SCREEN_FRESHNESS_MS;
const detailFreshness = 24 * 60 * 60_000;
const maxBrowsedPages = 15;
const maxRowsPerSlice = 90;
const maxDetails = 400;
const maxDetailBytes = 10 * 1024 * 1024;
const cacheKey = "campus-notice-index-v1";
const pageKey = (board: CampusNoticeBoard, page: number) => `${board}:${page}`;
const indexError: CampusNoticeError = { status: "error", message: "공지 자료를 불러오지 못했어요." };

type Page = { startPage: number; data: CampusNoticePage; checkedAt: number };
type Detail = { detail: CampusNoticeDetail; checkedAt: number; signature: string };
type SavedIndex = { pages: Page[]; details: Detail[] };
type NoticeLocation = Pick<CampusNotice, "board" | "board_id" | "id">;
type ReadPage = (board: CampusNoticeBoard, startPage: number, background: boolean) => Promise<CampusNoticePage | CampusNoticeError>;
type ReadDetail = (notice: NoticeLocation, background: boolean) => Promise<CampusNoticeDetail | CampusNoticeError>;
type StoredDetail = Detail & { tags: CampusNoticeIndexEntry["tags"]; bytes: number };

function signature({ title, published_at, has_attachments }: Pick<CampusNotice, "title" | "published_at" | "has_attachments">) {
  return JSON.stringify([title, published_at, has_attachments]);
}

export class CampusNoticeIndex {
  private readonly pages = new Map<string, Page>();
  private readonly details = new Map<string, StoredDetail>();
  private readonly failures = new Map<string, number>();
  private readonly failedBoards = new Set<CampusNoticeBoard>();
  private readonly disk?: AccountScreenCache;
  private readonly ready?: Promise<void>;
  private revision = 0;
  private active = false;
  private stopped = false;
  private loading = false;
  private headRefresh?: Promise<void>;
  private queuedRefresh = false;
  private queuedForce = false;
  private scanning?: Promise<void>;
  private writeTimer?: ReturnType<typeof setTimeout>;
  private detailBytes = 0;
  private boards: readonly CampusNoticeBoard[];

  constructor(private readonly readPage: ReadPage, private readonly readDetail: ReadDetail, directory?: string,
    private readonly now = Date.now, departmentScope = false) {
    this.boards = departmentScope ? [] : schoolBoards;
    const validBoard = departmentScope ? departmentNoticeSource : isSchoolCampusNoticeBoard;
    if (directory) this.disk = new AccountScreenCache(join(directory, departmentScope ? "department-notices" : "campus-notices"));
    this.ready = this.disk?.ready.then(() => {
      const saved = this.disk?.get<SavedIndex>(cacheKey);
      for (const page of Array.isArray(saved?.pages) ? saved.pages : []) {
        if (!page?.data || !validBoard(page.data.board) || !Array.isArray(page.data.notices) ||
            !Number.isSafeInteger(page.startPage) || page.startPage < 1 || !Number.isFinite(page.checkedAt)) continue;
        this.rememberPage(page.data, page.startPage, page.checkedAt);
      }
      for (const entry of Array.isArray(saved?.details) ? saved.details : []) {
        const detail = entry?.detail;
        if (!detail || !validBoard(detail.board) || typeof detail.content !== "string" || typeof detail.title !== "string" ||
            typeof entry.signature !== "string" || !Number.isFinite(entry.checkedAt)) continue;
        this.rememberDetail(entry);
      }
      this.revision++;
    });
  }

  async snapshot(afterRevision?: number, boards = this.boards): Promise<CampusNoticeIndexSnapshot | null> {
    await this.ready;
    const current = boards.length === this.boards.length && boards.every((board, index) => board === this.boards[index]);
    if (current && afterRevision === this.revision) return null;
    const notices = [...this.notices(boards).values()];
    const entries: CampusNoticeIndexSnapshot["entries"] = {};
    for (const notice of notices) {
      const key = campusNoticeKey(notice);
      const cached = this.details.get(key);
      if (cached && cached.signature === signature(notice)) entries[key] = { detail: cached.detail, tags: cached.tags };
    }
    const pages: CampusNoticeIndexSnapshot["pages"] = {};
    for (const board of boards) {
      const first = this.pages.get(pageKey(board, 1));
      if (!first) continue;
      let last = first;
      let listedAt = first.checkedAt;
      for (const page of this.pages.values()) {
        if (page.data.board !== board) continue;
        if (page.startPage > last.startPage) last = page;
        if (isSchoolCampusNoticeBoard(board)) listedAt = Math.min(listedAt, page.checkedAt);
      }
      pages[board] = { lastPage: last.startPage, nextPage: last.data.next_page, listedAt };
    }
    return {
      revision: this.revision, notices, entries, pages,
      listedBoards: boards.filter((board) => !!pages[board]), loading: current && this.loading,
      partial: boards.some((board) => this.failedBoards.has(board)) || notices.some((notice) => this.failures.has(campusNoticeKey(notice))) ||
        this.active && current && !this.loading && (boards.some((board) => !pages[board]) || notices.some((notice) => !entries[campusNoticeKey(notice)])),
    };
  }

  async list(board: CampusNoticeBoard, startPage: number, force = false, background = false) {
    if (this.ready) await this.ready;
    if (this.stopped) return indexError;
    const cached = this.pages.get(pageKey(board, startPage));
    if (!force && cached && this.now() - cached.checkedAt < listFreshness) return cached.data;
    const data = await this.readPage(board, startPage, background).catch(() => indexError);
    if (this.stopped) return indexError;
    if ("status" in data || data.board !== board || !Array.isArray(data.notices)) {
      if (startPage === 1 && !this.failedBoards.has(board)) {
        this.failedBoards.add(board);
        this.revision++;
      }
      return "status" in data ? data : indexError;
    }
    this.rememberPage(data, startPage, this.now());
    if (startPage === 1) this.failedBoards.delete(board);
    this.changed();
    if (this.active) this.startScan();
    return data;
  }

  async detail(notice: NoticeLocation, background = false): Promise<CampusNoticeDetail | CampusNoticeError> {
    if (this.ready) await this.ready;
    if (this.stopped) return indexError;
    const key = campusNoticeKey(notice);
    const cached = this.details.get(key);
    const listed = this.notices().get(key);
    const expected = listed && signature(listed);
    if (cached && (!expected || cached.signature === expected) && this.now() - cached.checkedAt < detailFreshness) {
      return cached.detail;
    }
    const detail = await this.readDetail(notice, background).catch(() => indexError);
    if (this.stopped) return indexError;
    if ("status" in detail || campusNoticeKey(detail) !== key || typeof detail.content !== "string") {
      if (!this.failures.has(key)) this.revision++;
      this.failures.set(key, this.now());
      return (!background && cached && (!expected || cached.signature === expected)) ? cached.detail :
        "status" in detail ? detail : indexError;
    }
    this.failures.delete(key);
    this.rememberDetail({ detail, checkedAt: this.now(), signature: expected ?? signature(detail) });
    this.changed();
    return detail;
  }

  sync(force = false, boards = this.boards) {
    if (this.stopped) return;
    const switched = boards.length !== this.boards.length || boards.some((board, index) => board !== this.boards[index]);
    if (switched) {
      this.boards = boards;
      this.revision++;
    }
    this.active = true;
    if (this.headRefresh) {
      this.queuedRefresh ||= switched || force;
      this.queuedForce ||= force;
      return;
    }
    this.setLoading(true);
    this.headRefresh = Promise.allSettled(boards.map((board) => this.list(board, 1, force, true))).then(() => {}).finally(() => {
      this.headRefresh = undefined;
      if (this.stopped) return;
      if (this.queuedRefresh) {
        const force = this.queuedForce;
        this.queuedRefresh = false;
        this.queuedForce = false;
        this.sync(force);
      } else {
        this.startScan();
      }
    });
  }

  async stop() {
    this.stopped = true;
    clearTimeout(this.writeTimer);
    this.writeTimer = undefined;
    await this.ready;
    this.save();
    await this.disk?.flush();
  }

  private rememberPage(data: CampusNoticePage, startPage: number, checkedAt: number) {
    const key = pageKey(data.board, startPage);
    const notices = data.notices.filter((notice) => notice && notice.board === data.board &&
      /^\d{1,20}$/.test(notice.board_id) && /^\d{1,20}$/.test(notice.id) && typeof notice.title === "string").slice(0, maxRowsPerSlice);
    const next_page = Number.isSafeInteger(data.next_page) && data.next_page! > startPage ? data.next_page : null;
    this.pages.delete(key);
    this.pages.set(key, { startPage, data: { ...data, notices, next_page }, checkedAt });
    if (next_page == null) for (const [otherKey, other] of this.pages) {
      if (other.data.board === data.board && other.startPage > startPage) this.pages.delete(otherKey);
    }
    const browsed = [...this.pages].filter(([, page]) => page.startPage !== 1);
    for (const [expired] of browsed.slice(0, Math.max(0, browsed.length - maxBrowsedPages))) this.pages.delete(expired);
  }

  private rememberDetail(entry: Detail) {
    const key = campusNoticeKey(entry.detail);
    const bytes = Buffer.byteLength(JSON.stringify(entry));
    if (bytes > maxDetailBytes) return;
    this.detailBytes -= this.details.get(key)?.bytes ?? 0;
    this.details.delete(key);
    this.details.set(key, { ...entry, tags: classifyCampusNotice(entry.detail.title, entry.detail.content), bytes });
    this.detailBytes += bytes;
    while (this.details.size > maxDetails || this.detailBytes > maxDetailBytes) {
      const oldest = this.details.entries().next().value;
      if (!oldest) break;
      this.details.delete(oldest[0]);
      this.detailBytes -= oldest[1].bytes;
    }
  }

  private notices(boards?: readonly CampusNoticeBoard[]) {
    const notices = new Map<string, CampusNotice>();
    const pages = [...this.pages.values()].sort((a, b) => a.startPage - b.startPage);
    for (const { data } of pages) {
      if (boards && !boards.includes(data.board)) continue;
      for (const notice of data.notices) {
        const key = campusNoticeKey(notice);
        if (!notices.has(key)) notices.set(key, notice);
      }
    }
    return notices;
  }

  private startScan() {
    if (this.scanning || this.headRefresh || this.stopped) return;
    this.setLoading(true);
    this.scanning = this.scan().finally(() => {
      this.scanning = undefined;
      if (!this.headRefresh) this.setLoading(false);
    });
  }

  private async scan() {
    const visited = new Set<string>();
    let nextBoard = 0;
    const known = this.notices();
    for (const key of this.failures.keys()) if (!known.has(key)) this.failures.delete(key);
    // Pull one detail at a time. The shared campus lane can serve foreground
    // article/list requests between background reads. Make every board usable early.
    while (!this.stopped && !this.headRefresh) {
      const boards = this.boards;
      const notices = this.notices(boards);
      const pending = new Map<CampusNoticeBoard, [string, CampusNotice]>();
      for (const [key, notice] of notices) {
        if (visited.has(key) || pending.has(notice.board)) continue;
        const saved = this.details.get(key);
        const age = this.now() - (saved?.checkedAt ?? 0);
        const failedAt = this.failures.get(key);
        if ((failedAt == null || this.now() - failedAt >= listFreshness) &&
            (!saved || saved.signature !== signature(notice) || age >= detailFreshness)) {
          pending.set(notice.board, [key, notice]);
        }
      }
      if (!pending.size) return;
      nextBoard %= boards.length;
      while (!pending.has(boards[nextBoard])) nextBoard = (nextBoard + 1) % boards.length;
      const [key, notice] = pending.get(boards[nextBoard])!;
      nextBoard = (nextBoard + 1) % boards.length;
      visited.add(key);
      await this.detail(notice, true);
    }
  }

  private setLoading(loading: boolean) {
    if (this.loading === loading) return;
    this.loading = loading;
    this.revision++;
  }

  private changed() {
    this.revision++;
    if (!this.disk || this.writeTimer) return;
    this.writeTimer = setTimeout(() => {
      this.writeTimer = undefined;
      this.save();
    }, 2_000);
    this.writeTimer.unref();
  }

  private save() {
    this.disk?.set(cacheKey, {
      pages: [...this.pages.values()],
      details: [...this.details.values()].map(({ detail, checkedAt, signature }) => ({ detail, checkedAt, signature })),
    } satisfies SavedIndex);
  }
}
