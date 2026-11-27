import type { Chat, Message } from "../api/types";

export const NOW = Date.UTC(2026, 10, 27, 15, 0, 0); // 2026-11-27 15:00 UTC (TZ pinned to UTC in tests)

export function msg(over: Partial<Message> = {}): Message {
  return {
    id: 1, chat_id: 1, from_me: false, ts: NOW - 3_600_000, type: "text", status: null, text: "hello",
    sender_id: "15550100101@s.whatsapp.net", sender_name: "Alice Example", color_idx: 0,
    system_kind: null, system_target_name: null, media: null, quoted: null, ...over,
  };
}

export function chat(over: Partial<Chat> = {}): Chat {
  return {
    id: 1, jid: "15550100101@s.whatsapp.net", title: "Alice Example", subtitle: "+1 555 0100 101",
    is_group: false, archived: false, avatar_url: null, last_message_ts: NOW - 3_600_000,
    last_message: { text: "see you", type: "text", from_me: false, ts: NOW - 3_600_000 }, ...over,
  };
}

export const media = (over: Partial<NonNullable<Message["media"]>> = {}): NonNullable<Message["media"]> => ({
  mime: "image/jpeg", size_bytes: 2048, duration_s: null, width: 640, height: 480, file_name: "IMG-0001.jpg",
  available: true, url: "/api/media/1", ...over,
});
