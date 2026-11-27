/** Mirrors waarchive/server/models.py. */
export type AuthMode = "google" | "password_totp";

export interface StatusOut {
  auth_mode: AuthMode;
  authenticated: boolean;
  vault_unlocked: boolean;
  csrf_token: string | null;
}
export interface OkOut {
  ok: boolean;
  csrf_token: string | null;
}
export interface MediaInfo {
  mime: string | null;
  size_bytes: number | null;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  file_name: string | null;
  available: boolean;
  url: string | null;
}
export interface Quoted {
  message_id: number | null;
  text: string | null;
  sender_name: string | null;
  type: string | null;
}
export type MessageType =
  | "text" | "image" | "video" | "audio" | "ptt" | "document" | "sticker"
  | "contact" | "location" | "call" | "system" | "deleted" | "other";

export interface Message {
  id: number;
  chat_id: number;
  from_me: boolean;
  ts: number;
  type: MessageType | (string & {});
  status: number | null;
  text: string | null;
  sender_id: string | null;
  sender_name: string | null;
  color_idx: number | null;
  system_kind: string | null;
  system_target_name: string | null;
  media: MediaInfo | null;
  quoted: Quoted | null;
}
export interface MessagesPage {
  items: Message[];
  cursor_before: string | null;
  cursor_after: string | null;
  has_more_before: boolean;
  has_more_after: boolean;
  target_id: number | null;
}
export interface LastMessage {
  text: string | null;
  type: string;
  from_me: boolean;
  ts: number;
}
export interface Chat {
  id: number;
  jid: string;
  title: string;
  subtitle: string | null;
  is_group: boolean;
  archived: boolean;
  last_message_ts: number | null;
  last_message: LastMessage | null;
}
export interface ChatsPage {
  items: Chat[];
  next_cursor: string | null;
}
export interface Participant {
  jid: string;
  name: string;
  color_idx: number;
}
export interface ChatDetail extends Chat {
  participants: Participant[];
}
export interface SearchHit {
  message_id: number;
  chat_id: number;
  chat_title: string;
  ts: number;
  from_me: boolean;
  sender_name: string | null;
  type: string;
  snippet: string;
}
export interface SearchPage {
  items: SearchHit[];
  terms: string[];
  next_cursor: string | null;
}
