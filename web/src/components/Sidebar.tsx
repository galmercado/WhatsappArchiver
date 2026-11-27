import { useCallback, useEffect, useRef, useState } from "react";
import { Virtuoso } from "react-virtuoso";
import { api } from "../api/client";
import type { Chat, SearchHit } from "../api/types";
import { useDebounced } from "../lib/useDebounced";
import { ArchiveIcon, Avatar, BackIcon, LockIcon, LogoutIcon, MoonIcon, SearchIcon, SunIcon } from "./Icons";
import { ChatListItem } from "./ChatListItem";
import { Menu } from "./Menu";
import { HitRow } from "./SearchResults";
import { useSession } from "../state/session";
import { isDark, setThemePref } from "../lib/theme";

interface Props {
  selectedId: number | null;
  onOpenChat: (chatId: number, messageId?: number | null) => void;
}

export function Sidebar({ selectedId, onOpenChat }: Props) {
  const { lock, logout } = useSession();
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const [focused, setFocused] = useState(false);
  const [dark, setDark] = useState(isDark());
  const q = useDebounced(query.trim(), 250);

  const [chats, setChats] = useState<Chat[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const gen = useRef(0);
  const busy = useRef(false);

  const [hits, setHits] = useState<SearchHit[]>([]);
  const [hitTerms, setHitTerms] = useState<string[]>([]);
  const [hitCursor, setHitCursor] = useState<string | null>(null);

  const load = useCallback(
    async (reset: boolean, from: string | null) => {
      if (busy.current && !reset) return;
      busy.current = true;
      const g = reset ? ++gen.current : gen.current;
      if (reset) setLoading(true);
      try {
        const p = await api.chats({ q: q || undefined, archived, cursor: reset ? null : from });
        if (g !== gen.current) return;
        setChats((cur) => (reset ? p.items : [...cur, ...p.items]));
        setCursor(p.next_cursor);
        setFailed(false);
      } catch {
        if (g === gen.current) setFailed(true);
      } finally {
        if (g === gen.current) setLoading(false);
        busy.current = false;
      }
    },
    [q, archived],
  );

  useEffect(() => {
    void load(true, null);
  }, [load]);

  const loadHits = useCallback(
    async (from: string | null) => {
      try {
        const p = await api.search({ q, cursor: from, limit: 20 });
        setHits((cur) => (from ? [...cur, ...p.items] : p.items));
        setHitTerms(p.terms);
        setHitCursor(p.next_cursor);
      } catch {
        if (!from) setHits([]);
        setHitCursor(null);
      }
    },
    [q],
  );
  useEffect(() => {
    if (q.length >= 2 && !archived) void loadHits(null);
    else {
      setHits([]);
      setHitCursor(null);
    }
  }, [q, archived, loadHits]);

  const searching = q.length > 0;
  const toggleTheme = (): void => {
    setThemePref(dark ? "light" : "dark");
    setDark(!dark);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-[59px] shrink-0 items-center justify-between bg-panel px-4">
        <Avatar group={false} size={40} />
        <div className="flex items-center gap-1">
          <Menu
            label="Menu"
            items={[
              { label: dark ? "Light mode" : "Dark mode", icon: dark ? <SunIcon size={20} /> : <MoonIcon size={20} />, onSelect: toggleTheme },
              { label: archived ? "Back to all chats" : "Archived chats", icon: <ArchiveIcon size={20} />, onSelect: () => setArchived((a) => !a) },
              { label: "Lock vault", icon: <LockIcon size={20} />, onSelect: () => void lock() },
              { label: "Log out", icon: <LogoutIcon size={20} />, onSelect: () => void logout() },
            ]}
          />
        </div>
      </header>

      <div className="shrink-0 bg-sidebar px-3 py-2">
        <label className="flex h-[35px] items-center gap-6 rounded-lg bg-input pl-4 pr-3">
          <span className="text-icon" style={{ color: focused ? "var(--accent)" : undefined }}>
            {focused || query ? (
              <button type="button" aria-label="Clear search" onMouseDown={(e) => e.preventDefault()} onClick={() => setQuery("")}>
                <BackIcon size={18} />
              </button>
            ) : (
              <SearchIcon size={18} />
            )}
          </span>
          <input
            type="search"
            aria-label="Search or filter chats"
            placeholder={archived ? "Search archived chats" : "Search or start new chat"}
            value={query}
            maxLength={100}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            className="h-full w-full bg-transparent text-[14px] text-ink outline-none placeholder:text-ink2 [&::-webkit-search-cancel-button]:hidden"
          />
        </label>
      </div>
      {archived ? <div className="bg-sidebar px-4 pb-1 pt-2 text-[13px] text-accent-strong">Archived</div> : null}

      <div className="min-h-0 flex-1 bg-sidebar" role="listbox" aria-label="Chats">
        {failed ? (
          <p role="alert" className="p-6 text-center text-ink2">Could not load chats.</p>
        ) : loading && chats.length === 0 ? (
          <p role="status" className="p-6 text-center text-ink2">Loading chats…</p>
        ) : searching ? (
          <div className="h-full overflow-y-auto">
            {chats.length === 0 && hits.length === 0 ? <p className="p-6 text-center text-ink2">No chats, contacts or messages found</p> : null}
            {chats.map((c) => (
              <ChatListItem key={c.id} chat={c} selected={c.id === selectedId} onOpen={(id) => onOpenChat(id)} />
            ))}
            {cursor ? <button type="button" className="w-full py-3 text-[14px] text-accent-strong" onClick={() => void load(false, cursor)}>Show more chats</button> : null}
            {hits.length > 0 ? (
              <section aria-label="Messages">
                <h3 className="bg-sidebar px-4 pb-1 pt-4 text-[15px] text-accent-strong">Messages</h3>
                {hits.map((h) => (
                  <HitRow key={h.message_id} hit={h} terms={hitTerms} showChat onOpen={(x) => onOpenChat(x.chat_id, x.message_id)} />
                ))}
                {hitCursor ? <button type="button" className="w-full py-3 text-[14px] text-accent-strong" onClick={() => void loadHits(hitCursor)}>Show more messages</button> : null}
              </section>
            ) : null}
          </div>
        ) : chats.length === 0 ? (
          <p className="p-6 text-center text-ink2">{archived ? "No archived chats" : "No chats"}</p>
        ) : (
          <Virtuoso
            data={chats}
            fixedItemHeight={72}
            endReached={() => cursor && void load(false, cursor)}
            computeItemKey={(_i, c) => c.id}
            itemContent={(_i, c) => <ChatListItem chat={c} selected={c.id === selectedId} onOpen={(id) => onOpenChat(id)} />}
          />
        )}
      </div>
    </div>
  );
}
