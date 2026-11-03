import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { MobileNav, primaryFor, type NavItem } from "../components/MobileNav";

const Icon = () => null;
const ITEMS: NavItem[] = [
  { to: "/demandes", label: "Demandes", icon: Icon },
  { to: "/lits", label: "Lits et sorties", icon: Icon },
  { to: "/plan-des-lits", label: "Plan des lits", icon: Icon },
  { to: "/urgences", label: "Urgences et tension", icon: Icon, short: "Urgences" },
  { to: "/prevision", label: "Prévision", icon: Icon },
  { to: "/groupe", label: "Vue groupe", icon: Icon },
  { to: "/indicateurs", label: "Indicateurs pilote", icon: Icon },
  { to: "/computer-use", label: "Computer use", icon: Icon }
];

function renderAt(path: string, role = "coordination") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <MobileNav items={ITEMS} primary={primaryFor(role)} />
    </MemoryRouter>
  );
}

describe("MobileNav", () => {
  it("puts each persona's four daily screens under the thumb, the rest behind « Plus »", () => {
    renderAt("/plan-des-lits");
    const bar = screen.getByRole("navigation", { name: "Navigation principale" });
    const links = within(bar).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Plan des lits", "Urgences", "Demandes", "Lits et sorties"]);
    expect(within(bar).getByRole("link", { name: "Plan des lits" })).toHaveAttribute("aria-current", "page");
    expect(within(bar).getByRole("button", { name: "Plus" })).toHaveAttribute("aria-expanded", "false");

    expect(primaryFor("direction")).toEqual(["/urgences", "/groupe", "/prevision", "/indicateurs"]);
  });

  it("opens the other screens in a sheet, marks « Plus » when one of them is open, and closes on choice", async () => {
    renderAt("/computer-use");
    const more = screen.getByRole("button", { name: "Plus" });
    expect(more).toHaveAttribute("data-active", "true");
    await userEvent.click(more);
    const sheet = screen.getByRole("dialog", { name: "Tous les écrans" });
    const names = within(sheet).getAllByRole("link").map((l) => l.textContent);
    expect(names).toEqual(["Prévision", "Vue groupe", "Indicateurs pilote", "Computer use"]);
    expect(within(sheet).getByRole("link", { name: "Computer use" })).toHaveAttribute("aria-current", "page");
    await userEvent.click(within(sheet).getByRole("link", { name: "Prévision" }));
    expect(screen.queryByRole("dialog", { name: "Tous les écrans" })).not.toBeInTheDocument();
  });

  it("closes the sheet with Escape", async () => {
    renderAt("/demandes");
    await userEvent.click(screen.getByRole("button", { name: "Plus" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Tous les écrans" })).not.toBeInTheDocument();
  });
});
