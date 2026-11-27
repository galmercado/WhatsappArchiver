import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { useSession } from "../state/session";
import { LockIcon } from "./Icons";

function Shell({ title, children, notice }: { title: string; children: ReactNode; notice?: string | null }) {
  return (
    <main className="fixed inset-0 overflow-auto" style={{ background: "var(--app-outer)" }}>
      <div className="absolute inset-x-0 top-0 h-[222px]" style={{ background: "var(--app-band)" }} />
      <div className="relative mx-auto mt-10 w-[min(92vw,460px)] rounded-[3px] bg-sidebar p-8 shadow-[0_17px_50px_0_rgba(11,20,26,.19),0_12px_15px_0_rgba(11,20,26,.24)] sm:mt-20 sm:p-10">
        <div className="mb-6 flex items-center gap-3 text-accent-strong">
          <svg width="40" height="40" viewBox="0 0 64 64" aria-hidden="true">
            <rect width="64" height="64" rx="14" fill="currentColor" />
            <path d="M32 14c-10 0-18 7.600-18 17 0 4 1.500 7.700 4 10.600L16 50l9-3c2 .8 4.300 1.200 7 1.200 10 0 18-7.600 18-17S42 14 32 14z" fill="none" stroke="#fff" strokeWidth="4" strokeLinejoin="round" />
          </svg>
          <span className="text-[15px] font-medium uppercase tracking-wide text-ink2">Archive</span>
        </div>
        <h1 className="mb-4 text-[28px] font-light leading-8 text-ink">{title}</h1>
        {notice ? (
          <p role="status" className="mb-4 rounded bg-[color:var(--system-bg)] px-3 py-2 text-[13px] text-[color:var(--system-text)]">
            {notice}
          </p>
        ) : null}
        {children}
        <p className="mt-6 flex items-center gap-1.5 text-[13px] text-ink2">
          <LockIcon size={13} /> Stored encrypted at rest. Nothing leaves your server.
        </p>
      </div>
    </main>
  );
}

const field =
  "w-full rounded-lg border border-line bg-input px-3 py-2.5 text-[15px] text-ink outline-none placeholder:text-ink2 focus:border-accent";
const primary =
  "w-full rounded-full bg-accent px-6 py-2.5 text-[14.5px] font-medium text-white hover:bg-accent-strong disabled:opacity-50";

function errorText(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return `Too many attempts. Try again in ${e.retryAfter ?? 60}s.`;
    if (e.status === 0) return "Cannot reach the server.";
    return fallback;
  }
  return fallback;
}

export function LoginScreen() {
  const { authMode, login, notice } = useSession();
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (authMode === "google") {
    return (
      <Shell title="Sign in to your archive" notice={notice}>
        <p className="mb-5 text-[14px] leading-5 text-ink2">
          Continue with the Google account that owns this archive. You will be asked to sign in again every time.
        </p>
        <a href="/auth/google/start" className={`${primary} block text-center`}>
          Continue with Google
        </a>
      </Shell>
    );
  }

  const submit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(password, totp);
    } catch (x) {
      setErr(errorText(x, "Invalid credentials."));
      setTotp("");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Sign in to your archive" notice={notice}>
      <form onSubmit={(e) => void submit(e)} className="space-y-3" autoComplete="off">
        <label className="block text-[13px] text-ink2">
          Password
          <input className={`${field} mt-1`} type="password" name="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="block text-[13px] text-ink2">
          6-digit code
          <input className={`${field} mt-1 tracking-[0.3em]`} inputMode="numeric" name="totp" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required value={totp} onChange={(e) => setTotp(e.target.value.replace(/\D/g, ""))} />
        </label>
        {err ? <p role="alert" className="text-[13px] text-[#ea0038]">{err}</p> : null}
        <button className={primary} disabled={busy || totp.length !== 6 || !password} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </Shell>
  );
}

export function UnlockScreen() {
  const { unlock, logout, notice } = useSession();
  const [pass, setPass] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await unlock(pass);
    } catch (x) {
      setErr(errorText(x, "That passphrase did not unlock the vault."));
    } finally {
      setPass("");
      setBusy(false);
    }
  };
  return (
    <Shell title="Unlock vault" notice={notice}>
      <p className="mb-4 text-[14px] leading-5 text-ink2">
        Enter the vault passphrase you chose when the archive was created. The key is held in server memory only until you lock the vault.
      </p>
      <form onSubmit={(e) => void submit(e)} className="space-y-3" autoComplete="off">
        <label className="block text-[13px] text-ink2">
          Vault passphrase
          <input className={`${field} mt-1`} type="password" name="passphrase" autoComplete="off" required autoFocus value={pass} onChange={(e) => setPass(e.target.value)} />
        </label>
        {err ? <p role="alert" className="text-[13px] text-[#ea0038]">{err}</p> : null}
        <button className={primary} disabled={busy || !pass} type="submit">
          {busy ? "Unlocking…" : "Unlock"}
        </button>
        <button type="button" className="w-full py-2 text-[14px] text-accent-strong hover:underline" onClick={() => void logout()}>
          Sign out
        </button>
      </form>
    </Shell>
  );
}

export function FatalScreen() {
  return (
    <Shell title="Cannot reach the server">
      <p className="text-[14px] text-ink2">Check that the archive server is running, then reload this page.</p>
    </Shell>
  );
}
