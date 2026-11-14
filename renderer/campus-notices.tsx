import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";
import {
  campusNoticeBoardLabel, campusNoticeBoards, campusNoticeKey, campusNoticeLink, isSchoolCampusNoticeBoard, noticeWebLink,
  type CampusNotice, type CampusNoticeBoard, type CampusNoticeDetail, type CampusNoticeIndexSnapshot,
  type CampusNoticeScope, type SchoolCampusNoticeBoard,
} from "../shared/campus-notices.js";
import { campusNoticeTags, type CampusNoticeTag } from "../shared/campus-notice-tags.js";
import { campusNoticeApplication } from "../shared/campus-notice-application.js";
import { departmentNoticeSources } from "../shared/seoultech-department-notices.js";
import type { StudentPreferences } from "../shared/student-preferences.js";
import refreshIcon from "./assets/notice-timeline/refresh.svg?no-inline";
import originalIcon from "./assets/notice-timeline/original.svg?no-inline";
import calendarIcon from "./assets/notice-timeline/calendar.svg?no-inline";
import attachmentIcon from "./assets/notice-timeline/attachment.svg?no-inline";
import attachmentOriginalIcon from "./assets/notice-timeline/attachment-original.svg?no-inline";
import pinIcon from "./assets/notice-timeline/pin.svg?no-inline";
import disclosureIcon from "./assets/notice-timeline/disclosure.svg?no-inline";
import dateIcon from "./assets/notice-timeline/date.svg?no-inline";
import selectedDateIcon from "./assets/notice-timeline/selected-date.svg?no-inline";
import moreIcon from "./assets/notice-timeline/more.svg?no-inline";
import searchIcon from "./assets/notice-timeline/search.svg?no-inline";
import boardCheckIcon from "./assets/notice-timeline/board-check.svg?no-inline";
import { NoticeFilterButton } from "./notice-filter-button.js";
import { normalizeNoticeQuery, noticeBodyExcerpt, useCampusNoticeIndex } from "./use-notice-search.js";
import { useVisibleRefresh } from "./use-visible-refresh.js";
import { PaneSplitter } from "./workspace-splitter.js";
import "./campus-notices.css";

const schoolBoards = Object.keys(campusNoticeBoards) as SchoolCampusNoticeBoard[];
const topics = Object.keys(campusNoticeTags) as CampusNoticeTag[];
const splitThreshold = 640;
const minListWidth = 265;
const minReaderWidth = 320;
const splitterWidth = 10;

type BoardState = { loading: boolean; error: string | null };
type NoticeTab = SchoolCampusNoticeBoard | "all" | "affiliation";
type NoticeResult = { key: string; notice: CampusNotice; detail?: CampusNoticeDetail; tags: CampusNoticeTag[]; excerpt?: string };
const noticeDay = new Intl.DateTimeFormat("ko-KR", { day: "numeric", weekday: "short", timeZone: "UTC" });
const noticeMonth = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long", timeZone: "UTC" });
const noticeDate = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });

function publishedDay(value: string | null): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("9999-")) return "";
  const day = new Date(value);
  return Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === value ? value : "";
}

function boardLabel(board: NoticeTab) {
  if (board === "all") return "전체";
  if (board === "affiliation") return "학과 공지";
  return campusNoticeBoards[board];
}

function NoticeMeta({ notice, sourceLabel }: { notice: Pick<CampusNotice, "published_at" | "department" | "has_attachments">; sourceLabel?: string }) {
  return (
    <span className="notice-meta">
      {sourceLabel && <span>{sourceLabel}</span>}
      {notice.published_at && <time>{notice.published_at}</time>}
      {notice.department && <span>{notice.department}</span>}
      {notice.has_attachments && <span>첨부파일</span>}
    </span>
  );
}

function NoticeLink({ url, children, onError, className, label, notice }: {
  url: string;
  children: ReactNode;
  onError: () => void;
  className?: string;
  label?: string;
  notice?: Pick<CampusNotice, "board" | "board_id" | "id">;
}) {
  function open(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    void window.ast.openCampusNoticeLink(url, notice).then((opened) => {
      if (!opened) onError();
    }, onError);
  }
  return (
    <a href={url} className={className} aria-label={label} onClick={open} onAuxClick={(event) => {
      if (event.button === 1) open(event);
    }}>
      {children}
    </a>
  );
}

