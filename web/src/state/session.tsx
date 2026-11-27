import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, onAuthProblem, setCsrf } from "../api/client";
import type { AuthMode } from "../api/types";

export type Phase = "loading" | "login" | "unlock" | "ready" | "error";

interface SessionApi {
  phase: Phase;
  authMode: AuthMode | null;
  notice: string | null;
  login: (password: string, totp: string) => Promise<void>;
  unlock: (passphrase: string) => Promise<void>;
  lock: () => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<SessionApi | null>(null);

export function useSession(): SessionApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("SessionProvider missing");
  return v;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const s = await api.status();
      if (!alive.current) return;
      setAuthMode(s.auth_mode);
      setCsrf(s.csrf_token);
      setPhase(!s.authenticated ? "login" : s.vault_unlocked ? "ready" : "unlock");
    } catch {
      if (alive.current) setPhase("error");
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const failed = new URLSearchParams(window.location.search).get("login") === "failed";
    if (failed) {
      setNotice("Google sign-in was rejected. Make sure you use the configured account.");
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    }
    void refresh();
    const off = onAuthProblem((status) => {
      setNotice(status === 423 ? "The vault was locked." : "Your session has ended. Please sign in again.");
      void refresh();
    });
    return () => {
      alive.current = false;
      off();
    };
  }, [refresh]);

  const value = useMemo<SessionApi>(
    () => ({
      phase,
      authMode,
      notice,
      login: async (password, totp) => {
        const r = await api.login(password, totp);
        setCsrf(r.csrf_token);
        setNotice(null);
        await refresh();
      },
      unlock: async (passphrase) => {
        await api.unlock(passphrase);
        setNotice(null);
        await refresh();
      },
      lock: async () => {
        try {
          await api.lock();
        } catch (e) {
          if (!(e instanceof ApiError) || e.status !== 401) throw e;
        }
        setCsrf(null);
        window.location.hash = "";
        setNotice("Vault locked. Keys were purged from server memory.");
        await refresh();
      },
      logout: async () => {
        try {
          await api.logout();
        } catch {
          /* already logged out */
        }
        setCsrf(null);
        window.location.hash = "";
        setNotice(null);
        await refresh();
      },
    }),
    [phase, authMode, notice, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
