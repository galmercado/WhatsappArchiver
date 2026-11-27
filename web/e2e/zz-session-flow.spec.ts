import { expect, request as pwRequest, test } from "@playwright/test";
import { AUTH_FILE, PASSWORD, PASSPHRASE, loginUi, nextTotp, unlockUi, wrongTotp } from "./helpers";

// The read-only specs leave the vault unlocked (it is server-wide). Lock it so this spec can
// exercise the real unlock path; this also proves Lock Vault kills the earlier sessions.
test.beforeAll(async ({ baseURL }) => {
  const api = await pwRequest.newContext({ baseURL, storageState: AUTH_FILE, extraHTTPHeaders: { Origin: String(baseURL) } });
  const st = (await (await api.get("/auth/status")).json()) as { csrf_token: string };
  expect((await api.post("/vault/lock", { headers: { "X-CSRF-Token": st.csrf_token }, data: {} })).ok()).toBe(true);
  expect((await api.get("/api/chats", { failOnStatusCode: false })).status()).toBe(401);
  await api.dispose();
});

// No shared storage state: this spec performs the real login → unlock → browse → lock journey.
test("login → unlock vault → browse → lock vault", async ({ page, context }) => {
  const request = context.request; // shares the browser's cookies, like the page itself
  // anonymous visitors only ever see the login screen, and the API refuses them
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to your archive" })).toBeVisible();
  expect((await request.get("/api/chats", { failOnStatusCode: false })).status()).toBe(401);
  expect((await request.get("/api/media/12", { failOnStatusCode: false })).status()).toBe(401);

  // a wrong second factor gives a generic error and no session
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByLabel("6-digit code").fill(wrongTotp());
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Invalid credentials.");
  expect((await context.cookies()).filter((c) => c.name.includes("session"))).toHaveLength(0);

  // real login; cookie is HttpOnly + SameSite=Strict and invisible to scripts
  await loginUi(page);
  await expect(page.getByRole("heading", { name: "Unlock vault" })).toBeVisible();
  const cookie = (await context.cookies()).find((c) => c.name === "wa_session");
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Strict" });
  expect(await page.evaluate(() => document.cookie)).toBe("");
  expect((await request.get("/api/chats", { failOnStatusCode: false })).status()).toBe(423); // signed in but vault locked

  // wrong passphrase is refused; the right one unlocks
  await page.getByLabel("Vault passphrase").fill("definitely-wrong-passphrase");
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByRole("alert")).toContainText("did not unlock");
  await unlockUi(page);

  // browse
  await page.getByTestId("chat-1").click();
  await expect(page.getByTestId("chat-title")).toHaveText("Alice Example");
  await expect(page.locator("[data-msg-id]").first()).toBeVisible();
  expect((await request.get("/api/chats")).status()).toBe(200);

  // lock vault: keys purged, session destroyed, everything refused, UI back at sign-in
  await page.goto("/");
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Lock vault" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to your archive" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Vault locked");
  expect((await request.get("/api/chats", { failOnStatusCode: false })).status()).toBe(401);
  expect((await request.get("/api/media/12", { failOnStatusCode: false })).status()).toBe(401);
  expect(await page.evaluate(() => document.body.innerText)).not.toContain("Alice Example");

  // back/forward must not resurrect decrypted content
  await page.goto("/#/chat/1");
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.locator("[data-msg-id]")).toHaveCount(0);

  // and a full re-login + unlock still works afterwards
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByLabel("6-digit code").fill(await nextTotp());
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Vault passphrase").fill(PASSPHRASE);
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.locator("[data-msg-id]").first()).toBeVisible();
});
