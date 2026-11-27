import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Virtuoso, type ListRange, type VirtuosoHandle } from "react-virtuoso";
import { api } from "../api/client";
import type { ChatDetail } from "../api/types";
import { useChatMessages } from "../lib/useChatMessages";
import { Avatar, BackIcon, ChevronDownIcon, LockIcon, SearchIcon } from "./Icons";
import { Lightbox } from "./Lightbox";
import { IconButton, Menu } from "./Menu";
import { MessageBubble } from "./MessageBubble";

interface Props {
  chatId: number;
  anchor: number | null;
  terms: readonly string[];
  searchOpen: boolean;
  onToggleSearch: () => void;
  onBack: () => void;
  onJump: (messageId: number) => void;
  onLatest: () => void;
}

// Stable component identities: inline arrow components would remount (and reset scroll) every render.
const LIST_COMPONENTS = { Header: () => <div className="h-3" />, Footer: () => <div className="h-3" /> };

function subtitleFor(chat: ChatDetail | null): string {
  if (!chat) return "";
  if (!chat.is_group) return chat.subtitle ?? "";
  const names = chat.participants.map((p) => p.name);
  return names.length ? [...names, "You"].join(", ") : "";
}

export function ChatView({ chatId, anchor, terms, searchOpen, onToggleSearch, onBack, onJump, onLatest }: Props) {
  const { win, error, loadOlder, loadNewer, reloadKey } = useChatMessages(chatId, anchor);
  const [chat, setChat] = useState<ChatDetail | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [flashId, setFlashId] = useState<number | null>(null);
  const [lightboxId, setLightboxId] = useState<number | null>(null);
  const list = useRef<VirtuosoHandle>(null);
  // Edge loaders stay disarmed until the initial scroll-to-target has settled; otherwise the
  // "top reached" event fired during positioning prepends a page and shifts the view off target.
  const armed = useRef(false);
  const range = useRef<ListRange | null>(null);
  const winRef = useRef(win);
  winRef.current = win;
  const loaded = win !== null;

  /** Load whichever side the visible range has reached. Range-driven, so no edge event can be lost. */
  const pump = useCallback(
    (r: ListRange | null): void => {
      const w = winRef.current;
      if (!armed.current || !w || !r) return;
      if (r.startIndex - w.firstIndex < 4) void loadOlder();
      if (r.endIndex - w.firstIndex >= w.items.length - 4) void loadNewer();
    },
    [loadOlder, loadNewer],
  );

  useEffect(() => {
    armed.current = false;
    range.current = null;
    if (!loaded) return;
    const t = window.setTimeout(() => {
      armed.current = true;
      pump(range.current);
    }, 700);
    return () => window.clearTimeout(t);
  }, [chatId, anchor, reloadKey, loaded, pump]);

  useEffect(() => {
    const ac = new AbortController();
    setChat(null);
    api.chat(chatId, ac.signal).then(setChat).catch(() => undefined);
    return () => ac.abort();
  }, [chatId]);

  useEffect(() => {
    if (!anchor || !win) return;
    setFlashId(anchor);
    const t = window.setTimeout(() => setFlashId(null), 2200);
    return () => window.clearTimeout(t);
  }, [anchor, win === null]); // eslint-disable-line react-hooks/exhaustive-deps

  const gallery = useMemo(
    () => (win?.items ?? []).filter((m) => m.media?.available && (m.type === "image" || m.type === "video")),
    [win],
  );
  const lightboxIndex = lightboxId === null ? -1 : gallery.findIndex((m) => m.id === lightboxId);
  const openMedia = useCallback((id: number) => setLightboxId(id), []);

  const scrollDown = (): void => {
    if (win?.hasMoreAfter) onLatest();
    else list.current?.scrollToIndex({ index: "LAST", align: "end", behavior: "smooth" });
  };

  const initial = useMemo(() => {
    if (!win) return undefined;
    const idx = anchor ? win.items.findIndex((m) => m.id === anchor) : -1;
    return idx >= 0 ? { index: idx, align: "center" as const } : { index: "LAST" as const, align: "end" as const };
  }, [win === null, anchor]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <header className="flex h-[59px] shrink-0 items-center gap-3 border-l border-line bg-panel px-4">
        <button type="button" aria-label="Back to chats" className="text-icon md:hidden" onClick={onBack}>
          <BackIcon />
        </button>
        <Avatar group={chat?.is_group ?? false} size={40} src={chat?.avatar_url ?? null} />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[16px] leading-5 text-ink" data-testid="chat-title">{chat?.title ?? "…"}</h2>
          <p className="truncate text-[13px] leading-4 text-ink2">{subtitleFor(chat)}</p>
        </div>
        <IconButton label="Search messages" onClick={onToggleSearch} pressed={searchOpen}>
          <SearchIcon />
        </IconButton>
        <Menu items={[{ label: "Close chat", onSelect: onBack }]} label="Chat menu" />
      </header>

      <div className="wallpaper min-h-0 flex-1">
        <div className="absolute inset-0">
          {error ? (
            <p role="alert" className="p-6 text-center text-ink2">Could not load messages.</p>
          ) : !win ? (
            <div className="flex h-full items-center justify-center text-ink2" role="status">Loading…</div>
          ) : win.items.length === 0 ? (
            <div className="flex h-full items-center justify-center text-ink2">No messages in this chat.</div>
          ) : (
            <Virtuoso
              key={`${chatId}:${anchor ?? "latest"}:${reloadKey}`}
              ref={list}
              style={{ height: "100%" }}
              data={win.items}
              firstItemIndex={win.firstIndex}
              initialTopMostItemIndex={initial}
              alignToBottom
              increaseViewportBy={{ top: 800, bottom: 800 }}
              rangeChanged={(r) => {
                range.current = r;
                pump(r);
              }}
              atBottomStateChange={setAtBottom}
              atBottomThreshold={120}
              followOutput={false}
              computeItemKey={(_i, m) => m.id}
              components={LIST_COMPONENTS}
              itemContent={(index, m) => (
                <MessageBubble
                  m={m}
                  prev={win.items[index - win.firstIndex - 1] ?? null}
                  isGroup={chat?.is_group ?? false}
                  terms={terms}
                  flash={flashId === m.id}
                  onOpenMedia={openMedia}
                  onJump={onJump}
                />
              )}
            />
          )}
          {win && (!atBottom || win.hasMoreAfter) ? (
            <button type="button" aria-label="Scroll to latest message" onClick={scrollDown} className="absolute bottom-4 right-5 z-20 flex h-10 w-10 items-center justify-center rounded-full bg-panel text-icon shadow-[0_1px_3px_rgba(11,20,26,.4)]">
              <ChevronDownIcon />
            </button>
          ) : null}
        </div>
      </div>

      <footer className="flex h-[62px] shrink-0 items-center gap-3 border-l border-line bg-panel px-4">
        <span className="flex flex-1 items-center gap-2 rounded-lg bg-[color:var(--composer)] px-4 py-[9px] text-[14.5px] text-ink2">
          <LockIcon size={16} className="shrink-0" />
          <span className="truncate"><span className="sm:hidden">Read-only archive</span><span className="hidden sm:inline">Read-only archive. Messages can't be sent from here.</span></span>
        </span>
      </footer>

      {lightboxIndex >= 0 ? (
        <Lightbox items={gallery} index={lightboxIndex}  
        onIndex={(i) => setLightboxId(gallery.at(i)?.id ?? null)} onClose={() => setLightboxId(null)} />
      ) : null}
    </div>
  );
}
