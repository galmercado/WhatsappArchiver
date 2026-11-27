import { fireEvent, render, screen, within } from "@testing-library/react";
import { media, msg, NOW } from "../test/factories";
import { MessageBubble, type BubbleProps } from "./MessageBubble";

function show(m = msg(), over: Partial<BubbleProps> = {}) {
  const props: BubbleProps = { m, prev: null, isGroup: false, terms: [], flash: false, onOpenMedia: vi.fn(), onJump: vi.fn(), now: NOW, ...over };
  return { ...render(<MessageBubble {...props} />), props };
}

describe("incoming vs outgoing", () => {
  it("places and styles bubbles per side", () => {
    show(msg({ id: 1 }));
    expect(screen.getByTestId("bubble-1")).toHaveAttribute("data-side", "in");
    expect(screen.getByTestId("bubble-1")).toHaveClass("bubble-in", "tail-in");
    show(msg({ id: 2, from_me: true, status: 3 }));
    expect(screen.getByTestId("bubble-2")).toHaveAttribute("data-side", "out");
    expect(screen.getByTestId("bubble-2")).toHaveClass("bubble-out", "tail-out");
  });
  it("only the first bubble of a run gets a tail", () => {
    const a = msg({ id: 1 });
    show(msg({ id: 2 }), { prev: a });
    expect(screen.getByTestId("bubble-2")).not.toHaveClass("tail-in");
  });
  it("a different sender or side restarts the run", () => {
    const a = msg({ id: 1, sender_id: "a" });
    show(msg({ id: 2, sender_id: "b" }), { prev: a });
    expect(screen.getByTestId("bubble-2")).toHaveClass("tail-in");
  });
});

describe("ticks", () => {
  it.each([
    [0, "Pending"], [1, "Sent"], [2, "Delivered"], [3, "Read"],
  ])("status %i → %s", (status, label) => {
    show(msg({ from_me: true, status }));
    expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
  });
  it("incoming messages never show ticks", () => {
    show(msg({ from_me: false, status: null }));
    expect(screen.queryByRole("img", { name: /sent|delivered|read|pending/i })).toBeNull();
  });
  it("read ticks are blue, others grey", () => {
    show(msg({ from_me: true, status: 3 }));
    expect(screen.getByRole("img", { name: "Read" })).toHaveStyle({ color: "var(--tick-blue)" });
  });
});

describe("date dividers", () => {
  it("shows a chip on the first message and when the day changes", () => {
    const day1 = msg({ id: 1, ts: NOW - 2 * 86_400_000 });
    const { container } = show(msg({ id: 2, ts: NOW }), { prev: day1 });
    expect(container).toHaveTextContent("Today");
    const { container: c2 } = show(msg({ id: 4, ts: NOW - 1000 }), { prev: msg({ id: 3, ts: NOW - 2000 }) });
    expect(c2).not.toHaveTextContent("Today");
    const { container: c3 } = show(msg({ id: 5, ts: NOW - 86_400_000 }));
    expect(c3).toHaveTextContent("Yesterday");
  });
});

describe("group chats", () => {
  it("shows the sender name in their colour on the first message only", () => {
    show(msg({ id: 1, sender_name: "Bob Example", color_idx: 3 }), { isGroup: true });
    const name = screen.getByTestId("sender-name");
    expect(name).toHaveTextContent("Bob Example");
    expect(name).toHaveStyle({ color: "var(--c3)" });
    show(msg({ id: 2, sender_name: "Bob Example", color_idx: 3 }), { isGroup: true, prev: msg({ id: 1 }) });
    expect(screen.getAllByTestId("sender-name")).toHaveLength(1);
  });
  it("never labels your own messages or 1:1 chats", () => {
    show(msg({ from_me: true }), { isGroup: true });
    show(msg({ id: 9 }), { isGroup: false });
    expect(screen.queryByTestId("sender-name")).toBeNull();
  });
  it("renders group system events as centred chips", () => {
    show(msg({ type: "system", system_kind: "added", system_target_name: "Carol", sender_name: "Alice", text: null }));
    expect(screen.getByText("Alice added Carol")).toBeInTheDocument();
    show(msg({ id: 2, type: "system", system_kind: "removed", system_target_name: "Carol", sender_name: null, text: null }));
    expect(screen.getByText("Carol was removed")).toBeInTheDocument();
  });
});

describe("quoted replies", () => {
  it("shows the preview and jumps to the original when clicked", () => {
    const { props } = show(msg({ from_me: true, text: "yes", quoted: { message_id: 42, text: "Are you coming?", sender_name: "Alice", type: "text" } }));
    const quote = screen.getByRole("button", { name: /Are you coming/ });
    expect(quote).toHaveTextContent("Alice");
    fireEvent.click(quote);
    expect(props.onJump).toHaveBeenCalledWith(42);
  });
  it("renders hostile quoted text as text", () => {
    const { container } = show(msg({ quoted: { message_id: 1, text: "<img src=x onerror=alert(1)>", sender_name: "<b>x</b>", type: "text" } }));
    expect(container.querySelector("img,b")).toBeNull();
  });
});

