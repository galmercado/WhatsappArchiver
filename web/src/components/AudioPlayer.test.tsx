import { fireEvent, render, screen } from "@testing-library/react";
import { AudioPlayer } from "./AudioPlayer";

beforeEach(() => {
  const setPaused = (el: HTMLMediaElement, v: boolean): void => {
    Object.defineProperty(el, "paused", { value: v, configurable: true });
  };
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    setPaused(this, false);
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
    setPaused(this, true);
    this.dispatchEvent(new Event("pause"));
  });
});
afterEach(() => vi.restoreAllMocks());

const setup = (id = 1) => render(<AudioPlayer id={id} url={`/api/media/${id}`} durationHint={10} outgoing={false} />);

it("toggles play/pause and updates the label", () => {
  setup();
  fireEvent.click(screen.getByRole("button", { name: "Play voice message" }));
  expect(screen.getByRole("button", { name: "Pause voice message" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Pause voice message" }));
  expect(screen.getByRole("button", { name: "Play voice message" })).toBeInTheDocument();
});

it("only one voice note plays at a time", () => {
  const { container: a } = setup(1);
  const { container: b } = setup(2);
  const [btnA] = Array.from(a.querySelectorAll("button"));
  const [btnB] = Array.from(b.querySelectorAll("button"));
  fireEvent.click(btnA!);
  fireEvent.click(btnB!);
  expect(a.querySelector("button")).toHaveAttribute("aria-label", "Play voice message");
  expect(b.querySelector("button")).toHaveAttribute("aria-label", "Pause voice message");
});

it("keyboard scrubbing moves the playhead", () => {
  const { container } = setup();
  const audio = container.querySelector("audio")!;
  Object.defineProperty(audio, "duration", { value: 10, configurable: true });
  fireEvent.loadedMetadata(audio);
  const slider = screen.getByRole("slider");
  fireEvent.keyDown(slider, { key: "ArrowRight" });
  fireEvent.keyDown(slider, { key: "ArrowRight" });
  expect(audio.currentTime).toBe(4);
  fireEvent.keyDown(slider, { key: "ArrowLeft" });
  expect(audio.currentTime).toBe(2);
  expect(slider).toHaveAttribute("aria-valuenow", "2");
});

it("pointer scrubbing seeks proportionally and clamps", () => {
  const { container } = setup();
  const audio = container.querySelector("audio")!;
  Object.defineProperty(audio, "duration", { value: 10, configurable: true });
  const slider = screen.getByRole("slider");
  slider.getBoundingClientRect = () => ({ left: 100, width: 200, top: 0, height: 28, right: 300, bottom: 28, x: 100, y: 0, toJSON: () => ({}) });
  slider.setPointerCapture = vi.fn();
  fireEvent.pointerDown(slider, { clientX: 200, pointerId: 1 });
  expect(audio.currentTime).toBeCloseTo(5);
  fireEvent.pointerMove(slider, { clientX: 5000, pointerId: 1 });
  expect(audio.currentTime).toBeCloseTo(10);
  fireEvent.pointerUp(slider, { pointerId: 1 });
  fireEvent.pointerMove(slider, { clientX: 100, pointerId: 1 });
  expect(audio.currentTime).toBeCloseTo(10); // no drag => no seek
});

it("cycles playback speed and reports load errors", () => {
  const { container } = setup();
  const audio = container.querySelector("audio")!;
  const speed = screen.getByRole("button", { name: /Playback speed/ });
  fireEvent.click(speed);
  expect(audio.playbackRate).toBe(1.5);
  fireEvent.click(screen.getByRole("button", { name: "Playback speed 1.5x" }));
  expect(audio.playbackRate).toBe(2);
  fireEvent.error(audio);
  expect(screen.getByText("Audio unavailable")).toBeInTheDocument();
});

it("streams lazily: preload=none so nothing is fetched until played", () => {
  const { container } = setup();
  expect(container.querySelector("audio")).toHaveAttribute("preload", "none");
});

it("ignores non-finite pointer positions instead of throwing", () => {
  const { container } = setup();
  const audio = container.querySelector("audio")!;
  Object.defineProperty(audio, "duration", { value: 10, configurable: true });
  const slider = screen.getByRole("slider");
  slider.getBoundingClientRect = () => ({ left: 0, width: 0, top: 0, height: 0, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}) });
  slider.setPointerCapture = vi.fn();
  expect(() => fireEvent.pointerDown(slider, { clientX: 50, pointerId: 1 })).not.toThrow();
  expect(audio.currentTime).toBe(0);
});