export function NoticeDetail({ notice, initialDetail, sourceLabel, onDismiss, inline = false, tags = [] }: {
  notice: CampusNotice; initialDetail?: CampusNoticeDetail; sourceLabel?: string; onDismiss: () => void;
  inline?: boolean; tags?: CampusNoticeTag[];
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [detail, setDetail] = useState<CampusNoticeDetail | null>(initialDetail ?? null);
  const [error, setError] = useState<string | null>(null);
  const [linkError, setLinkError] = useState(false);
  const [attachmentLinkError, setAttachmentLinkError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
  }, []);

  useEffect(() => {
    if (initialDetail && attempt === 0) return;
    let active = true;
    setError(null);
    void window.ast.getCampusNotice(notice.board, notice.board_id, notice.id).then((result) => {
      if (!active) return;
      if ("status" in result) setError(result.message);
      else setDetail(result);
    }, () => {
      if (active) setError("공지 본문을 불러오지 못했어요. 다시 시도해 주세요.");
    });
    return () => { active = false; };
  }, [notice, initialDetail, attempt]);

  const resolved = initialDetail ?? detail;
  const item = resolved ?? notice;
  const original = campusNoticeLink(item.url) ?? campusNoticeLink(notice.url);
  const images = (resolved?.images ?? []).flatMap((image) => {
    const url = campusNoticeLink(image.url);
    return url && /\.(?:jpe?g|png|gif|webp|bmp|tiff?|avif)$/i.test(url.pathname)
      ? [{ id: image.id, url: url.href, name: image.alt.trim() || "공지 본문 이미지" }]
      : [];
  });
  const content = resolved?.content.trim();
  const attachments = resolved?.attachments ?? [];
  const attachmentList = <><h3>첨부파일</h3><ul>{attachments.map((file) => <li key={file.id}>{file.name}</li>)}</ul></>;
  const showLinkError = () => setLinkError(true);
  const body = error ? (
    <div className="notice-feedback">
      <p role="status">{error}</p>
      <button className="button" type="button" onClick={() => setAttempt((value) => value + 1)}>다시 시도</button>
    </div>
  ) : resolved ? (
    (content || images.length === 0) && (
      <div className="notice-content-text">{content || "표시할 텍스트 본문이 없어요. 원문을 확인해 주세요."}</div>
    )
  ) : <p role="status">공지 본문을 불러오고 있어요.</p>;
  const bodyImages = images.length > 0 && (
    <section className="notice-resources" aria-label="본문 이미지">
      <h3>본문 이미지</h3>
      <ul>{images.map((image) => (
        <li key={image.id}>
          <NoticeLink url={image.url} onError={showLinkError}>
            <img className="notice-body-image" src={image.url} alt={image.name} loading="lazy" referrerPolicy="no-referrer" />
          </NoticeLink>
        </li>
      ))}</ul>
    </section>
  );
  const links = (resolved?.links ?? []).flatMap((link) => {
    const url = noticeWebLink(link.url);
    return url ? [{ url: url.href, title: link.text.trim() || url.hostname }] : [];
  });
  const noticeLinks = links.length > 0 && (
    <section className="notice-resources" aria-label="본문 링크">
      <h3>본문 링크</h3>
      <ul>{links.map(({ url, title }) => <li key={url}>
        <NoticeLink url={url} notice={{ board: notice.board, board_id: notice.board_id, id: notice.id }} onError={showLinkError}>{title}</NoticeLink>
      </li>)}</ul>
    </section>
  );

  if (inline) {
    const day = publishedDay(item.published_at) || publishedDay(notice.published_at);
    const { deadline, audience } = content ? campusNoticeApplication(content) : {};
    return (
      <article className="notice-reading-pane" aria-labelledby="notice-reading-title">
        <button className="button notice-back" type="button" onClick={onDismiss}>목록으로</button>
        <div className="notice-reading-top">
          <div className="notice-reading-source">
            {tags.map((tag) => <span className="notice-reading-topic" key={tag} data-topic={tag}>{campusNoticeTags[tag]}</span>)}
            <span>{sourceLabel ?? campusNoticeBoardLabel(notice.board)}</span>
          </div>
          {original && <NoticeLink className="button notice-reading-original" url={original.href} onError={showLinkError}>
            원문 열기 <img src={originalIcon} alt="" />
          </NoticeLink>}
        </div>
        <h2 id="notice-reading-title">{item.title}</h2>
        <div className="notice-reading-meta">
          {day && <time dateTime={day}>{noticeDate.format(new Date(day))} 게시</time>}
          {item.department && <span>{item.department}</span>}
          {attachments.length > 0 ? <span>첨부 {attachments.length}개</span> : notice.has_attachments && <span>첨부파일</span>}
        </div>
        {linkError && <p className="notice-inline-error" role="status">브라우저에서 링크를 열지 못했어요.</p>}
        {(deadline || audience) && (
          <dl className="notice-application">
            {deadline && <div className="notice-application-deadline"><img src={calendarIcon} alt="" />
              <dt>신청 마감</dt><dd>{deadline}</dd>
            </div>}
            {audience && <div><dt>지원 대상</dt><dd>{audience}</dd></div>}
          </dl>
        )}
        <section className="notice-reading-body" aria-labelledby="notice-body-title" aria-busy={!resolved && !error}>
          <h3 id="notice-body-title">본문 미리보기</h3>
          {body}
        </section>
        {bodyImages}
        {noticeLinks}
        {attachments.length > 0 && <section className="notice-reading-files" aria-label="첨부파일">
          <h3>첨부파일 {attachments.length}개</h3>
          <ul>{attachments.map((file) => <li key={file.id}>
            {original ? <NoticeLink url={original.href} label={`${file.name}, 원문에서 받기`} onError={() => setAttachmentLinkError(true)}>
              <img src={attachmentIcon} alt="" /><span>{file.name}</span><img src={attachmentOriginalIcon} alt="" />
            </NoticeLink> : <span>{file.name}</span>}
          </li>)}</ul>
          {original && <p>첨부파일은 학교 홈페이지 원문에서 받을 수 있어요.</p>}
          {attachmentLinkError && <p className="notice-inline-error" role="status">브라우저에서 링크를 열지 못했어요.</p>}
        </section>}
      </article>
    );
  }

  return (
    <dialog ref={dialog} className="notice-dialog" aria-labelledby="notice-detail-title" onClose={onDismiss}>
      <div className="notice-dialog-top">
        <span>{sourceLabel ?? campusNoticeBoardLabel(notice.board)}</span>
        <button className="button" type="button" onClick={() => dialog.current?.close()}>닫기</button>
      </div>
      <div className="notice-dialog-content">
        <h2 id="notice-detail-title">{item.title}</h2>
        <NoticeMeta notice={item} />
        {original && (
          <NoticeLink className="button notice-original" url={original.href} onError={showLinkError}>
            원문 보기 <span aria-hidden="true">↗</span>
          </NoticeLink>
        )}
        {linkError && <p className="notice-inline-error" role="status">브라우저에서 링크를 열지 못했어요.</p>}
        <div className="notice-detail-body" aria-busy={!resolved && !error}>{body}</div>
        {bodyImages}
        {noticeLinks}
        {attachments.length > 0 && (
          <section className="notice-resources" aria-label="첨부파일">
            {original ? (
              <NoticeLink className="notice-attachments-link" url={original.href} label="학교 홈페이지에서 첨부파일 받기"
                onError={() => setAttachmentLinkError(true)}>
                {attachmentList}
                <span>학교 홈페이지에서 첨부파일 받기 <span aria-hidden="true">↗</span></span>
              </NoticeLink>
            ) : attachmentList}
            {attachmentLinkError && <p className="notice-inline-error" role="status">브라우저에서 링크를 열지 못했어요.</p>}
          </section>
        )}
      </div>
    </dialog>
  );
}

