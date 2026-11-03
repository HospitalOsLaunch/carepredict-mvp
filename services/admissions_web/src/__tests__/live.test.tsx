import { act, render, screen } from "@testing-library/react";

import { Freshness, LiveNumber, useChanged } from "../components/live";

function Flag({ value }: { value: string }) {
  return <span>{useChanged(value) ? "changé" : "stable"}</span>;
}

afterEach(() => vi.useRealTimers());

describe("LiveNumber", () => {
  it("says nothing on first display, then shows what changed while you were away", () => {
    vi.useFakeTimers();
    const view = render(<LiveNumber value={27} />);
    expect(screen.getByText("27")).toBeInTheDocument();
    expect(screen.queryByTestId("delta")).not.toBeInTheDocument();

    view.rerender(<LiveNumber value={29} />);
    const delta = screen.getByTestId("delta");
    expect(delta).toHaveTextContent("+2");
    expect(delta).toHaveAttribute("title", "En hausse de 2 depuis la dernière mise à jour");
    expect(screen.getByText("29").closest("[data-changed]")).toHaveAttribute("data-changed", "true");

    view.rerender(<LiveNumber value={26} />);
    expect(screen.getByTestId("delta")).toHaveTextContent("−3");

    // Long enough to be seen after a phone call, then it fades away.
    act(() => vi.advanceTimersByTime(3 * 60_000));
    expect(screen.queryByTestId("delta")).not.toBeInTheDocument();
  });
});

describe("LiveNumber scope", () => {
  it("does not call a filter change a change of the data", () => {
    const view = render(<LiveNumber value={27} scope="all" />);
    view.rerender(<LiveNumber value={2} scope="unit-12" />); // the cadre picked their unit
    expect(screen.queryByTestId("delta")).not.toBeInTheDocument();
    view.rerender(<LiveNumber value={3} scope="unit-12" />); // a bed freed in that unit
    expect(screen.getByTestId("delta")).toHaveTextContent("+1");
    view.rerender(<LiveNumber value={27} scope="all" />);
    expect(screen.queryByTestId("delta")).not.toBeInTheDocument();
  });
});

describe("useChanged", () => {
  it("flags a bed whose status just changed, for a moment only", () => {
    vi.useFakeTimers();
    const view = render(<Flag value="occupe" />);
    expect(screen.getByText("stable")).toBeInTheDocument();
    view.rerender(<Flag value="a_nettoyer" />);
    expect(screen.getByText("changé")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(5000));
    expect(screen.getByText("stable")).toBeInTheDocument();
  });
});

describe("Freshness", () => {
  it("reassures while the data follows the refresh, warns when it is late", () => {
    const now = new Date("2026-11-03T08:10:00Z").getTime();
    const view = render(<Freshness at="2026-11-03T08:09:30Z" staleAfterMs={180_000} now={now} />);
    expect(screen.getByText("À jour")).toBeInTheDocument();
    expect(screen.getByText(/à l'instant/)).toBeInTheDocument();

    view.rerender(<Freshness at="2026-11-03T07:58:00Z" staleAfterMs={180_000} now={now} />);
    expect(screen.getByText("Données en retard")).toBeInTheDocument();
    expect(screen.getByText(/il y a 12 minutes/)).toBeInTheDocument();
  });
});
