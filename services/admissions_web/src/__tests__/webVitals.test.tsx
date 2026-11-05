import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { Metric } from "web-vitals";

import { setToken } from "../api/client";
import { deviceClass, pageTemplate, startWebVitals, type VitalOut } from "../lib/webVitals";

vi.mock("../api/client", async (real) => {
  const mod = await real<typeof import("../api/client")>();
  return { ...mod, api: vi.fn() };
});
import { api } from "../api/client";
import { VitalsTab } from "../pages/VitalsSettings";

type Report = (m: Metric) => void;

function fakeVitals() {
  const on: Record<string, Report> = {};
  const register = (name: string) => (cb: Report) => {
    on[name] = cb;
  };
  return {
    on,
    load: async () => ({
      onLCP: register("LCP"),
      onINP: register("INP"),
      onCLS: register("CLS"),
      onFCP: register("FCP"),
      onTTFB: register("TTFB")
    })
  };
}

const metric = (name: Metric["name"], value: number) => ({ name, value }) as Metric;

function hide() {
  Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
}

describe("webVitals", () => {
  afterEach(() => {
    setToken(null);
    window.history.replaceState(null, "", "/");
  });

  it("never sends an id: a screen is reduced to its route template", () => {
    expect(pageTemplate("/demandes/4512")).toBe("/demandes/:id");
    expect(pageTemplate("/agents/passages/12/")).toBe("/agents/passages/:id");
    expect(pageTemplate("/plan-des-lits")).toBe("/plan-des-lits");
    expect(pageTemplate("/patients/Martin")).toBe("autre");
    expect([deviceClass(390), deviceClass(820), deviceClass(1440)]).toEqual(["mobile", "tablette", "bureau"]);
  });

  it("sends the measures of the visit to the group's API when the tab is put aside", async () => {
    const vitals = fakeVitals();
    const send = vi.fn<(v: VitalOut[], token: string) => void>();
    setToken("jeton-de-session");
    await startWebVitals({ load: vitals.load, send, landing: "/plan-des-lits" });

    window.history.replaceState(null, "", "/demandes/4512");
    vitals.on.LCP(metric("LCP", 1200));
    vitals.on.INP(metric("INP", 180));
    hide();

    expect(send).toHaveBeenCalledTimes(1);
    const [batch, token] = send.mock.calls[0];
    expect(token).toBe("jeton-de-session");
    // The load is measured on the screen it opened; the reaction on the screen shown.
    expect(batch.map((v) => [v.metric, v.value, v.page])).toEqual([
      ["LCP", 1200, "/plan-des-lits"],
      ["INP", 180, "/demandes/:id"]
    ]);
    expect(JSON.stringify(batch)).not.toContain("4512");

    hide();
    expect(send).toHaveBeenCalledTimes(1); // nothing left to send
  });

  it("keeps the measures of the login page until a session exists", async () => {
    const vitals = fakeVitals();
    const send = vi.fn<(v: VitalOut[], token: string) => void>();
    await startWebVitals({ load: vitals.load, send, landing: "/" });
    vitals.on.LCP(metric("LCP", 900));
    hide();
    expect(send).not.toHaveBeenCalled();

    setToken("jeton-de-session");
    hide();
    expect(send.mock.calls[0][0]).toEqual([expect.objectContaining({ metric: "LCP", page: "/" })]);
  });

  it("never breaks the application when the measuring library cannot load", async () => {
    await expect(startWebVitals({ load: () => Promise.reject(new Error("réseau coupé")), send: vi.fn() })).resolves.toBeUndefined();
  });
});

describe("VitalsTab", () => {
  function renderTab() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <VitalsTab />
      </QueryClientProvider>
    );
  }

  it("shows each screen's 75th percentile with its rating", async () => {
    vi.mocked(api).mockResolvedValue({
      days: 28,
      samples: 60,
      rows: [
        { page: "/plan-des-lits", metric: "LCP", p75: 1240, samples: 40, rating: "bon" },
        { page: "/plan-des-lits", metric: "INP", p75: 320, samples: 12, rating: "a_ameliorer" },
        { page: "/lits", metric: "CLS", p75: 0.31, samples: 8, rating: "mauvais" }
      ]
    } as never);
    renderTab();

    const row = (await screen.findByRole("rowheader", { name: "Plan des lits" })).closest("tr")!;
    expect(within(row).getByText("1,2 s")).toBeInTheDocument();
    expect(within(row).getByText("bon")).toBeInTheDocument();
    expect(within(row).getByText("320 ms")).toBeInTheDocument();
    expect(within(row).getByText("à améliorer")).toBeInTheDocument();
    const lits = screen.getByRole("rowheader", { name: "Lits et sorties" }).closest("tr")!;
    expect(within(lits).getByText("0,31")).toBeInTheDocument();
    expect(within(lits).getByText("mauvais")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/web-vitals?days=28");
  });

  it("says when no visit has been measured yet", async () => {
    vi.mocked(api).mockResolvedValue({ days: 28, samples: 0, rows: [] } as never);
    renderTab();
    expect(await screen.findByText("Pas encore de mesure")).toBeInTheDocument();
  });
});
