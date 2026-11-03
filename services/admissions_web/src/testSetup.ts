import "@testing-library/jest-dom/vitest";

// jsdom has no PointerEvent: without it, a dragged window would receive no coordinates.
if (typeof window !== "undefined" && !("PointerEvent" in window)) {
  class PointerEventShim extends MouseEvent {
    pointerId: number;
    pointerType: string;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
      this.pointerType = init.pointerType ?? "mouse";
    }
  }
  Object.assign(window, { PointerEvent: PointerEventShim });
}
