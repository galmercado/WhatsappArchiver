import { expect, test } from "@playwright/test";
import { AUTH_FILE, openAt, openChat } from "./helpers";

test.use({ storageState: AUTH_FILE });

test.describe("reading a conversation", () => {
  test("hostile message bodies are shown as text and nothing executes", async ({ page }) => {
    const dialogs: string[] = [];
    page.on("dialog", (d) => {
      dialogs.push(d.message());
      void d.dismiss();
    });
    const cspErrors: string[] = [];
    page.on("console", (m) => {
      if (/content security policy/i.test(m.text())) cspErrors.push(m.text());
    });
    await openAt(page, 1, 4);
    await expect(page.getByText("<script>alert(1)</script>")).toBeVisible();
    await expect(page.getByText('<img src=x onerror="alert(document.cookie)">')).toBeVisible();
    await expect(page.getByText("javascript:alert(1)")).toBeVisible();
    expect(await page.locator("[data-msg-id] script, [data-msg-id] img[src='x'], [data-msg-id] iframe").count()).toBe(0);
    expect(await page.locator("a[href^='javascript:']").count()).toBe(0);
    expect(dialogs).toEqual([]);
    expect(cspErrors).toEqual([]);
  });

  test("renders bubbles, ticks, quoted reply, documents and voice notes", async ({ page }) => {
    await openAt(page, 1, 2);
    await expect(page.getByTestId("chat-title")).toHaveText("Alice Example");
    const bubble = (id: number) => page.getByTestId(`bubble-${id}`);
    await expect(bubble(2)).toHaveAttribute("data-side", "out");
    await expect(bubble(2).getByRole("img", { name: "Read" })).toBeVisible();
    await openAt(page, 1, 15);
    await expect(bubble(15).getByRole("button", { name: /Hello from Alice/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Download report.pdf/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Play voice message" })).toBeVisible();
    await expect(page.getByRole("img", { name: "real photo" })).toBeVisible();
    await expect.poll(() => page.getByRole("img", { name: "real photo" }).evaluate((i: HTMLImageElement) => i.naturalWidth)).toBeGreaterThan(0);
  });

  test("group chat shows participant names and system events", async ({ page }) => {
    await openChat(page, 2);
    await expect(page.getByTestId("chat-title")).toHaveText("Test Group");
    await expect(page.getByTestId("sender-name").first()).toBeVisible();
    await expect(page.getByText("Carol", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("carol-wa was added")).toBeVisible();
  });

  test("lightbox opens, navigates with the keyboard and closes", async ({ page }) => {
    await openChat(page, 1); // latest page includes the real photo
    await page.getByRole("button", { name: "Open photo" }).last().click();
    const dialog = page.getByRole("dialog", { name: "Media viewer" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("img")).toHaveAttribute("src", /\/api\/media\/\d+/);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("voice note streams with HTTP Range (206)", async ({ page }) => {
    await openAt(page, 1, 13);
    const resp = page.waitForResponse((r) => /\/api\/media\/13$/.test(r.url()));
    await page.getByRole("button", { name: "Play voice message" }).click();
    const r = await resp;
    expect(r.request().headers()["range"]).toMatch(/^bytes=\d+-/);
    expect([200, 206]).toContain(r.status());
    expect(r.headers()["accept-ranges"]).toBe("bytes");
    expect(r.headers()["cache-control"]).toBe("no-store");
  });

  test("media endpoint refuses traversal and unknown ids", async ({ page, request }) => {
    await openChat(page, 1);
    for (const p of ["/api/media/..%2f..%2fetc%2fpasswd", "/api/media/16", "/api/media/999999"]) {
      const r = await request.get(p);
      expect([404, 422]).toContain(r.status());
    }
    const ok = await request.get("/api/media/12", { headers: { Range: "bytes=0-3" } });
    expect(ok.status()).toBe(206);
    expect((await ok.body()).length).toBe(4);
  });
});

test.describe("search and navigation", () => {
  test("in-chat search highlights, jumps to the message and flashes it", async ({ page }) => {
    await openChat(page, 1);
    await page.getByRole("button", { name: "Search messages" }).click();
    await page.getByLabel("Search in this chat").fill("hello");
    const hit = page.getByTestId("hit-1");
    await expect(hit).toBeVisible();
    await expect(hit.locator("mark.hit").first()).toHaveText(/hello/i);
    await hit.click();
    await expect(page).toHaveURL(/#\/chat\/1\/m\/1$/);
    const target = page.locator('[data-msg-id="1"]');
    await expect(target).toBeVisible();
    await expect(target.locator("mark.hit").first()).toBeVisible();
    await expect(target).toHaveClass(/msg-flash/);
  });

  test("syntax-injection queries never break search", async ({ page }) => {
    await openChat(page, 1);
    await page.getByRole("button", { name: "Search messages" }).click();
    const box = page.getByLabel("Search in this chat");
    for (const q of ['"', "NEAR(", "*", "' OR 1=1 --", "a AND NOT b", "col:foo"]) {
      await box.fill(q);
      await expect(page.getByRole("alert")).toHaveCount(0);
      await expect(page.locator("aside[aria-label='Search messages']")).toBeVisible();
    }
    await box.fill("Hello");
    await expect(page.getByTestId("hit-1")).toBeVisible(); // still healthy afterwards
  });

  test("sidebar filters chats by name and phone, and finds messages globally", async ({ page }) => {
    await page.goto("/");
    const list = page.getByRole("listbox", { name: "Chats" });
    await expect(list.getByTestId("chat-1")).toBeVisible();
    const search = page.getByLabel("Search or filter chats");
    await search.fill("alice");
    await expect(list.getByTestId("chat-2")).toHaveCount(0);
    await expect(list.getByTestId("chat-1")).toBeVisible();
    await search.fill("15550100102");
    await expect(page.getByText("No chats, contacts or messages found")).toBeVisible();
    await search.fill("CANARY");
    const hit = page.getByRole("region", { name: "Messages" }).getByTestId("hit-1");
    await expect(hit).toBeVisible();
    await hit.click();
    await expect(page).toHaveURL(/#\/chat\/1\/m\/1$/);
    await expect(page.locator('[data-msg-id="1"]')).toBeVisible();
  });
});
