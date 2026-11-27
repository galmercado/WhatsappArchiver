import { memo, useState, type CSSProperties, type ReactNode } from "react";
import type { Message } from "../api/types";
import { dayLabel, fileExtension, formatBytes, formatClock, previewLabel, sameDay } from "../lib/format";
import { emojiOnlyCount, renderRich } from "../lib/richtext";
import { AudioPlayer } from "./AudioPlayer";
import { DocIcon, DownloadIcon, ImageIcon, Ticks, VideoIcon } from "./Icons";

export interface BubbleProps {
  m: Message;
  prev: Message | null;
  isGroup: boolean;
  terms: readonly string[];
  flash: boolean;
  onOpenMedia: (id: number) => void;
  onJump: (id: number) => void;
  now?: number;
}

const TEXTISH = new Set(["text", "other", "deleted", "contact", "location", "call"]);

function senderColor(idx: number | null): string {
  return `var(--c${(idx ?? 0) % 8})`;
}

export function DateChip({ ts, now }: { ts: number; now?: number }) {
  return (
    <div className="sticky top-2 z-10 my-3 flex justify-center">
      <span className="rounded-lg bg-chip px-3 py-[5px] text-[12.5px] uppercase text-[color:var(--chip-text)] shadow-[var(--shadow-bubble)]">
        {dayLabel(ts, now)}
      </span>
    </div>
  );
}

function systemText(m: Message): string {
  const who = m.system_target_name ?? m.sender_name ?? "Someone";
  const actor = m.from_me ? "You" : m.sender_name;
  switch (m.system_kind) {
    case "added": return actor ? `${actor} added ${who}` : `${who} was added`;
    case "removed": return actor ? `${actor} removed ${who}` : `${who} was removed`;
    case "group_created": return m.text ? `Group created: ${m.text}` : "Group created";
    case "subject_changed": return m.text ? `The group name was changed to “${m.text}”` : "The group name was changed";
    default: return m.text ?? "";
  }
}

