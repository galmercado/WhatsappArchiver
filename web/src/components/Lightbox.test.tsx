import { fireEvent, render, screen } from "@testing-library/react";
import { media, msg, NOW } from "../test/factories";
import { Lightbox } from "./Lightbox";

const items = [1, 2, 3].map((id) => msg({ id, type: "image", ts: NOW, media: media({ url: `/api/media/${id}` }), text: `cap ${id}` }));

function setup(index = 1) {
  const onIndex = vi.fn();
  const onClose = vi.fn();
  render(<Lightbox items={items} index={index} onIndex={onIndex} onClose={onClose} />);
  return { onIndex, onClose };
}

it("is an accessible modal that focuses the close button", () => {
  setup();
  expect(screen.getByRole("dialog", { name: "Media viewer" })).toHaveAttribute("aria-modal", "true");
  expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
});

it("shows the current photo, its sender and caption", () => {
  setup();
  expect(screen.getByRole("img", { name: "cap 2" })).toHaveAttribute("src", "/api/media/2");
  expect(screen.getByText("Alice Example")).toBeInTheDocument();
  expect(screen.getAllByText("cap 2").length).toBeGreaterThan(0);
});

it("keyboard: Escape closes, arrows navigate within bounds", () => {
  const { onIndex, onClose } = setup(1);
  fireEvent.keyDown(window, { key: "ArrowRight" });
  expect(onIndex).toHaveBeenLastCalledWith(2);
  fireEvent.keyDown(window, { key: "ArrowLeft" });
  expect(onIndex).toHaveBeenLastCalledWith(0);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onClose).toHaveBeenCalled();
});

it("does not navigate past the ends", () => {
  const { onIndex } = setup(0);
  fireEvent.keyDown(window, { key: "ArrowLeft" });
  expect(onIndex).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Previous" })).toBeNull();
});

it("clicking the backdrop closes but clicking the image does not", () => {
  const { onClose } = setup();
  fireEvent.click(screen.getByRole("img", { name: "cap 2" }));
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("dialog"));
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("offers a same-origin download link", () => {
  setup();
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/media/2");
});
