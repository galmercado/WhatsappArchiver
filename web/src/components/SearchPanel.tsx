import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SearchHit } from "../api/types";
import { useDebounced } from "../lib/useDebounced";
import { CloseIcon, SearchIcon } from "./Icons";
import { IconButton } from "./Menu";
import { HitRow } from "./SearchResults";

export function SearchPanel({ chatId, onClose, onJump, onTerms }: { chatId: number; onClose: () => void; onJump: (messageId: number) => void; onTerms: (t: string[]) => void }) {
  const [query, setQuery] = useState("");
  const q = useDebounced(query.trim(), 250);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [terms, setTerms] = useState<string[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "done" | "invalid">("idle");

  useEffect(() => {
    if (!q) {
      setHits([]);
      setTerms([]);
      onTerms([]);
      setState("idle");
      return;
    }
    const ac = new AbortController();
    setState("loading");
    api
      .search({ q, chatId }, ac.signal)
      .then((p) => {
        setHits(p.items);
        setTerms(p.terms);
        onTerms(p.terms);
        setCursor(p.next_cursor);
        setState("done");
      })
      .catch(() => {
        if (!ac.signal.aborted) {
          setHits([]);
          setState("invalid");
        }
      });
    return () => ac.abort();
  }, [q, chatId, onTerms]);

  useEffect(() => () => onTerms([]), [onTerms]);

  const more = async (): Promise<void> => {
    if (!cursor) return;
    const p = await api.search({ q, chatId, cursor });
    setHits((h) => [...h, ...p.items]);
    setCursor(p.next_cursor);
  };

  return (
    <aside aria-label="Search messages" className="fixed inset-0 z-40 flex flex-col bg-sidebar md:static md:inset-auto md:z-auto md:w-[30%] md:min-w-[340px] md:max-w-[480px] md:border-l md:border-line">
      <header className="flex h-[59px] shrink-0 items-center gap-4 bg-panel px-4">
        <IconButton label="Close search" onClick={onClose}>
          <CloseIcon />
        </IconButton>
        <h2 className="text-[16px] text-ink">Search messages</h2>
      </header>
      <div className="px-3 py-2">
        <label className="flex h-[35px] items-center gap-6 rounded-lg bg-input pl-4 pr-3">
          <SearchIcon size={18} className="text-icon" />
          <input autoFocus type="search" aria-label="Search in this chat" placeholder="Search…" maxLength={100} value={query} onChange={(e) => setQuery(e.target.value)} className="h-full w-full bg-transparent text-[14px] text-ink outline-none placeholder:text-ink2 [&::-webkit-search-cancel-button]:hidden" />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {state === "idle" ? <p className="p-8 text-center text-[14px] text-ink2">Search for messages in this chat.</p> : null}
        {state === "invalid" ? <p className="p-8 text-center text-[14px] text-ink2">Try different words.</p> : null}
        {state === "done" && hits.length === 0 ? <p className="p-8 text-center text-[14px] text-ink2">No messages found</p> : null}
        {hits.map((h) => (
          <HitRow key={h.message_id} hit={h} terms={terms} showChat={false} onOpen={(x) => onJump(x.message_id)} />
        ))}
        {cursor ? <button type="button" className="w-full py-3 text-[14px] text-accent-strong" onClick={() => void more()}>Show more</button> : null}
      </div>
    </aside>
  );
}
