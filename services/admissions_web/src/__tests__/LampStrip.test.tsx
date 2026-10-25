import { fireEvent, render, screen } from "@testing-library/react";

import { LampStrip, lampState } from "../components/LampStrip";

const days = [
  { day: "2026-10-25", free_expected: 2.4, prob_at_least_one_free: 0.93 },
  { day: "2026-10-26", free_expected: 1.1, prob_at_least_one_free: 0.6 },
  { day: "2026-10-27", free_expected: 0.2, prob_at_least_one_free: 0.15 }
];

describe("lampState", () => {
  it("is safe from 80 %, probable when one bed is expected, off otherwise", () => {
    expect(days.map(lampState)).toEqual(["sur", "probable", "eteint"]);
  });
});

describe("LampStrip", () => {
  it("describes every day for screen readers", () => {
    render(<LampStrip days={days} />);
    expect(screen.getByText(/dimanche 25 octobre : lit sûr, 2 lits libres attendus/)).toBeInTheDocument();
    expect(screen.getByText(/mardi 27 octobre : aucun lit prévu, 0 lit libre attendu/)).toBeInTheDocument();
  });

  it("lets the coordinator pick a day", () => {
    const onPick = vi.fn();
    render(<LampStrip days={days} onPick={onPick} />);
    fireEvent.click(screen.getAllByRole("button")[1]);
    expect(onPick).toHaveBeenCalledWith("2026-10-26");
  });
});
