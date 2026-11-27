import { expect, test, type Page } from "@playwright/test";
import { AUTH_FILE, openChat } from "./helpers";

test.use({ storageState: AUTH_FILE });

const bg = (page: Page, sel: string): Promise<string> => page.locator(sel).first().evaluate((e) => getComputedStyle(e).backgroundColor);

test.describe("WhatsApp look and theming", () => {
  test("light palette", async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: AUTH_FILE, colorScheme: "light" });
    const page = await ctx.newPage();
    await openChat(page, 1);
    expect(await bg(page, ".wallpaper")).toBe("rgb(239, 234, 226)"); // #efeae2
    expect(await bg(page, "[data-side=out] >> nth=0")).toBe("rgb(217, 253, 211)"); // #d9fdd3
    expect(await bg(page, "[data-side=in] >> nth=0")).toBe("rgb(255, 255, 255)");
    expect(await page.locator("body").evaluate((b) => getComputedStyle(b).fontFamily)).toMatch(/Segoe UI|Helvetica/);
    await ctx.close();
  });

  test("dark palette follows the OS and can be toggled and persisted", async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: AUTH_FILE, colorScheme: "dark" });
    const page = await ctx.newPage();
    await openChat(page, 1);
    expect(await bg(page, ".wallpaper")).toBe("rgb(11, 20, 26)"); // #0b141a
    expect(await bg(page, "[data-side=out] >> nth=0")).toBe("rgb(0, 92, 75)"); // #005c4b
    expect(await bg(page, "[data-side=in] >> nth=0")).toBe("rgb(32, 44, 51)"); // #202c33
    await page.goto("/");
    await page.getByRole("button", { name: "Menu" }).click();
    await page.getByRole("menuitem", { name: "Light mode" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await openChat(page, 1);
    expect(await bg(page, ".wallpaper")).toBe("rgb(239, 234, 226)");
    await ctx.close();
  });

  test("no external requests and no CSP violations on load", async ({ page }) => {
    const external: string[] = [];
    const violations: string[] = [];
    page.on("request", (r) => {
      if (!r.url().startsWith("http://localhost:8765") && !r.url().startsWith("data:") && !r.url().startsWith("blob:")) external.push(r.url());
    });
    page.on("console", (m) => {
      if (/content security policy|refused to/i.test(m.text())) violations.push(m.text());
    });
    const resp = await page.goto("/");
    expect(resp?.headers()["content-security-policy"]).toContain("default-src 'self'");
    expect(resp?.headers()["cache-control"]).toBe("no-store");
    await openChat(page, 2);
    expect(external).toEqual([]);
    expect(violations).toEqual([]);
  });
});

test.describe("mobile layout", () => {
  test.use({ viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true });

  test("single pane navigation: list → conversation → back", async ({ page }) => {
    await page.goto("/");
    const list = page.getByRole("listbox", { name: "Chats" });
    await expect(list).toBeVisible();
    const w = await list.evaluate((e) => e.getBoundingClientRect().width);
    expect(w).toBeGreaterThan(380); // list uses the full width
    await expect(page.getByTestId("chat-title")).toHaveCount(0);
    await list.getByTestId("chat-1").tap();
    await expect(page.getByTestId("chat-title")).toHaveText("Alice Example");
    await expect(list).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Back to chats" }).tap();
    await expect(list).toBeVisible();
    await page.goBack().catch(() => undefined);
  });

  test("bubbles stay inside the viewport and the footer does not wrap", async ({ page }) => {
    await openChat(page, 2);
    for (const b of await page.locator("[data-testid^=bubble-]").all()) {
      const r = await b.boundingBox();
      expect(r && r.x >= 0 && r.x + r.width <= 390).toBeTruthy();
    }
    const footer = page.locator("footer").first();
    expect((await footer.boundingBox())?.height).toBeLessThan(70);
    await page.getByRole("button", { name: "Search messages" }).tap();
    const panel = page.locator("aside[aria-label='Search messages']");
    expect((await panel.boundingBox())?.width).toBeGreaterThanOrEqual(389); // search takes over the screen on phones
  });
});
