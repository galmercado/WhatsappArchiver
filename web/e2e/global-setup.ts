import { request, type FullConfig } from "@playwright/test";
import { AUTH_FILE, PASSPHRASE, PASSWORD, nextTotp } from "./helpers";

/** One real login + unlock shared by the read-only specs. The final flow spec logs in on its own. */
export default async function setup(config: FullConfig): Promise<void> {
  const base = String(config.projects[0]?.use.baseURL);
  const ctx = await request.newContext({ baseURL: base, extraHTTPHeaders: { Origin: base } });
  const login = await ctx.post("/auth/login", { data: { password: PASSWORD, totp: await nextTotp() } });
  if (!login.ok()) throw new Error(`setup login failed: ${login.status()}`);
  const csrf = ((await login.json()) as { csrf_token: string }).csrf_token;
  const unlock = await ctx.post("/vault/unlock", { data: { passphrase: PASSPHRASE }, headers: { "X-CSRF-Token": csrf } });
  if (!unlock.ok()) throw new Error(`setup unlock failed: ${unlock.status()}`);
  await ctx.storageState({ path: AUTH_FILE });
  await ctx.dispose();
}
