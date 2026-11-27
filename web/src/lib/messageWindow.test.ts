import type { Message, MessagesPage } from "../api/types";
import { msg } from "../test/factories";
import { MAX_WINDOW, START_INDEX, append, encodeCursor, fromPage, prepend } from "./messageWindow";

const mk = (from: number, to: number): Message[] => Array.from({ length: to - from + 1 }, (_, i) => msg({ id: from + i, ts: 1000 + (from + i) * 10 }));
const page = (items: Message[], more: { before?: boolean; after?: boolean } = {}): MessagesPage => ({
  items, cursor_before: items[0] ? encodeCursor(items[0].ts, items[0].id) : null, cursor_after: items.at(-1) ? encodeCursor(items.at(-1)!.ts, items.at(-1)!.id) : null,
  has_more_before: more.before ?? false, has_more_after: more.after ?? false, target_id: null,
});

it("cursor encoding matches the server's urlsafe-base64 (no padding)", () => {
  expect(encodeCursor(1700000000000, 12)).toBe(btoa("1700000000000:12").replace(/=+$/, ""));
  expect(encodeCursor(-5, 3)).not.toMatch(/[+/=]/);
});

it("prepend keeps order, moves firstIndex by the number of new rows, and dedupes", () => {
  let w = fromPage(page(mk(50, 59), { before: true }));
  expect(w.firstIndex).toBe(START_INDEX);
  w = prepend(w, page(mk(40, 52), { before: true })); // overlaps 50–52
  expect(w.items.map((m) => m.id)).toEqual([...Array.from({ length: 20 }, (_, i) => 40 + i)]);
  expect(w.firstIndex).toBe(START_INDEX - 10);
  expect(w.hasMoreBefore).toBe(true);
});

it("append dedupes and updates flags", () => {
  let w = fromPage(page(mk(1, 10), { after: true }));
  w = append(w, page(mk(8, 15), { after: false }));
  expect(w.items.map((m) => m.id)).toEqual(Array.from({ length: 15 }, (_, i) => i + 1));
  expect(w.hasMoreAfter).toBe(false);
});

it("bounded: scrolling far back drops the newest end and re-enables loading it", () => {
  let w = fromPage(page(mk(2961, 3000), { before: true }));
  for (let hi = 2960; hi > 0; hi -= 40) w = prepend(w, page(mk(Math.max(hi - 39, 1), hi), { before: hi > 40 }));
  expect(w.items.length).toBeLessThanOrEqual(MAX_WINDOW);
  expect(w.hasMoreAfter).toBe(true);
  expect(w.cursorAfter).toBe(encodeCursor(w.items.at(-1)!.ts, w.items.at(-1)!.id));
  const ids = w.items.map((m) => m.id);
  expect(ids).toEqual([...ids].sort((a, b) => a - b));
});

it("bounded: scrolling far forward drops the oldest end and advances firstIndex", () => {
  let w = fromPage(page(mk(1, 40), { after: true }));
  for (let lo = 41; lo < 3000; lo += 40) w = append(w, page(mk(lo, lo + 39), { after: true }));
  expect(w.items.length).toBe(MAX_WINDOW);
  expect(w.items.at(-1)!.id).toBeGreaterThan(w.items[0]!.id);
  expect(w.firstIndex - START_INDEX).toBe(w.items[0]!.id - 1); // index advanced by exactly the rows dropped
  expect(w.hasMoreBefore).toBe(true);
  expect(w.cursorBefore).toBe(encodeCursor(w.items[0]!.ts, w.items[0]!.id));
});
