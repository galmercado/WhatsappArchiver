import type {
  ChatDetail, ChatsPage, MessagesPage, OkOut, SearchPage, StatusOut,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Listener = (status: number) => void;
let csrfToken: string | null = null;
const listeners = new Set<Listener>();

export function setCsrf(token: string | null): void {
  csrfToken = token;
}
/** Notified on 401 (session lost) and 423 (vault locked) from data calls. */
export function onAuthProblem(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  }
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Network error");
  }
  if (!res.ok) {
    let detail = "Request failed";
    try {
      const j: unknown = await res.json();
      if (isRecord(j) && typeof j.detail === "string") detail = j.detail;
    } catch {
      /* non-JSON error body */
    }
    const ra = Number(res.headers.get("Retry-After"));
    if (res.status === 401 || res.status === 423) listeners.forEach((l) => l(res.status));
    throw new ApiError(res.status, detail, Number.isFinite(ra) && ra > 0 ? ra : null);
  }
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const api = {
  status: (signal?: AbortSignal) => request<StatusOut>("GET", "/auth/status", undefined, signal),
  login: (password: string, totp: string) => request<OkOut>("POST", "/auth/login", { password, totp }),
  logout: () => request<OkOut>("POST", "/auth/logout", {}),
  unlock: (passphrase: string) => request<OkOut>("POST", "/vault/unlock", { passphrase }),
  lock: () => request<OkOut>("POST", "/vault/lock", {}),
  chats: (p: { q?: string; cursor?: string | null; archived?: boolean; limit?: number }, signal?: AbortSignal) =>
    request<ChatsPage>("GET", `/api/chats${qs({ ...p, limit: p.limit ?? 50 })}`, undefined, signal),
  chat: (id: number, signal?: AbortSignal) => request<ChatDetail>("GET", `/api/chats/${id}`, undefined, signal),
  messages: (
    id: number,
    p: { before?: string | null; after?: string | null; around?: number | null; limit?: number },
    signal?: AbortSignal,
  ) => request<MessagesPage>("GET", `/api/chats/${id}/messages${qs({ ...p, limit: p.limit ?? 40 })}`, undefined, signal),
  search: (p: { q: string; chatId?: number | null; cursor?: string | null; limit?: number }, signal?: AbortSignal) =>
    request<SearchPage>(
      "GET",
      `/api/search${qs({ q: p.q, chat_id: p.chatId, cursor: p.cursor, limit: p.limit ?? 30 })}`,
      undefined,
      signal,
    ),
};

export const mediaUrl = (messageId: number): string => `/api/media/${messageId}`;
