import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ForecastDay, ForecastSeries, LiscopForecast } from "../api/types_liscop";
import { levelOf, PrevisionPage } from "../pages/PrevisionPage";

vi.mock("../api/client", () => ({ api: vi.fn() }));
import { api } from "../api/client";

function day(k: number, mean: number, pTension: number | null = null, pCritique: number | null = null): ForecastDay {
  return {
    day: `2026-11-0${k + 1}`,
    horizon: `J+${k}`,
    mean,
    q10: Math.max(0, mean - 2),
    q50: mean,
    q90: mean + 3,
    p_tension: pTension,
    p_critique: pCritique
  };
}

function series(target: ForecastSeries["target"], label: string, values: ForecastDay[], extra = {}): ForecastSeries {
  return {
    scope: "unit",
    scope_key: "pool:2",
    label,
    site_id: 1,
    pool_id: 2,
    target,
    beds_installed: 36,
    model: null,
    fallback: null,
    values,
    recent: [],
    ...extra
  };
}

const week = (f: (k: number) => ForecastDay) => Array.from({ length: 8 }, (_, k) => f(k));

const sample: LiscopForecast = {
  scope: "unit",
  targets: ["available_beds", "arrivals"],
  run: {
    id: 3,
    as_of: "2026-11-01",
    created_at: "2026-11-01T05:00:00Z",
    model_version: "liscop-forecast-1.0",
    horizon_days: 8,
    age_hours: 2.2,
    stale: false,
    models_chosen: { AutoETS: 6, AutoTheta: 2 },
    fallback_series: 0,
    common_shock_variance: 0.004
  },
  last_failure_at: null,
  restricted_to_site: null,
  synthetic: true,
  series: [
    series(
      "available_beds",
      "Médecine polyvalente",
      week((k) => day(k, k === 2 ? 0 : 6, k === 2 ? 0.95 : 0.2, k === 2 ? 0.7 : 0))
    ),
    series(
      "arrivals",
      "Médecine polyvalente",
      week((k) => day(k, 5.7)),
      { model: "AutoETS", fallback: false }
    )
  ],
  backtest: null,
  notes: ["Disponibles attendus = lits ouverts − patients présents − promesses + sorties − arrivées."]
};

const boarding: LiscopForecast = {
  ...sample,
  scope: "site",
  targets: ["boarding_10h"],
  series: [
    series(
      "boarding_10h",
      "CH Deux-Rivières",
      week((k) => day(k, 4)),
      {
        scope: "site",
        scope_key: "site:1",
        model: "AutoTheta",
        recent: [{ day: "2026-10-31", value: 3 }]
      }
    )
  ]
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PrevisionPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(api).mockImplementation(
    async (path: string) => (path.includes("boarding_10h") ? boarding : sample) as never
  );
});

describe("PrevisionPage", () => {
  it("shows expected available beds per unit with the range and the tension level", async () => {
    renderPage();
    const row = await screen.findByRole("row", { name: /Médecine polyvalente/ });
    const cells = within(row).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("5,7"); // arrivals expected tomorrow
    expect(cells[2]).toHaveTextContent(/^64 à 9\s*Normal · risque 20/); // J+1: mean 6, range, level
    expect(cells[3]).toHaveTextContent(/Critique · risque 95/); // J+2: no bed in most scenarios
    expect(screen.getByRole("columnheader", { name: "Disponibles J+7" })).toBeInTheDocument();
    // Table from the sm breakpoint, cards below: both carry the seven-day strip.
    for (const strip of screen.getAllByLabelText("Sept jours, Médecine polyvalente")) {
      expect(strip.children).toHaveLength(7);
    }
    const card = within(screen.getByRole("list", { name: "Lits disponibles attendus par unité" }));
    expect(card.getByText(/Arrivées attendues demain/)).toHaveTextContent("5,7 (4 à 9)");
  });

  it("says the forecast is computed on synthetic demo data and explains the formula", async () => {
    renderPage();
    expect(await screen.findByRole("note")).toHaveTextContent(/données de démonstration synthétiques/);
    expect(screen.getByText(/libérés − arrivées non programmées − promesses/)).toBeInTheDocument();
    expect(screen.getByText(/il y a 2 h/)).toBeInTheDocument();
    expect(screen.getByText(/AutoETS \(6\)/)).toBeInTheDocument();
  });

  it("charts boarding at 10:00 with its model", async () => {
    renderPage();
    expect(await screen.findByRole("img", { name: /Lits brancards à 10 h, CH Deux-Rivières/ })).toBeInTheDocument();
    expect(screen.getByText(/Modèle : AutoTheta/)).toBeInTheDocument();
  });

  it("switches scale and asks the API for it", async () => {
    renderPage();
    await screen.findByRole("row", { name: /Médecine polyvalente/ });
    await userEvent.click(screen.getByRole("button", { name: "GHT" }));
    expect(screen.getByRole("button", { name: "GHT" })).toHaveAttribute("aria-pressed", "true");
    expect(vi.mocked(api)).toHaveBeenCalledWith("/forecast/liscop?scope=ght");
  });

  it("has a clear empty state before the first run", async () => {
    vi.mocked(api).mockResolvedValue({ ...sample, run: null, series: [] } as never);
    renderPage();
    expect(await screen.findByText("Aucune prévision calculée pour l'instant")).toBeInTheDocument();
  });
});

describe("levelOf", () => {
  it("picks the most likely LISCOP level", () => {
    expect(levelOf(day(1, 0, 0.9, 0.6))).toBe("critique");
    expect(levelOf(day(1, 2, 0.6, 0.1))).toBe("tension");
    expect(levelOf(day(1, 9, 0.2, 0))).toBe("normal");
  });
});
