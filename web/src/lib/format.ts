const DAY = 86_400_000;

function startOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function sameDay(a: number, b: number): boolean {
  return startOfDay(a) === startOfDay(b);
}

/** 14:05 / 2:05 PM — locale decides, like WhatsApp Web. */
export function formatClock(ts: number): string {
  return new Date(ts).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function numericDate(ts: number): string {
  return new Date(ts).toLocaleDateString(undefined, { day: "numeric", month: "numeric", year: "numeric" });
}

function weekday(ts: number): string {
  return new Date(ts).toLocaleDateString(undefined, { weekday: "long" });
}

/** Sidebar timestamp: time today, "Yesterday", weekday this week, otherwise a date. */
export function formatChatListTime(ts: number, now: number = Date.now()): string {
  const diffDays = Math.round((startOfDay(now) - startOfDay(ts)) / DAY);
  if (diffDays <= 0) return formatClock(ts);
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return weekday(ts);
  return numericDate(ts);
}

/** Date divider inside a conversation: TODAY / YESTERDAY / weekday / date. */
export function dayLabel(ts: number, now: number = Date.now()): string {
  const diffDays = Math.round((startOfDay(now) - startOfDay(ts)) / DAY);
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return weekday(ts);
  return numericDate(ts);
}

export function formatBytes(n: number | null): string {
  if (n === null || n < 0) return "";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  // eslint-disable-next-line security/detect-object-injection -- numeric index
  return `${v >= 10 ? Math.round(v) : v.toFixed(1)} ${units[i] ?? "TB"}`;
}

export function formatDuration(totalSeconds: number | null): string {
  if (totalSeconds === null || !Number.isFinite(totalSeconds) || totalSeconds < 0) return "0:00";
  const s = Math.floor(totalSeconds);
  const m = Math.floor(s / 60);
  const sec = String(s % 60).padStart(2, "0");
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function fileExtension(name: string | null, mime: string | null): string {
  const m = name ? /\.([A-Za-z0-9]{1,5})$/.exec(name) : null;
  if (m?.[1]) return m[1].toUpperCase();
  const sub = mime?.split("/")[1]?.split(";")[0];
  return sub ? sub.slice(0, 4).toUpperCase() : "FILE";
}

/** Preview text for the sidebar when the last message has no text. */
export function previewLabel(type: string, text: string | null): string {
  if (text) return text;
  switch (type) {
    case "image": return "Photo";
    case "video": return "Video";
    case "audio": return "Audio";
    case "ptt": return "Voice message";
    case "document": return "Document";
    case "sticker": return "Sticker";
    case "contact": return "Contact";
    case "location": return "Location";
    case "call": return "Call";
    case "deleted": return "This message was deleted";
    case "system": return "";
    default: return "";
  }
}

/** Deterministic, privacy-neutral initial for avatar fallbacks (unused when silhouettes show). */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "")).toUpperCase();
}
