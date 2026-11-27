import { createHmac } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Page } from "@playwright/test";

export const PASSWORD = "e2e-Password-12345";
export const PASSPHRASE = "correct horse battery staple";
const SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
const STATE = join(tmpdir(), "wa-e2e-totp-last");
export const AUTH_FILE = join(tmpdir(), "wa-e2e-auth.json");

function b32(s: string): Buffer {
  const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s) bits += A.indexOf(c).toString(2).padStart(5, "0");
  const out: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}

function hotp(counter: number): string {
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = createHmac("sha1", b32(SECRET)).update(buf).digest();
  const o = (h[19] ?? 0) & 15;
  const n = (((h[o] ?? 0) & 0x7f) << 24) | ((h[o + 1] ?? 0) << 16) | ((h[o + 2] ?? 0) << 8) | (h[o + 3] ?? 0);
  return String(n % 1_000_000).padStart(6, "0");
}

/** A valid TOTP the server has not seen yet (it rejects replays of an already-used time step). */
export async function nextTotp(): Promise<string> {
  for (;;) {
    const now = Math.floor(Date.now() / 30_000);
    const last = existsSync(STATE) ? Number(readFileSync(STATE, "utf8")) : 0;
    const use = Math.max(now, last + 1);
    if (use <= now + 1) {
      writeFileSync(STATE, String(use));
      return hotp(use);
    }
    await new Promise((r) => setTimeout(r, 1000)); // wait for the next step to open
  }
}
export const wrongTotp = (): string => hotp(Math.floor(Date.now() / 30_000) + 40);

export async function loginUi(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByLabel("6-digit code").fill(await nextTotp());
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function unlockUi(page: Page): Promise<void> {
  await page.getByLabel("Vault passphrase").fill(PASSPHRASE);
  await page.getByRole("button", { name: "Unlock" }).click();
  await page.getByRole("listbox", { name: "Chats" }).waitFor();
}

/** Open a chat centred on a message (the list is virtualized, so only nearby rows exist in the DOM). */
export const openAt = async (page: Page, chat: number, messageId: number): Promise<void> => {
  await page.goto(`/#/chat/${chat}/m/${messageId}`);
  await page.locator(`[data-msg-id="${messageId}"]`).waitFor();
};

export const openChat = async (page: Page, id: number): Promise<void> => {
  await page.goto(`/#/chat/${id}`);
  await page.locator("[data-msg-id]").first().waitFor();
};
