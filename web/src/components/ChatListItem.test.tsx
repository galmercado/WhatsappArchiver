import { fireEvent, render, screen } from "@testing-library/react";
import { chat, NOW } from "../test/factories";
import { ChatListItem } from "./ChatListItem";

const DAY = 86_400_000;
const show = (c = chat(), selected = false) => {
  const onOpen = vi.fn();
  render(<ChatListItem chat={c} selected={selected} onOpen={onOpen} now={NOW} />);
  return onOpen;
};

it("shows title, preview and time; opens on click", () => {
  const open = show();
  expect(screen.getByText("Alice Example")).toBeInTheDocument();
  expect(screen.getByText("see you")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("option"));
  expect(open).toHaveBeenCalledWith(1);
});

it.each([
  [NOW - DAY, "Yesterday"],
  [NOW - 2 * DAY, "Wednesday"],
  [NOW - 40 * DAY, "10/18/2026"],
])("timestamp %i → %s", (ts, label) => {
  show(chat({ last_message_ts: ts }));
  expect(screen.getByText(label)).toBeInTheDocument();
});

it("falls back to a media label and icon when there is no text", () => {
  show(chat({ last_message: { text: null, type: "ptt", from_me: false, ts: NOW } }));
  expect(screen.getByText("Voice message")).toBeInTheDocument();
});

it("own last message gets ticks; selection is exposed to AT", () => {
  show(chat({ last_message: { text: "ok", type: "text", from_me: true, ts: NOW } }), true);
  expect(screen.getByRole("img", { name: "Read" })).toBeInTheDocument();
  expect(screen.getByRole("option")).toHaveAttribute("aria-selected", "true");
});

it("hostile chat titles and previews are plain text", () => {
  const { container } = render(<ChatListItem chat={chat({ title: "<img src=x onerror=1>", last_message: { text: "<script>1</script>", type: "text", from_me: false, ts: NOW } })} selected={false} onOpen={vi.fn()} now={NOW} />);
  expect(container.querySelector("img,script")).toBeNull();
  expect(container).toHaveTextContent("<img src=x onerror=1>");
});
