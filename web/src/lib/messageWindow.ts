import type { Message, MessagesPage } from "../api/types";

/** Sliding window over a conversation. Bounded so 100k+ message chats never exhaust memory. */
export interface MessageWindow {
  items: Message[];
  /** Virtuoso `firstItemIndex`: decreases when older pages are prepended. */
  firstIndex: number;
  hasMoreBefore: boolean;
  hasMoreAfter: boolean;
  cursorBefore: string | null;
  cursorAfter: string | null;
}

export const START_INDEX = 1_000_000;
export const MAX_WINDOW = 1200;

export function encodeCursor(ts: number, id: number): string {
  return btoa(`${ts}:${id}`).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function edge(m: Message | undefined): string | null {
  return m ? encodeCursor(m.ts, m.id) : null;
}

export function fromPage(page: MessagesPage): MessageWindow {
  return {
    items: page.items,
    firstIndex: START_INDEX,
    hasMoreBefore: page.has_more_before,
    hasMoreAfter: page.has_more_after,
    cursorBefore: page.cursor_before,
    cursorAfter: page.cursor_after,
  };
}

export function prepend(w: MessageWindow, page: MessagesPage): MessageWindow {
  const have = new Set(w.items.map((m) => m.id));
  const fresh = page.items.filter((m) => !have.has(m.id));
  let items = [...fresh, ...w.items];
  let { hasMoreAfter, cursorAfter } = w;
  if (items.length > MAX_WINDOW) {
    items = items.slice(0, MAX_WINDOW); // drop the newest end; it can be re-fetched
    hasMoreAfter = true;
    cursorAfter = edge(items[items.length - 1]);
  }
  return {
    items,
    firstIndex: w.firstIndex - fresh.length,
    hasMoreBefore: page.has_more_before,
    cursorBefore: page.cursor_before ?? w.cursorBefore,
    hasMoreAfter,
    cursorAfter,
  };
}

export function append(w: MessageWindow, page: MessagesPage): MessageWindow {
  const have = new Set(w.items.map((m) => m.id));
  const fresh = page.items.filter((m) => !have.has(m.id));
  let items = [...w.items, ...fresh];
  let { firstIndex, hasMoreBefore, cursorBefore } = w;
  if (items.length > MAX_WINDOW) {
    const drop = items.length - MAX_WINDOW;
    items = items.slice(drop); // drop the oldest end; Virtuoso needs firstIndex to move with it
    firstIndex += drop;
    hasMoreBefore = true;
    cursorBefore = edge(items[0]);
  }
  return {
    items,
    firstIndex,
    hasMoreBefore,
    cursorBefore,
    hasMoreAfter: page.has_more_after,
    cursorAfter: page.cursor_after ?? w.cursorAfter,
  };
}
