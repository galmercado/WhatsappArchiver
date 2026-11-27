import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { append, fromPage, prepend, type MessageWindow } from "./messageWindow";

const PAGE = 40;

export function useChatMessages(chatId: number, anchor: number | null) {
  const [win, setWin] = useState<MessageWindow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const ref = useRef<MessageWindow | null>(null);
  const busy = useRef({ older: false, newer: false });
  const gen = useRef(0);
  ref.current = win;

  useEffect(() => {
    const g = ++gen.current;
    const ac = new AbortController();
    setWin(null);
    setError(null);
    busy.current = { older: false, newer: false };
    api
      .messages(chatId, anchor ? { around: anchor, limit: PAGE } : { limit: PAGE }, ac.signal)
      .then((p) => {
        if (g === gen.current) setWin(fromPage(p));
      })
      .catch((e: unknown) => {
        if (!ac.signal.aborted && g === gen.current) setError(e instanceof Error ? e.message : "Failed to load");
      });
    return () => ac.abort();
  }, [chatId, anchor, reloadKey]);

  const loadOlder = useCallback(async (): Promise<void> => {
    const w = ref.current;
    if (!w?.hasMoreBefore || !w.cursorBefore || busy.current.older) return;
    busy.current.older = true;
    const g = gen.current;
    try {
      const p = await api.messages(chatId, { before: w.cursorBefore, limit: PAGE });
      if (g === gen.current) setWin((cur) => (cur ? prepend(cur, p) : cur));
    } catch {
      /* transient: the next scroll retries */
    } finally {
      busy.current.older = false;
    }
  }, [chatId]);

  const loadNewer = useCallback(async (): Promise<void> => {
    const w = ref.current;
    if (!w?.hasMoreAfter || !w.cursorAfter || busy.current.newer) return;
    busy.current.newer = true;
    const g = gen.current;
    try {
      const p = await api.messages(chatId, { after: w.cursorAfter, limit: PAGE });
      if (g === gen.current) setWin((cur) => (cur ? append(cur, p) : cur));
    } catch {
      /* transient */
    } finally {
      busy.current.newer = false;
    }
  }, [chatId]);

  return { win, error, loadOlder, loadNewer, reload: () => setReloadKey((k) => k + 1), reloadKey };
}
