import { useCallback, useEffect, useRef, useState } from "react";
import type { LmsBridgeError } from "../shared/lms.js";
import { useVisibleRefresh } from "./use-visible-refresh.js";

export type ScreenReadState<T> = { data: T | null; error: LmsBridgeError | null; loading: boolean; loadedAt?: number };

export function useScreenRead<T extends object>(
  key: string,
  visible: boolean,
  load: (refresh: boolean) => Promise<T | LmsBridgeError>,
  autoRefresh = visible,
) {
  const [reads, setReads] = useState(() => new Map<string, ScreenReadState<T>>());
  const sequence = useRef(0);
  const pending = useRef(false);
  const read = useCallback(async (refresh: boolean, background = false) => {
    if (background && pending.current) return;
    const request = ++sequence.current;
    pending.current = true;
    function update(change: (current: ScreenReadState<T> | undefined) => ScreenReadState<T>) {
      setReads((current) => {
        const next = new Map(current);
        next.delete(key);
        next.set(key, change(current.get(key)));
        if (next.size > 12) next.delete(next.keys().next().value!);
        return next;
      });
    }
    update((current) => background && current ? current : { ...current, data: current?.data ?? null, error: null, loading: true });
    let result: T | LmsBridgeError;
    try {
      result = await load(refresh);
    } catch {
      result = { status: "error", message: "정보를 불러오지 못했어요. 다시 시도해 주세요." };
    }
    if (sequence.current !== request) return;
    pending.current = false;
    if ("status" in result) {
      const error = result as LmsBridgeError;
      update((current) => background && current?.data && error.status !== "login_required" ? current : ({
        ...current,
        data: error.status === "login_required" ? null : current?.data ?? null,
        error,
        loading: false,
      }));
    } else {
      update(() => ({ data: result, error: null, loading: false, loadedAt: Date.now() }));
    }
  }, [key, load]);

  useEffect(() => {
    if (visible) void read(false, true);
    return () => { sequence.current++; pending.current = false; };
  }, [visible, read]);

  const state = reads.get(key) ?? { data: null, error: null, loading: true };
  useVisibleRefresh(autoRefresh, () => void read(true, true), state.loadedAt, key);
  return { ...state, refresh: () => void read(true) };
}
