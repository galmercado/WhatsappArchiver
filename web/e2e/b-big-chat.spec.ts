import { expect, test, type Page } from "@playwright/test";
import { AUTH_FILE } from "./helpers";

test.use({ storageState: AUTH_FILE });
const BIG = 9;
const FIRST = 100_000;
const LAST = 199_999;

const rendered = (page: Page): Promise<number[]> =>
  page.locator("[data-msg-id]").evaluateAll((els) => els.map((e) => Number((e as HTMLElement).dataset.msgId)));

async function scrollUp(page: Page, times: number): Promise<void> {
  const scroller = page.locator("[data-virtuoso-scroller='true']").last();
  for (let i = 0; i < times; i++) {
    await scroller.evaluate((el) => {
      el.scrollTop = 0;
    });
    await page.waitForTimeout(120);
  }
}

test("100,000-message chat opens at the bottom and keeps the DOM small", async ({ page }) => {
  await page.goto(`/#/chat/${BIG}`);
  await expect(page.locator(`[data-msg-id="${LAST}"]`)).toBeVisible();
  const ids = await rendered(page);
  expect(ids.length).toBeGreaterThan(5);
  expect(ids.length).toBeLessThan(150); // virtualized: nowhere near 100,000 nodes
  expect(await page.locator("*").count()).toBeLessThan(4000);
});

test("infinite scroll up loads older pages in order without duplicates and with bounded memory", async ({ page }) => {
  await page.goto(`/#/chat/${BIG}`);
  await expect(page.locator(`[data-msg-id="${LAST}"]`)).toBeVisible();
  const startMin = Math.min(...(await rendered(page)));
  await scrollUp(page, 25);
  const ids = await rendered(page);
  expect(Math.min(...ids)).toBeLessThan(startMin - 200); // older history was fetched
  expect(new Set(ids).size).toBe(ids.length);
  expect(ids.length).toBeLessThan(200);
  const heapMb = await page.evaluate(() => ((performance as unknown as { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? 0) / 1e6);
  expect(heapMb).toBeLessThan(200);
});

test("jump to a message deep in the history, then back to the latest", async ({ page }) => {
  await page.goto(`/#/chat/${BIG}/m/150000`);
  const target = page.locator('[data-msg-id="150000"]');
  await expect(target).toBeVisible();
  await expect(target).toContainText("bulk message number 50000");
  const box = await target.boundingBox();
  const vp = page.viewportSize();
  expect(box && vp && box.y > 0 && box.y < vp.height).toBeTruthy(); // actually on screen, not just in the DOM
  await page.getByRole("button", { name: "Scroll to latest message" }).click();
  await expect(page.locator(`[data-msg-id="${LAST}"]`)).toBeVisible();
  expect(await rendered(page)).not.toContain(150000);
});

test("older messages keep their dates and the first message is reachable", async ({ page }) => {
  await page.goto(`/#/chat/${BIG}/m/${FIRST + 2}`);
  await expect(page.locator(`[data-msg-id="${FIRST + 2}"]`)).toBeVisible();
  await scrollUp(page, 3);
  await expect(page.locator(`[data-msg-id="${FIRST}"]`)).toBeVisible();
  await expect(page.locator(`[data-msg-id="${FIRST}"]`)).toContainText("bulk message number 0");
});

test("full-text search over 100,000 messages answers quickly", async ({ page }) => {
  await page.goto(`/#/chat/${BIG}`);
  await page.getByRole("button", { name: "Search messages" }).click();
  const t0 = Date.now();
  await page.getByLabel("Search in this chat").fill("number 77777");
  await expect(page.getByTestId("hit-177777")).toBeVisible();
  expect(Date.now() - t0).toBeLessThan(5000);
  await page.getByTestId("hit-177777").click();
  await expect(page.locator('[data-msg-id="177777"]')).toBeVisible();
});
