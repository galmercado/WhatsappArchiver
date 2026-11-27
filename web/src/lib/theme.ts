export type ThemePref = "light" | "dark" | "system";
const KEY = "wa-theme";

export function getThemePref(): ThemePref {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(pref: ThemePref): void {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
}

export function setThemePref(pref: ThemePref): void {
  try {
    if (pref === "system") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, pref);
  } catch {
    /* storage unavailable (private mode): theme still applies for this session */
  }
  applyTheme(pref);
}

export function isDark(): boolean {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr) return attr === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}
