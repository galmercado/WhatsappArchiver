import { useCallback, useEffect, useState } from "react";

export interface Route {
  chatId: number | null;
  messageId: number | null;
}

export function parseHash(hash: string): Route {
  // eslint-disable-next-line security/detect-unsafe-regex -- bounded digit runs, anchored
  const m = /^#\/chat\/(\d{1,15})(?:\/m\/(\d{1,15}))?$/.exec(hash);
  return { chatId: m?.[1] ? Number(m[1]) : null, messageId: m?.[2] ? Number(m[2]) : null };
}

export function buildHash(chatId: number | null, messageId?: number | null): string {
  if (chatId === null) return "";
  return messageId ? `#/chat/${chatId}/m/${messageId}` : `#/chat/${chatId}`;
}

export function useRoute(): [Route, (chatId: number | null, messageId?: number | null) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = (): void => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((chatId: number | null, messageId?: number | null): void => {
    const h = buildHash(chatId, messageId);
    if (h === window.location.hash) setRoute(parseHash(h));
    else window.location.hash = h;
  }, []);
  return [route, go];
}
