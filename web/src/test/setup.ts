import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// jsdom has no PointerEvent: provide one so pointer coordinates reach React handlers.
if (typeof window.PointerEvent === "undefined") {
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  Object.defineProperty(window, "PointerEvent", { value: PointerEventPolyfill, configurable: true });
}

// jsdom lacks these; components only use them behind feature checks.
if (!("scrollTo" in Element.prototype)) {
  Object.defineProperty(Element.prototype, "scrollTo", { value: () => undefined });
}
