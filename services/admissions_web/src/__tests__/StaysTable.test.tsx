import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Stay } from "../api/types";
import { StaysTable, VIRTUALIZE_FROM } from "../pages/BedsPage";

vi.mock("../api/client", () => ({ api: vi.fn(async () => ({})) }));

function stays(n: number): Stay[] {
  return Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    site_id: 1,
    site_name: "Les Saules",
    mention: "polyvalent",
    patient_ref: `P-${String(i + 1).padStart(4, "0")}`,
    admission_date: "2026-10-01",
    planned_discharge_date: null,
    discharge_date: null,
    length_of_stay: 30 + i,
    care_level: 2,
    prob_within_7_days: 1 - i / n, // P-0001 first, P-0120 last
    median_discharge_day: null,
    plan_changes: 0
  }));
}

function renderTable(n: number) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StaysTable stays={stays(n)} canWrite />
    </QueryClientProvider>
  );
}

const drawn = () => document.querySelectorAll("tbody tr[data-index]");

// jsdom lays nothing out: a row is given the height it has in a browser.
const offsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");
beforeAll(() => {
  window.scrollTo = vi.fn() as typeof window.scrollTo; // jsdom does not scroll
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      return (this as HTMLElement).tagName === "TR" ? 87 : 0;
    }
  });
});
afterAll(() => {
  if (offsetHeight) Object.defineProperty(HTMLElement.prototype, "offsetHeight", offsetHeight);
});
afterEach(() => {
  Object.defineProperty(window, "scrollY", { value: 0, configurable: true, writable: true });
});

function scrollTo(y: number) {
  act(() => {
    Object.defineProperty(window, "scrollY", { value: y, configurable: true, writable: true });
    window.dispatchEvent(new Event("scroll"));
  });
}

describe("StaysTable", () => {
  it("draws every row of a small site", () => {
    renderTable(VIRTUALIZE_FROM - 1);
    expect(drawn()).toHaveLength(VIRTUALIZE_FROM - 1);
    expect(screen.queryByLabelText("Rechercher un patient présent")).not.toBeInTheDocument();
  });

  it("draws only the rows on screen for 120 patients, and says how many there are", () => {
    renderTable(120);
    expect(drawn().length).toBeGreaterThan(5);
    expect(drawn().length).toBeLessThan(25);
    expect(screen.getByRole("table")).toHaveAttribute("aria-rowcount", "121");
    expect(screen.getByText("P-0001")).toBeInTheDocument();
    expect(screen.queryByText("P-0120")).not.toBeInTheDocument();

    scrollTo(120 * 87);
    expect(screen.getByText("P-0120")).toBeInTheDocument();
    expect(screen.queryByText("P-0001")).not.toBeInTheDocument();
    const last = screen.getByText("P-0120").closest("tr")!;
    expect(last).toHaveAttribute("aria-rowindex", "121");
  });

  it("finds a patient that is off screen, since the browser's search no longer can", async () => {
    renderTable(120);
    await userEvent.type(screen.getByLabelText("Rechercher un patient présent"), "P-0117");
    expect(drawn()).toHaveLength(1);
    expect(screen.getByText("P-0117")).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveAttribute("aria-rowcount", "2");
  });

  it("keeps a planned date typed and not saved when its row leaves the screen", () => {
    renderTable(120);
    const input = screen.getByLabelText("Sortie prévue de P-0001");
    fireEvent.change(input, { target: { value: "2026-11-12" } });
    expect(within(input.closest("tr")!).getByRole("button", { name: "Enregistrer" })).toBeInTheDocument();

    scrollTo(120 * 87);
    // Still drawn (it is being edited), with what was typed.
    expect(screen.getByLabelText("Sortie prévue de P-0001")).toHaveValue("2026-11-12");
    expect(screen.getByText("P-0120")).toBeInTheDocument();
  });
});
