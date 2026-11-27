import { formatChatListTime } from "../lib/format";
import { highlight } from "../lib/richtext";
import type { SearchHit } from "../api/types";

export function HitRow({ hit, terms, showChat, onOpen }: { hit: SearchHit; terms: readonly string[]; showChat: boolean; onOpen: (h: SearchHit) => void }) {
  return (
    <button type="button" onClick={() => onOpen(hit)} className="flex w-full flex-col gap-0.5 px-4 py-2.5 text-left hover:bg-hover" data-testid={`hit-${hit.message_id}`}>
      <span className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[15px] text-ink">{showChat ? hit.chat_title : hit.from_me ? "You" : (hit.sender_name ?? "")}</span>
        <span className="shrink-0 text-[12px] text-ink2">{formatChatListTime(hit.ts)}</span>
      </span>
      <span className="line-clamp-2 text-[14px] text-ink2" dir="auto">
        {showChat && !hit.from_me && hit.sender_name ? `${hit.sender_name}: ` : ""}
        {highlight(hit.snippet, terms, `h${hit.message_id}`)}
      </span>
    </button>
  );
}
