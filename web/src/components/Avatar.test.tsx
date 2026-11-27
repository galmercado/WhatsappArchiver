import { fireEvent, render, screen } from "@testing-library/react";
import { chat, NOW } from "../test/factories";
import { Avatar } from "./Icons";
import { ChatListItem } from "./ChatListItem";

describe("Avatar", () => {
  it("shows the silhouette when there is no picture", () => {
    const { container } = render(<Avatar group={false} />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(screen.queryByTestId("avatar-img")).toBeNull();
  });

  it("layers the picture over the silhouette, lazily loaded and decorative", () => {
    render(<Avatar group={false} src="/api/avatars/7" />);
    const img = screen.getByTestId("avatar-img");
    expect(img).toHaveAttribute("src", "/api/avatars/7");
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("draggable", "false");
  });

  it("falls back to the silhouette when the picture fails to load", () => {
    const { container } = render(<Avatar group src="/api/avatars/7" />);
    fireEvent.error(screen.getByTestId("avatar-img"));
    expect(screen.queryByTestId("avatar-img")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("is used by the chat list", () => {
    render(<ChatListItem chat={chat({ avatar_url: "/api/avatars/3" })} selected={false} onOpen={vi.fn()} now={NOW} />);
    expect(screen.getByTestId("avatar-img")).toHaveAttribute("src", "/api/avatars/3");
  });
});
