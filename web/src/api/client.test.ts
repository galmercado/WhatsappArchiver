import { ApiError, api, onAuthProblem, setCsrf } from "./client";

function respond(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

afterEach(() => {
  vi.restoreAllMocks();
  setCsrf(null);
});

it("sends CSRF only on POST, same-origin credentials, no referrer, no cache", async () => {
  const f = vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(respond(200, { ok: true, csrf_token: null })));
  setCsrf("tok123");
  await api.lock();
  await api.chats({});
  const [post, get] = f.mock.calls;
  expect((post![1]!.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
  expect((get![1]!.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  for (const c of f.mock.calls) {
    expect(c[1]).toMatchObject({ credentials: "same-origin", cache: "no-store", referrerPolicy: "no-referrer" });
  }
});

it("builds query strings safely (encoding, no empty params)", async () => {
  const f = vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(respond(200, { items: [], next_cursor: null })));
  await api.chats({ q: "a&b=c d", archived: false });
  expect(f.mock.calls[0]![0]).toBe("/api/chats?q=a%26b%3Dc+d&archived=false&limit=50");
  await api.search({ q: "x", chatId: 3 });
  expect(f.mock.calls[1]![0]).toBe("/api/search?q=x&chat_id=3&limit=30");
});

it("surfaces server detail and Retry-After without leaking bodies", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(respond(429, { detail: "too many attempts" }, { "Retry-After": "12" })));
  await expect(api.login("p", "123456")).rejects.toMatchObject({ status: 429, message: "too many attempts", retryAfter: 12 });
});

it("401/423 notify listeners; other errors do not", async () => {
  const seen: number[] = [];
  const off = onAuthProblem((s) => seen.push(s));
  const f = vi.spyOn(globalThis, "fetch");
  f.mockResolvedValueOnce(respond(401, { detail: "x" })).mockResolvedValueOnce(respond(423, { detail: "x" })).mockResolvedValueOnce(respond(404, { detail: "x" }));
  for (const id of [1, 2, 3]) await api.chat(id).catch(() => undefined);
  off();
  expect(seen).toEqual([401, 423]);
});

it("network failures become ApiError(0); non-JSON error bodies are tolerated", async () => {
  const f = vi.spyOn(globalThis, "fetch");
  f.mockRejectedValueOnce(new TypeError("boom"));
  await expect(api.status()).rejects.toMatchObject({ status: 0 });
  f.mockResolvedValueOnce(new Response("<html>oops</html>", { status: 502 }));
  const err = await api.status().catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect((err as ApiError).message).toBe("Request failed");
});
