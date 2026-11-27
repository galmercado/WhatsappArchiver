import { render, screen } from "@testing-library/react";
import { emojiOnlyCount, renderRich, safeHref } from "./richtext";

const XSS = [
  "<script>window.__xss=1</script>",
  '<img src=x onerror="window.__xss=1">',
  "<svg onload=window.__xss=1>",
  '"><iframe src="javascript:window.__xss=1"></iframe>',
  "javascript:window.__xss=1",
  "<a href='javascript:window.__xss=1'>x</a>",
  "&lt;b&gt;entities&lt;/b&gt;",
];

describe("hostile message bodies render as inert text", () => {
  it.each(XSS)("%s", (payload) => {
    const { container } = render(<p>{renderRich(payload)}</p>);
    expect(container.querySelector("script,img,svg,iframe,object,embed,style")).toBeNull();
    expect(container.querySelector("[onerror],[onload],[onclick]")).toBeNull();
    expect(container.textContent).toBe(payload); // shown literally, never interpreted
    expect((window as unknown as Record<string, unknown>).__xss).toBeUndefined();
  });

  it("does not turn javascript:/data: URLs into links", () => {
    const { container } = render(<p>{renderRich("click javascript:alert(1) or data:text/html,<b>x</b>")}</p>);
    expect(container.querySelector("a")).toBeNull();
  });
});

describe("links", () => {
  it("linkifies only http(s) and adds rel/target hardening", () => {
    render(<p>{renderRich("see https://example.com/a?b=1, and http://x.test.")}</p>);
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["https://example.com/a?b=1", "http://x.test/"]);
    for (const l of links) {
      expect(l).toHaveAttribute("target", "_blank");
      expect(l.getAttribute("rel")).toBe("noopener noreferrer nofollow");
    }
  });
  it("safeHref rejects other schemes and garbage", () => {
    expect(safeHref("https://a.b")).toBe("https://a.b/");
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "ftp://x", "not a url", "//evil"]) expect(safeHref(bad)).toBeNull();
  });
});

describe("formatting", () => {
  it("bold, italic, strike, monospace", () => {
    const { container } = render(<p>{renderRich("*b* _i_ ~s~ `m` plain")}</p>);
    expect(container.querySelector("strong")?.textContent).toBe("b");
    expect(container.querySelector("em")?.textContent).toBe("i");
    expect(container.querySelector("s")?.textContent).toBe("s");
    expect(container.querySelector("code")?.textContent).toBe("m");
    expect(container.textContent).toBe("b i s m plain");
  });
  it("leaves intra-word markers alone", () => {
    const { container } = render(<p>{renderRich("snake_case_name and 2*3*4")}</p>);
    expect(container.querySelector("em,strong")).toBeNull();
  });
  it("code spans stay literal", () => {
    const { container } = render(<p>{renderRich("`*not bold*`")}</p>);
    expect(container.querySelector("strong")).toBeNull();
    expect(container.textContent).toBe("*not bold*");
  });
});

describe("search highlighting", () => {
  it("wraps matches in <mark>, case-insensitively, without changing text", () => {
    const { container } = render(<p>{renderRich("Hello hello HELLO world", ["hello"])}</p>);
    expect(container.querySelectorAll("mark.hit")).toHaveLength(3);
    expect(container.textContent).toBe("Hello hello HELLO world");
  });
  it("treats regex metacharacters in terms literally", () => {
    const { container } = render(<p>{renderRich("a.b a+b (x) [y]", [".", "+", "(", "["])}</p>);
    expect(container.querySelectorAll("mark.hit").length).toBe(4);
    expect(container.textContent).toBe("a.b a+b (x) [y]");
  });
  it("highlights inside formatted and linked text", () => {
    const { container } = render(<p>{renderRich("*bold match* https://match.example", ["match"])}</p>);
    expect(container.querySelectorAll("mark.hit").length).toBe(2);
  });
});

describe("emoji-only detection", () => {
  it("counts 1–3 emoji", () => {
    expect(emojiOnlyCount("👍")).toBe(1);
    expect(emojiOnlyCount("👨‍👩‍👧 🎉")).toBe(2);
    expect(emojiOnlyCount("👍🏽")).toBe(1);
  });
  it("is 0 for mixed text", () => {
    expect(emojiOnlyCount("hi 👍")).toBe(0);
    expect(emojiOnlyCount("")).toBe(0);
  });
});