function Meta({ m, overlay = false }: { m: Message; overlay?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap text-meta ${overlay ? "text-white" : "text-[color:var(--bubble-meta)]"}`}>
      <time dateTime={new Date(m.ts).toISOString()}>{formatClock(m.ts)}</time>
      {m.from_me ? <Ticks status={m.status} /> : null}
    </span>
  );
}

function Unavailable({ type }: { type: string }) {
  const Icon = type === "video" ? VideoIcon : ImageIcon;
  return (
    <div className="flex h-[120px] w-[min(240px,60vw)] flex-col items-center justify-center gap-1 rounded-md bg-black/5 text-ink2">
      <Icon size={30} />
      <span className="text-[12.5px]">Media not available</span>
    </div>
  );
}

function Photo({ m, url, box, onOpen }: { m: Message; url: string; box: CSSProperties; onOpen: (id: number) => void }) {
  const [broken, setBroken] = useState(false);
  if (broken) return <Unavailable type="image" />;
  return (
    <button type="button" onClick={() => onOpen(m.id)} aria-label="Open photo" className="block overflow-hidden rounded-md" style={box}>
      <img src={url} alt={m.text ?? "Photo"} loading="lazy" decoding="async" className="h-full w-full object-cover" onError={() => setBroken(true)} />
    </button>
  );
}

function Media({ m, onOpen }: { m: Message; onOpen: (id: number) => void }) {
  const media = m.media;
  if (!media) return null;
  if (!media.available || !media.url) return <Unavailable type={m.type} />;
  const ratio = media.width && media.height ? media.width / media.height : 4 / 3;
  const box = { aspectRatio: String(ratio), width: `min(330px, 62vw, ${Math.round(330 * Math.max(ratio, 0.6))}px)` };
  switch (m.type) {
    case "image":
    case "sticker":
      return <Photo m={m} url={media.url} box={box} onOpen={onOpen} />;
    case "video":
      return (
        <div className="relative overflow-hidden rounded-md bg-black" style={box}>
          <video src={media.url} controls preload="metadata" playsInline className="h-full w-full object-contain" />
        </div>
      );
    case "ptt":
    case "audio":
      return <AudioPlayer id={m.id} url={media.url} durationHint={media.duration_s} outgoing={m.from_me} />;
    default: {
      const ext = fileExtension(media.file_name, media.mime);
      return (
        <a href={media.url} download={media.file_name ?? undefined} className="flex w-[min(300px,62vw)] items-center gap-3 rounded-md bg-black/5 p-2.5 hover:bg-black/10" aria-label={`Download ${media.file_name ?? "document"}`}>
          <span className="relative inline-flex h-10 w-10 shrink-0 items-center justify-center rounded text-[#ea4c4c]">
            <DocIcon size={36} />
            <span className="absolute bottom-1.5 text-[8px] font-bold text-white">{ext.slice(0, 4)}</span>
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[14px] text-ink">{media.file_name ?? previewLabel(m.type, null)}</span>
            <span className="block text-[12px] text-ink2">{ext} · {formatBytes(media.size_bytes)}</span>
          </span>
          <DownloadIcon size={22} className="text-icon" />
        </a>
      );
    }
  }
}

function Quote({ m, onJump }: { m: Message; onJump: (id: number) => void }) {
  const q = m.quoted;
  if (!q) return null;
  const color = senderColor(m.color_idx);
  const body = q.text ?? previewLabel(q.type ?? "text", null);
  return (
    <button
      type="button"
      onClick={() => q.message_id !== null && onJump(q.message_id)}
      className="mb-1 block w-full overflow-hidden rounded-md text-left"
      style={{ background: m.from_me ? "var(--quote-out)" : "var(--quote-in)", borderLeft: `4px solid ${m.from_me ? "var(--accent)" : color}` }}
    >
      <span className="block px-2.5 py-1.5">
        <span className="block truncate text-[12.8px] font-medium" style={{ color: m.from_me ? "var(--accent-strong)" : color }}>
          {q.sender_name ?? "You"}
        </span>
        <span className="line-clamp-2 block text-[13px] text-ink2" dir="auto">{body}</span>
      </span>
    </button>
  );
}

function BubbleImpl({ m, prev, isGroup, terms, flash, onOpenMedia, onJump, now }: BubbleProps) {
  const newDay = !prev || !sameDay(prev.ts, m.ts);
  const chip = newDay ? <DateChip ts={m.ts} now={now} /> : null;

  if (m.type === "system") {
    return (
      <div data-msg-id={m.id}>
        {chip}
        <div className="my-2 flex justify-center px-4">
          <span className="max-w-[85%] rounded-lg bg-[color:var(--system-bg)] px-3 py-1.5 text-center text-[12.5px] text-[color:var(--system-text)] shadow-[var(--shadow-bubble)]">
            {systemText(m)}
          </span>
        </div>
      </div>
    );
  }

  const firstInGroup = !prev || prev.type === "system" || prev.from_me !== m.from_me || prev.sender_id !== m.sender_id || newDay;
  const media = m.media;
  const hasText = Boolean(m.text) && !(m.type === "document" && m.text === media?.file_name);
  const isSticker = m.type === "sticker";
  const visual = media !== null && (m.type === "image" || m.type === "video");
  const mediaOnly = visual && !hasText;
  const emojis = !media && m.text ? emojiOnlyCount(m.text) : 0;
  const showName = isGroup && !m.from_me && firstInGroup;
  const tail = firstInGroup && !isSticker;
  const side = m.from_me ? "out" : "in";

  let content: ReactNode;
  if (m.type === "deleted") {
    content = <span className="italic text-ink2">{m.from_me ? "You deleted this message" : "This message was deleted"}</span>;
  } else if (hasText) {
    content = (
      <span className={`pp ${emojis > 0 && emojis <= 3 ? "text-[34px] leading-[44px]" : ""}`} dir="auto">
        {renderRich(m.text ?? "", terms)}
      </span>
    );
  } else if (!media && !TEXTISH.has(m.type)) {
    content = null;
  } else if (!media) {
    content = <span className="italic text-ink2">{previewLabel(m.type, null) || "Unsupported message"}</span>;
  } else {
    content = null;
  }

  return (
    <div data-msg-id={m.id} className={flash ? "msg-flash" : undefined}>
      {chip}
      <div className={`flex px-3 md:px-[7%] ${m.from_me ? "justify-end" : "justify-start"} ${firstInGroup ? "mt-[10px]" : "mt-[2px]"}`}>
        <div
          data-testid={`bubble-${m.id}`}
          data-side={side}
          className={isSticker ? "relative max-w-[75%] md:max-w-[65%]" : `bubble bubble-${side} ${tail ? `tail-${side}` : ""} max-w-[85%] md:max-w-[65%] ${mediaOnly ? "p-[3px]" : "px-[7px] pb-[8px] pt-[6px]"}`}
        >
          {showName ? (
            <div className="mb-[1px] truncate px-[2px] text-[12.8px] font-medium leading-[22px]" style={{ color: senderColor(m.color_idx) }} data-testid="sender-name">
              {m.sender_name ?? m.sender_id}
            </div>
          ) : null}
          <Quote m={m} onJump={onJump} />
          {media ? <div className={mediaOnly ? "relative" : "mb-1"}><Media m={m} onOpen={onOpenMedia} />
            {mediaOnly ? <span className="absolute bottom-1.5 right-2 rounded px-1 text-white" style={{ background: "linear-gradient(transparent, rgba(0,0,0,.45))", textShadow: "0 0 3px rgba(0,0,0,.6)" }}><Meta m={m} overlay /></span> : null}
          </div> : null}
          {!mediaOnly && !isSticker ? (
            <div className="relative px-[2px] text-msg text-ink">
              {content}
              {/* reserve room so text never runs under the floating timestamp */}
              <span className="inline-block" style={{ width: m.from_me ? 74 : 52 }} aria-hidden="true" />
              <span className="absolute bottom-[-3px] right-0">
                <Meta m={m} />
              </span>
            </div>
          ) : null}
          {isSticker ? <div className="mt-0.5 text-right"><Meta m={m} /></div> : null}
        </div>
      </div>
    </div>
  );
}

export const MessageBubble = memo(BubbleImpl);
