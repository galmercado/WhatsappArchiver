import { memo, type ReactNode } from "react";
import type { Chat } from "../api/types";
import { formatChatListTime, previewLabel } from "../lib/format";
import { Avatar, ImageIcon, MicIcon, Ticks, VideoIcon, DocIcon } from "./Icons";

function typeIcon(type: string): ReactNode {
  switch (type) {
    case "image": case "sticker": return <ImageIcon size={16} />;
    case "video": return <VideoIcon size={16} />;
    case "ptt": case "audio": return <MicIcon size={16} />;
    case "document": return <DocIcon size={16} />;
    default: return null;
  }
}

function ChatListItemImpl({ chat, selected, onOpen, now }: { chat: Chat; selected: boolean; onOpen: (id: number) => void; now?: number }) {
  const last = chat.last_message;
  const label = last ? previewLabel(last.type, last.text) : "";
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-testid={`chat-${chat.id}`}
      onClick={() => onOpen(chat.id)}
      className={`flex h-[72px] w-full items-center gap-[15px] pl-[13px] pr-[15px] text-left ${selected ? "bg-selected" : "hover:bg-hover"}`}
    >
      <Avatar group={chat.is_group} />
      <div className="flex h-full min-w-0 flex-1 flex-col justify-center border-b border-line">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-list text-ink">{chat.title}</span>
          {chat.last_message_ts ? <span className="shrink-0 text-[12px] text-ink2">{formatChatListTime(chat.last_message_ts, now)}</span> : null}
        </div>
        <div className="mt-[1px] flex items-center gap-1 text-sub text-ink2">
          {last?.from_me ? <Ticks status={3} /> : null}
          {last ? typeIcon(last.type) : null}
          <span className="truncate" dir="auto">{label}</span>
        </div>
      </div>
    </button>
  );
}

export const ChatListItem = memo(ChatListItemImpl);
