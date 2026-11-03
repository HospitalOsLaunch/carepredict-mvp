import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/common";
import { cn } from "@/lib/utils";

describe("shadcn/ui primitives on the HospitalOS tokens", () => {
  it("merge classes, the design tokens included: a later radius or shadow wins", () => {
    expect(cn("rounded-xl px-4", "rounded-chip")).toBe("px-4 rounded-chip");
    expect(cn("shadow-md", false && "hidden", "shadow-lift")).toBe("shadow-lift");
  });

  it("give a router link the button look with asChild, and keep 44 px touch targets", () => {
    render(
      <MemoryRouter>
        <Button asChild variant="dark">
          <Link to="/agents/passages/7">Regarder en direct</Link>
        </Button>
      </MemoryRouter>
    );
    const link = screen.getByRole("link", { name: "Regarder en direct" });
    expect(link).toHaveAttribute("href", "/agents/passages/7");
    expect(link).toHaveClass("bg-ink", "text-white", "rounded-chip", "touch-target");
    render(<Badge tone="coral-solid">À reprendre</Badge>);
    expect(screen.getByText("À reprendre")).toHaveClass("bg-coral-dark", "text-white");
  });

  it("Modal traps the focus, hides the page behind and closes with Escape", async () => {
    const onClose = vi.fn();
    render(
      <>
        <button type="button">Derrière</button>
        <Modal title="Bloquer le lit" onClose={onClose}>
          <label>
            Motif <input />
          </label>
        </Modal>
      </>
    );
    const dialog = screen.getByRole("dialog", { name: "Bloquer le lit" });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(screen.queryByRole("button", { name: "Derrière" })).not.toBeInTheDocument(); // aria-hidden
    await userEvent.tab();
    await userEvent.tab();
    expect(dialog).toContainElement(document.activeElement as HTMLElement); // focus stays inside
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
