import { useEffect, useState } from "react";
import type { CampusNoticeIndexSnapshot, CampusNoticeScope } from "../shared/campus-notices.js";

const empty: CampusNoticeIndexSnapshot = {
  revision: -1, notices: [], entries: {}, listedBoards: [], pages: {}, loading: false, partial: false,
};
const loadingSnapshot = { ...empty, loading: true };

export const cleanNoticeText = (value: string) => value.normalize("NFC").trim().replace(/\s+/g, " ");
export const normalizeNoticeQuery = (value: string) => cleanNoticeText(value).toLocaleLowerCase("ko-KR");

export function noticeBodyExcerpt(content: string | null | undefined, query: string) {
  if (!content || !query) return;
  const text = cleanNoticeText(content);
  const match = text.toLocaleLowerCase("ko-KR").indexOf(query);
  if (match < 0) return;
  const start = Math.max(0, match - 32);
  const end = Math.min(text.length, match + query.length + 58);
  return `${start ? "…" : ""}${text.slice(start, end)}${end < text.length ? "…" : ""}`;
}

export function useCampusNoticeIndex(active: boolean, scope: CampusNoticeScope = "school"): CampusNoticeIndexSnapshot {
  const [snapshots, setSnapshots] = useState<Partial<Record<CampusNoticeScope, CampusNoticeIndexSnapshot>>>({});

  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let timer: number | undefined;
    let revision: number | undefined;
    let loading = true;

    async function update() {
      try {
        const result = await window.ast.getCampusNoticeIndex(revision, scope);
        if (stopped) return;
        if (result) {
          revision = result.revision;
          loading = result.loading;
          setSnapshots((previous) => ({ ...previous, [scope]: result }));
        }
        timer = window.setTimeout(() => void update(), loading ? 650 : 2000);
      } catch {
        if (!stopped) {
          failed();
          timer = window.setTimeout(() => void update(), 2000);
        }
      }
    }

    function failed() {
      setSnapshots((previous) => ({
        ...previous, [scope]: { ...(previous[scope] ?? empty), loading: false, partial: true },
      }));
    }

    setSnapshots((previous) => ({
      ...previous, [scope]: { ...(previous[scope] ?? empty), loading: true },
    }));
    void (async () => {
      try { await window.ast.syncCampusNoticeIndex(false, scope); }
      catch {
        if (!stopped) {
          failed();
          void update();
        }
        return;
      }
      if (!stopped) void update();
    })();

    return () => { stopped = true; window.clearTimeout(timer); };
  }, [active, scope]);

  return snapshots[scope] ?? (active ? loadingSnapshot : empty);
}
