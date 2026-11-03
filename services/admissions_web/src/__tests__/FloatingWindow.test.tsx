import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { FloatingWindow } from "../components/FloatingWindow";

beforeEach(() => {
  localStorage.clear();
  Object.assign(window, { innerWidth: 1440, innerHeight: 900 });
});

function open(onClose = vi.fn()) {
  render(
    <>
      <button type="button">Revoir</button>
      <FloatingWindow title="Gestion des lits" titleId="w-title" onClose={onClose} storageKey="test.window" initialSize={{ w: 800, h: 600 }}>
        <button type="button">Lecture</button>
      </FloatingWindow>
    </>
  );
  return { win: screen.getByRole("dialog", { name: "Gestion des lits" }), onClose };
}

const at = (el: HTMLElement) => ({ x: parseInt(el.style.left, 10), y: parseInt(el.style.top, 10) });

describe("FloatingWindow", () => {
  it("opens centred over the page, which stays usable behind it, and takes the focus", () => {
    const { win } = open();
    expect(win).toHaveAttribute("aria-modal", "false");
    expect(at(win)).toEqual({ x: 320, y: 150 });
    expect(win).toHaveFocus();
    expect(screen.getByRole("button", { name: "Revoir" })).toBeInTheDocument(); // not hidden behind a modal
  });

  it("closes with its button or with Escape", async () => {
    const { onClose } = open();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Fermer le player" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("follows the pointer when its header is dragged, and keeps the header on screen", () => {
    const { win } = open();
    const handle = screen.getByTestId("window-handle");
    fireEvent.pointerDown(handle, { clientX: 400, clientY: 170, button: 0, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 500, clientY: 270, pointerId: 1 });
    fireEvent.pointerUp(handle, { pointerId: 1 });
    expect(at(win)).toEqual({ x: 420, y: 250 });

    fireEvent.pointerDown(handle, { clientX: 500, clientY: 270, button: 0, pointerId: 2 });
    fireEvent.pointerMove(handle, { clientX: 5000, clientY: -900, pointerId: 2 });
    fireEvent.pointerUp(handle, { pointerId: 2 });
    expect(at(win)).toEqual({ x: 1440 - 140, y: 0 });
    // Remembered on this device.
    expect(JSON.parse(localStorage.getItem("test.window") ?? "{}")).toMatchObject({ x: 1300, y: 0 });
  });

  it("never goes below the bottom edge, so the player controls stay visible", () => {
    const { win } = open();
    const handle = screen.getByTestId("window-handle");
    fireEvent.pointerDown(handle, { clientX: 400, clientY: 170, button: 0, pointerId: 3 });
    fireEvent.pointerMove(handle, { clientX: 400, clientY: 2000, pointerId: 3 });
    fireEvent.pointerUp(handle, { pointerId: 3 });
    expect(at(win).y).toBe(900 - 600 - 12);
  });

  it("does not start a drag from a button of the header", () => {
    const { win } = open();
    const close = screen.getByRole("button", { name: "Agrandir la fenêtre" });
    fireEvent.pointerDown(close, { clientX: 400, clientY: 170, button: 0, pointerId: 1 });
    fireEvent.pointerMove(screen.getByTestId("window-handle"), { clientX: 600, clientY: 400, pointerId: 1 });
    expect(at(win)).toEqual({ x: 320, y: 150 });
  });

  it("moves with the arrow keys on its handle and recentres with Début (no drag needed)", async () => {
    const { win } = open();
    const handle = screen.getByRole("button", { name: /Déplacer la fenêtre/ });
    handle.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}{ArrowDown}");
    expect(at(win)).toEqual({ x: 384, y: 182 });
    await userEvent.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    expect(at(win)).toEqual({ x: 288, y: 182 });
    await userEvent.keyboard("{Home}");
    expect(at(win)).toEqual({ x: 320, y: 150 });
  });

  it("enlarges to the screen and back", async () => {
    const { win } = open();
    await userEvent.click(screen.getByRole("button", { name: "Agrandir la fenêtre" }));
    expect(win.style.left).toBe("");
    expect(screen.queryByRole("button", { name: /Déplacer la fenêtre/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restaurer la taille de la fenêtre" }));
    expect(at(win)).toEqual({ x: 320, y: 150 });
  });
});