export function CampusNotices({ visible, preferences }: { visible: boolean; preferences?: StudentPreferences | null }) {
  const [board, setBoard] = useState<NoticeTab>("all");
  const [sourceId, setSourceId] = useState<CampusNoticeBoard>();
  const [states, setStates] = useState<Partial<Record<CampusNoticeBoard, BoardState>>>({});
  const [selectedKey, setSelectedKey] = useState<string>();
  const [boardWidth, setBoardWidth] = useState(0);
  const [preferredListWidth, setPreferredListWidth] = useState<number>();
  const [loadingMore, setLoadingMore] = useState(false);
  const [selectedTags, setSelectedTags] = useState<CampusNoticeTag[]>([]);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [pageIndices, setPageIndices] = useState<Partial<Record<CampusNoticeScope, CampusNoticeIndexSnapshot>>>({});
  const refreshRequest = useRef<Promise<void> | null>(null);
  const composing = useRef(false);
  const boardElement = useRef<HTMLElement>(null);
  const lastRow = useRef<HTMLButtonElement>(null);
  const wide = boardWidth >= splitThreshold;
  const maxListWidth = Math.max(minListWidth, Math.floor(boardWidth - splitterWidth - minReaderWidth));
  const clampListWidth = (width: number) => Math.max(minListWidth, Math.min(maxListWidth, width));
  const listWidth = clampListWidth(preferredListWidth ?? Math.round(boardWidth * 0.345));
  const splitStyle = wide ? {
    "--notice-list-width": `${listWidth}px`,
    "--notice-splitter-width": `${splitterWidth}px`,
  } as CSSProperties : undefined;
  const departmentId = preferences?.departmentId;
  const { college, department } = departmentNoticeSources(departmentId);
  const sources = [college, department].filter((source) => source !== undefined);
  const activeSource = sources.find((source) => source.id === sourceId) ?? department ?? college;
  const affiliation = board === "affiliation";
  const scope = affiliation ? "department" : "school";
  const activeBoard = affiliation ? activeSource?.id : board === "all" ? undefined : board;
  const polledIndex = useCampusNoticeIndex(visible && (!affiliation || Boolean(activeSource)), scope);
  const pageIndex = pageIndices[scope];
  const index = pageIndex && pageIndex.revision > polledIndex.revision ? pageIndex : polledIndex;
  const pending = useRef(new Map<CampusNoticeBoard, { background: boolean; finished: Promise<void> }>());
  const state = activeBoard ? states[activeBoard] : undefined;
  const indexedPage = activeBoard ? index.pages[activeBoard] : undefined;
  const nextPage = indexedPage?.nextPage;
  const morePages = activeBoard
    ? nextPage == null ? [] : [{ board: activeBoard, page: nextPage }]
    : board === "all" ? schoolBoards.flatMap((board) => {
      const page = index.pages[board]?.nextPage;
      return page == null ? [] : [{ board, page }];
    }) : [];

  const load = useCallback(async (requestedBoard: CampusNoticeBoard, startPage: number, refresh = false, background = false, throughPage = startPage) => {
    const existing = pending.current.get(requestedBoard);
    if (existing) {
      if (background || !existing.background) return;
      await existing.finished;
      if (pending.current.has(requestedBoard)) return;
    }
    let finish!: () => void;
    const finished = new Promise<void>((resolve) => { finish = resolve; });
    pending.current.set(requestedBoard, { background, finished });
    const update = (next: Partial<BoardState>) => setStates((current) => ({
      ...current,
      [requestedBoard]: { loading: false, error: null, ...current[requestedBoard], ...next },
    }));
    if (!background) update({ loading: true, error: null });

    try {
      let page = startPage;
      while (true) {
        const result = await window.ast.listCampusNotices(requestedBoard, page, refresh);
        if ("status" in result) {
          if (!background) update({ loading: false, error: result.message });
          return;
        }
        const next = result.next_page;
        if (next == null || next <= page || next > throughPage) break;
        page = next;
      }
      const snapshot = await window.ast.getCampusNoticeIndex(undefined, scope);
      if (snapshot) setPageIndices((current) => {
        const previous = current[scope];
        return !previous || snapshot.revision > previous.revision ? { ...current, [scope]: snapshot } : current;
      });
      update({ loading: false, error: null });
    } catch {
      if (!background) update({ loading: false, error: "공지 목록을 불러오지 못했어요. 다시 시도해 주세요." });
    } finally {
      pending.current.delete(requestedBoard);
      finish();
    }
  }, [scope]);

  useEffect(() => {
    if (visible && activeBoard && !state && !indexedPage && !index.loading) void load(activeBoard, 1);
  }, [visible, activeBoard, state, indexedPage, index.loading, load]);

  useVisibleRefresh(visible && Boolean(activeBoard), () => {
    if (activeBoard) void load(activeBoard, 1, true, Boolean(indexedPage), affiliation ? 1 : indexedPage?.lastPage);
  }, indexedPage?.listedAt, activeBoard);
  useVisibleRefresh(visible && board === "all", () => void refreshAll(), 0, "all");

  useEffect(() => {
    const element = boardElement.current;
    if (!visible || !element) return;
    const observer = new ResizeObserver(([entry]) => setBoardWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [visible]);

  const notices = useMemo(() => {
    const items = index.notices.filter((notice) => board === "all" ? isSchoolCampusNoticeBoard(notice.board) : notice.board === activeBoard);
    return [...items].sort((a, b) => publishedDay(b.published_at).localeCompare(publishedDay(a.published_at)));
  }, [activeBoard, board, index.notices]);
  const filtered = query.length > 0 || selectedTags.length > 0;
  const results = useMemo<NoticeResult[]>(() => notices.flatMap((notice) => {
    const key = campusNoticeKey(notice);
    const entry = index.entries[key];
    const tags = entry?.tags ?? [];
    if (selectedTags.length && !selectedTags.some((tag) => tags.includes(tag))) return [];
    const detail = entry?.detail;
    const excerpt = noticeBodyExcerpt(detail?.content, query) ?? noticeBodyExcerpt(notice.preview, query);
    const fields = [notice.title, notice.department, detail?.title, detail?.department];
    if (query && !excerpt && !fields.some((field) => field && normalizeNoticeQuery(field).includes(query))) return [];
    return [{ key, notice, detail, tags: tags.slice(0, 2), excerpt }];
  }), [notices, index.entries, query, selectedTags]);
  const pinned = results.filter(({ notice }) => notice.pinned);
  const days = new Map<string, NoticeResult[]>();
  for (const result of results) {
    if (result.notice.pinned) continue;
    const day = publishedDay(result.notice.published_at);
    const group = days.get(day);
    if (group) group.push(result);
    else days.set(day, [result]);
  }
  const explicitSelection = selectedKey ? results.find(({ key }) => key === selectedKey) : undefined;
  const selection = explicitSelection ?? (wide ? days.values().next().value?.[0] ?? pinned[0] : undefined);
  const showReading = !wide && Boolean(explicitSelection);
  const unavailable = affiliation && !activeSource;
  const scopeRefreshing = board === "all" && refreshing;
  const refreshError = board === "all" && refreshFailed;
  const waitingForList = board === "all" ? !notices.length && (index.revision < 0 && !index.partial || index.loading || scopeRefreshing)
    : !!activeBoard && !indexedPage && !state?.error && !notices.length;
  const loading = Boolean(state?.loading) || waitingForList;
  const checkingBodies = filtered && index.loading;
  const limited = index.partial || refreshError || Boolean(state?.error);
  const emptyMessage = unavailable
    ? departmentId ? "소속 학과의 공지 게시판을 확인하지 못했어요." : "설정에서 소속 학과를 선택해 주세요."
    : state?.error ?? (waitingForList ? "공지 목록을 불러오고 있어요."
      : checkingBodies ? "검색 결과를 확인하고 있어요."
      : filtered ? "확인한 범위에 일치하는 공지가 없어요."
      : limited ? "확인한 범위에 공지가 없어요." : "표시할 공지가 없어요.");

  useEffect(() => {
    if (selectedKey && !explicitSelection) setSelectedKey(undefined);
  }, [selectedKey, explicitSelection]);

  useEffect(() => {
    if (showReading) boardElement.current?.querySelector<HTMLButtonElement>(".notice-back")?.focus();
  }, [showReading]);

  function closeReading() {
    setSelectedKey(undefined);
    requestAnimationFrame(() => lastRow.current?.focus());
  }

  function toggleTag(tag: CampusNoticeTag) {
    setSelectedTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]);
  }

  async function refresh() {
    if (activeBoard) await load(activeBoard, 1, true, false, affiliation ? 1 : indexedPage?.lastPage);
    else if (board === "all") await refreshAll();
  }

  async function refreshAll() {
    if (refreshRequest.current) return refreshRequest.current;
    setRefreshing(true);
    setRefreshFailed(false);
    refreshRequest.current = (async () => {
      try { await window.ast.syncCampusNoticeIndex(true, "school"); }
      catch { setRefreshFailed(true); }
      finally {
        setRefreshing(false);
        refreshRequest.current = null;
      }
    })();
    return refreshRequest.current;
  }

  async function loadOlder() {
    if (loadingMore || !morePages.length) return;
    setLoadingMore(true);
    try { await Promise.all(morePages.map(({ board, page }) => load(board, page))); }
    finally { setLoadingMore(false); }
  }

  function renderNoticeRows(items: NoticeResult[]) {
    return <ul className="notice-list">{items.map(({ key, notice, detail, tags, excerpt }) => {
      const source = affiliation ? activeSource?.label : campusNoticeBoardLabel(notice.board);
      const attachmentCount = detail?.attachments.length ?? 0;
      return <li key={key} className="notice-timeline-card" data-selected={selection?.key === key}>
        {!!tags.length && <div className="notice-row-tags" role="group" aria-label="이 공지의 주제">
          {tags.map((tag) => <button key={tag} className="notice-chip" type="button" data-topic={tag} aria-pressed={selectedTags.includes(tag)}
            onClick={() => toggleTag(tag)}>{campusNoticeTags[tag]}</button>)}
        </div>}
        <button className="notice-row" type="button" aria-current={selection?.key === key ? "true" : undefined}
          onClick={(event) => { lastRow.current = event.currentTarget; setSelectedKey(key); }}>
          <strong>{notice.title}</strong>
          <span className="notice-row-meta">{[source, attachmentCount ? `첨부 ${attachmentCount}개` : notice.has_attachments ? "첨부파일" : ""]
            .filter(Boolean).join(" · ")}</span>
          {excerpt && <span className="notice-result-excerpt">{excerpt}</span>}
        </button>
      </li>;
    })}</ul>;
  }

  return (
    <section className="campus-notices" aria-labelledby="campus-notice-title">
      <div className="intro">
        <h1 id="campus-notice-title">대학생활 공지</h1>
        <button className="button notice-refresh" type="button" disabled={unavailable || loading || scopeRefreshing} onClick={() => void refresh()}>
          <img src={refreshIcon} alt="" />
          {loading || scopeRefreshing ? "불러오는 중…" : "새로고침"}
        </button>
      </div>
      <div className="notice-controls">
        <div className="notice-search" role="search" aria-label="학교 공지 검색">
          <img src={searchIcon} alt="" />
          <input type="search" value={draft} maxLength={250} aria-label="공지 검색" placeholder="제목, 부서, 본문 검색"
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={(event) => {
              composing.current = false;
              setDraft(event.currentTarget.value);
              setQuery(normalizeNoticeQuery(event.currentTarget.value));
            }}
            onChange={(event) => {
              setDraft(event.currentTarget.value);
              if (!composing.current && !(event.nativeEvent as InputEvent).isComposing) setQuery(normalizeNoticeQuery(event.currentTarget.value));
            }} />
        </div>
        <div className="notice-control-row">
          <span className="notice-control-label">게시판</span>
          <div className="notice-boards" role="group" aria-label="공지 게시판">
            <div className="notice-filter-options">
              <div className="notice-filter-all">
                <NoticeFilterButton className="button" pressed={board === "all"} onClick={() => setBoard("all")} checkIcon={boardCheckIcon}>
                  {boardLabel("all")}
                </NoticeFilterButton>
              </div>
              <div className="notice-filter-scroll notice-school-tabs">
                {schoolBoards.map((value) => (
                  <NoticeFilterButton key={value} className="button" pressed={board === value} onClick={() => setBoard(value)} checkIcon={boardCheckIcon}>
                    {boardLabel(value)}
                  </NoticeFilterButton>
                ))}
              </div>
            </div>
            <NoticeFilterButton className="button notice-affiliation-tab" pressed={affiliation}
              onClick={() => setBoard("affiliation")} checkIcon={boardCheckIcon}>
              {boardLabel("affiliation")}
            </NoticeFilterButton>
          </div>
        </div>
        {affiliation && sources.length > 0 && <div className="notice-control-row">
          <span className="notice-control-label">소속</span>
          <div className="notice-filter-scroll notice-subboards" role="group" aria-label="소속 공지 게시판">
            {sources.map((source) => (
              <NoticeFilterButton key={source.id} className="button" pressed={activeSource?.id === source.id}
                onClick={() => setSourceId(source.id)}>{source.label}</NoticeFilterButton>
            ))}
          </div>
        </div>}
        <div className="notice-control-row">
          <span className="notice-control-label">주제</span>
          <div className="notice-filter-options" role="group" aria-label="공지 주제">
            <div className="notice-filter-all">
              <NoticeFilterButton pressed={!selectedTags.length} onClick={() => setSelectedTags([])}>전체</NoticeFilterButton>
            </div>
            <div className="notice-filter-scroll notice-topic-tabs">
              {topics.map((tag) => (
                <NoticeFilterButton key={tag} pressed={selectedTags.includes(tag)} onClick={() => toggleTag(tag)}>
                  {campusNoticeTags[tag]}
                </NoticeFilterButton>
              ))}
              {!!selectedTags.length && <button className="notice-clear-tags" type="button" onClick={() => setSelectedTags([])}>주제 선택 해제</button>}
            </div>
          </div>
        </div>
      </div>
      <div className="notice-scope">
        {filtered && !unavailable && <p>{affiliation ? "검색 범위는 이 게시판에서 불러온 공지예요." : "검색 범위는 게시판별 최근 3페이지와 더 보기로 불러온 공지예요."}</p>}
        {checkingBodies && <p role="status">공지 본문을 확인하는 중이에요.</p>}
        {index.partial && <p className="notice-inline-error" role="status">일부 공지를 불러오지 못했어요. 확인된 범위만 표시해요.</p>}
        {refreshError && <p className="notice-inline-error" role="status">공지 목록을 새로고침하지 못했어요.</p>}
      </div>
      <section ref={boardElement} className="notice-board" data-wide={wide} data-reading={showReading} style={splitStyle}
        aria-label={affiliation && activeSource ? activeSource.label : boardLabel(board)} aria-busy={loading || checkingBodies}>
        <div className="notice-timeline" id="notice-timeline">
          <div className="notice-timeline-header">
            <h2>{filtered ? "검색 결과" : "최근 공지"}</h2>
            <span>{results.length}건</span>
            {results.length > 0 && <p>게시일 기준</p>}
          </div>
          <div className="notice-timeline-scroll">
            {!!results.length && state?.error && <p className="notice-inline-error" role="status">{state.error} 이전 공지를 표시하고 있어요.</p>}
            {!!pinned.length && <details className="notice-pinned" open={!days.size || filtered || undefined}>
              <summary><img src={pinIcon} alt="" />고정 공지 {pinned.length}건<img src={disclosureIcon} alt="" /></summary>
              {renderNoticeRows(pinned)}
            </details>}
            {!!days.size && <div className="notice-date-groups">
              {[...days].map(([day, items]) => <div className="notice-date-group" key={day}
                data-selected={items.some(({ key }) => selection?.key === key)}>
                <div className="notice-date-marker">
                  {day ? <time dateTime={day} aria-label={noticeDate.format(new Date(day))}>
                    <span>{noticeMonth.format(new Date(day))}</span>
                    <small>{noticeDay.format(new Date(day))}</small>
                  </time> : <span>날짜 미상</span>}
                  <img src={items.some(({ key }) => selection?.key === key) ? selectedDateIcon : dateIcon} alt="" />
                </div>
                {renderNoticeRows(items)}
              </div>)}
            </div>}
            {!results.length && <div className="empty">
              <p role="status">{emptyMessage}</p>
              {(state?.error || refreshError || !notices.length && index.partial) &&
                <button className="button" type="button" disabled={unavailable || loading || scopeRefreshing} onClick={() => void refresh()}>다시 시도</button>}
            </div>}
          </div>
          {!!morePages.length && <div className="notice-pagination">
            <button type="button" disabled={loadingMore || state?.loading} onClick={() => void loadOlder()}>
              {loadingMore ? "불러오는 중…" : "이전 공지 더 보기"}<img src={moreIcon} alt="" />
            </button>
          </div>}
        </div>
        {wide && <PaneSplitter className="notice-splitter" label="공지 목록 너비" controls="notice-timeline"
          width={listWidth} min={minListWidth} max={maxListWidth} onResize={(width) => setPreferredListWidth(clampListWidth(width))} />}
        {selection ? <NoticeDetail key={selection.key} notice={selection.notice} initialDetail={selection.detail}
          sourceLabel={affiliation ? activeSource?.label : undefined} tags={selection.tags} onDismiss={closeReading} inline />
          : wide && <div className="notice-reading-empty">읽을 공지를 선택해 주세요.</div>}
      </section>
    </section>
  );
}