describe("XSS safety of message bodies", () => {
  const payloads = ['<script>window.__x=1</script>', '<img src=x onerror="window.__x=1">', "javascript:window.__x=1", "<svg/onload=window.__x=1>"];
  it.each(payloads)("%s is inert", (p) => {
    const { container } = show(msg({ text: p }));
    expect(container.querySelector("script,img,svg,iframe")).toBeNull();
    expect(container).toHaveTextContent(p);
    expect((window as unknown as Record<string, unknown>).__x).toBeUndefined();
  });
  it("hostile sender names and file names are text too", () => {
    const { container } = show(msg({ sender_name: '<img src=x onerror=1>', text: "t" }), { isGroup: true });
    expect(container.querySelector("img")).toBeNull();
    show(msg({ id: 2, type: "document", text: null, media: media({ mime: "application/pdf", file_name: '"><script>1</script>.pdf' }) }));
    expect(document.querySelector("script")).toBeNull();
  });
});

describe("search highlighting", () => {
  it("marks matches without altering the text", () => {
    const { container } = show(msg({ text: "Find the needle in the haystack needle" }), { terms: ["needle"] });
    expect(container.querySelectorAll("mark.hit")).toHaveLength(2);
    expect(container).toHaveTextContent("Find the needle in the haystack needle");
  });
});

describe("text details", () => {
  it("emoji-only messages are large", () => {
    const { container } = show(msg({ text: "😂" }));
    expect(container.querySelector(".text-\\[34px\\]")).not.toBeNull();
    const { container: c2 } = show(msg({ id: 2, text: "😂 haha" }));
    expect(c2.querySelector(".text-\\[34px\\]")).toBeNull();
  });
  it("auto-detects direction for RTL text", () => {
    const { container } = show(msg({ text: "مرحبا שלום" }));
    expect(container.querySelector("[dir=auto]")).not.toBeNull();
  });
  it("deleted messages are labelled", () => {
    show(msg({ type: "deleted", text: null }));
    expect(screen.getByText("This message was deleted")).toBeInTheDocument();
  });
  it("timestamp is a semantic <time>", () => {
    const { container } = show(msg({ ts: NOW }));
    expect(container.querySelector("time")?.getAttribute("datetime")).toBe(new Date(NOW).toISOString());
  });
});

describe("media", () => {
  it("photo opens the viewer", () => {
    const { props } = show(msg({ id: 7, type: "image", text: "caption", media: media() }));
    fireEvent.click(screen.getByRole("button", { name: "Open photo" }));
    expect(props.onOpenMedia).toHaveBeenCalledWith(7);
    expect(screen.getByRole("img", { name: "caption" })).toHaveAttribute("src", "/api/media/1");
    expect(screen.getByRole("img", { name: "caption" })).toHaveAttribute("loading", "lazy");
  });
  it("a broken image falls back to a placeholder", () => {
    show(msg({ type: "image", text: null, media: media() }));
    fireEvent.error(screen.getByRole("img", { name: "Photo" }));
    expect(screen.getByText("Media not available")).toBeInTheDocument();
  });
  it("unavailable media shows a placeholder", () => {
    show(msg({ type: "image", text: "x", media: media({ available: false, url: null }) }));
    expect(screen.getByText("Media not available")).toBeInTheDocument();
  });
  it("video uses a native, range-streamed <video>", () => {
    const { container } = show(msg({ type: "video", text: null, media: media({ mime: "video/mp4", url: "/api/media/3" }) }));
    const v = container.querySelector("video");
    expect(v).toHaveAttribute("src", "/api/media/3");
    expect(v).toHaveAttribute("preload", "metadata");
  });
  it("documents show name, type, size and a download link", () => {
    show(msg({ type: "document", text: null, media: media({ mime: "application/pdf", file_name: "report.pdf", size_bytes: 1536, url: "/api/media/9" }) }));
    const link = screen.getByRole("link", { name: /Download report.pdf/ });
    expect(link).toHaveAttribute("href", "/api/media/9");
    expect(link).toHaveAttribute("download", "report.pdf");
    expect(within(link).getByText("report.pdf")).toBeInTheDocument();
    expect(link).toHaveTextContent("PDF · 1.5 KB");
  });
  it("voice notes render the custom player, not a raw <audio controls>", () => {
    const { container } = show(msg({ type: "ptt", text: null, media: media({ mime: "audio/ogg", duration_s: 3, url: "/api/media/5" }) }));
    expect(screen.getByRole("button", { name: "Play voice message" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Seek voice message" })).toBeInTheDocument();
    expect(container.querySelector("audio[controls]")).toBeNull();
    expect(screen.getByText("0:03")).toBeInTheDocument();
  });
  it("flash highlight class is applied to the jump target", () => {
    const { container } = show(msg({ id: 4 }), { flash: true });
    expect(container.querySelector(".msg-flash")).not.toBeNull();
  });
});
