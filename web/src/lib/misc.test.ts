import { buildHash, parseHash } from "./route";
import { applyTheme, getThemePref, isDark, setThemePref } from "./theme";
import { waveformBars } from "./waveform";

describe("hash routes", () => {
  it("round-trips", () => {
    expect(parseHash("#/chat/12")).toEqual({ chatId: 12, messageId: null });
    expect(parseHash("#/chat/12/m/345")).toEqual({ chatId: 12, messageId: 345 });
    expect(parseHash(buildHash(7, 9))).toEqual({ chatId: 7, messageId: 9 });
    expect(buildHash(null)).toBe("");
  });
  it.each(["", "#", "#/chat/", "#/chat/abc", "#/chat/1/m/", "#/chat/-1", "#/chat/1/../2", "#/chat/1234567890123456", "#/x/1", "#/chat/1/m/2/extra"])("rejects %s", (h) => {
    expect(parseHash(h)).toEqual({ chatId: null, messageId: null });
  });
});

describe("theme", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });
  it("persists and applies explicit choices; system removes the attribute", () => {
    setThemePref("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(getThemePref()).toBe("dark");
    expect(isDark()).toBe(true);
    setThemePref("light");
    expect(isDark()).toBe(false);
    setThemePref("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(getThemePref()).toBe("system");
  });
  it("ignores junk in storage", () => {
    window.localStorage.setItem("wa-theme", "<script>");
    expect(getThemePref()).toBe("system");
  });
  it("survives unavailable storage", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => setThemePref("dark")).not.toThrow();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    spy.mockRestore();
    applyTheme("system");
  });
});

describe("waveform", () => {
  it("is deterministic per id and bounded", () => {
    expect(waveformBars(5)).toEqual(waveformBars(5));
    expect(waveformBars(5)).not.toEqual(waveformBars(6));
    for (const h of waveformBars(99, 60)) {
      expect(h).toBeGreaterThanOrEqual(0.15);
      expect(h).toBeLessThanOrEqual(1);
    }
    expect(waveformBars(1, 12)).toHaveLength(12);
  });
});
