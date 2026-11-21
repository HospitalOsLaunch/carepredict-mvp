import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { WorldModel } from "./WorldModel";
import { worldApi, type WmContext, type WmSession } from "../api/worldModel";

const contexts: WmContext[] = [
  { id: "complet", label: "Établissement A", feed: "full", ward_count: 2 },
  { id: "partiel", label: "Établissement B", feed: "partial", ward_count: 2 },
  { id: "retarde", label: "Établissement C", feed: "delayed", ward_count: 2 },
];
const reference = "Maintenir les affectations";
const porter = "Transport vers Médecine";
const cleaner = "Bionettoyage en Gériatrie";

function sample(id: string, c: WmContext): WmSession {
  return {
    id, context: c, phase: "planning", hour: 12, decision_hour: 12, target_hour: 16, publication_hour: c.feed === "delayed" ? 18 : 16,
    model_version: "essai-1", morning_plan: ["Transport affecté à la gériatrie"],
    wards: [{ id: "med", label: "Médecine", beds: 20 }, { id: "ger", label: "Gériatrie", beds: 30 }],
    reference_id: "ref", selected_id: null,
    options: [reference, porter, cleaner].map((label, i) => ({
      id: ["ref", "port", "clean"][i]!, label, kind: (["reference", "transport", "cleaning"] as const)[i]!,
      ward_id: [null, "med", "ger"][i]!, forecast: 5-i, jepa_forecast: 5-i+.2, by_ward: [3-i, 2],
      reconstruction: null, reconstructed_by_ward: null,
    })), observation: null, journal: [{ hour: 12, event: "opened", option_id: null }],
  };
}
const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });

function fakeBackend(extraOptions: WmSession["options"] = []) {
  const states = new Map<string, WmSession>();
  const calls: Array<{ method: string; path: string; body?: Record<string, unknown> }> = [];
  let failedConfirm = false;
  const serve = async (input: string | URL | Request, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
    calls.push({ method, path, body });
    if (path === "/api/world-model/contexts") return json({ contexts, model_version: "essai-1" });
    const matched = path.match(/^\/api\/world-model\/sessions\/([^/]+)(?:\/(confirm|advance))?$/);
    if (!matched) return json({ detail: "Chemin inconnu" }, 404);
    const id = matched[1]!;
    if (method === "PUT" && !states.has(id)) {
      const who = contexts.find((c) => c.id === body?.context_id)!;
      const next = sample(id, who);
      next.options.push(...extraOptions.map((o) => ({ ...o })));
      states.set(id, next);
    }
    const s = states.get(id);
    if (!s) return json({ detail: "Parcours inconnu" }, 404);
    if (matched[2] === "confirm") {
      if (failedConfirm) return json({ detail: "Une autre session a déjà validé ce choix." }, 409);
      s.selected_id = String(body?.option_id);
      s.phase = "confirmed";
      s.journal.push({ hour: 12, event: "confirmed", option_id: s.selected_id });
    } else if (matched[2] === "advance") {
      if (body?.from_hour === 12 && s.context.feed === "delayed") {
        s.phase = "awaiting_report"; s.hour = 16;
        s.journal.push({ hour: 16, event: "awaiting_report", option_id: s.selected_id });
      } else {
        s.phase = "review"; s.hour = s.publication_hour;
        const partial = s.context.feed === "partial";
        s.observation = { sample_hour: 16, published_hour: s.hour, by_ward: [0, partial ? null : 2],
          observed_stock: partial ? null : 2, visible_components: partial ? 4 : 7, total_components: 10 };
        for (const [j,o] of s.options.entries()) { o.reconstruction = 3+j; o.reconstructed_by_ward = [1+j,2]; }
        s.journal.push({ hour: s.hour, event: "report_received", option_id: s.selected_id });
      }
    }
    return json(s);
  };
  vi.stubGlobal("fetch", vi.fn(serve));
  return { states, calls, rejectConfirm: () => { failedConfirm = true; } };
}

beforeEach(() => { window.localStorage.clear(); });
afterEach(() => { vi.unstubAllGlobals(); });

const start = () => screen.findByRole("radio", { name: porter });
async function validate(label = porter) {
  fireEvent.click(await screen.findByRole("radio", { name: label }));
  fireEvent.click(screen.getByRole("button", { name: "Valider en simulation" }));
  await screen.findByText("Affectation validée en simulation");
}

describe("simulation d’affectation", () => {
  it("enregistre une seule validation, différencie l’observé du contrefactuel et relit le journal après rechargement", async () => {
    const api = fakeBackend();
    const first = render(<WorldModel />);
    fireEvent.click(await start());
    expect((screen.getByRole("button", { name: "Avancer à 16 h" }) as HTMLButtonElement).disabled).toBe(true);
    const confirm = screen.getByRole("button", { name: "Valider en simulation" });
    fireEvent.click(confirm); fireEvent.click(confirm);
    await screen.findByText("Affectation validée en simulation");
    expect(api.calls.filter((c) => c.path.endsWith("/confirm"))).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Comparaison après relevé" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Avancer à 16 h" }));
    const observed = await screen.findByRole("region", { name: "Comparaison après relevé" });
    expect(within(observed).getByText(/7 composantes du relevé publiées sur 10/)).toBeTruthy();
    expect(within(observed).queryByText(/total observé reste inconnu/)).toBeNull();
    const options = within(observed).getByRole("combobox");
    expect(within(options).queryByRole("option", { name: porter })).toBeNull();
    fireEvent.change(options, { target: { value: "clean" } });
    expect((options as HTMLSelectElement).value).toBe("clean");
    expect(within(observed).getByText(cleaner, { selector: "small" })).toBeTruthy();
    const oldId = [...api.states.keys()][0];
    first.unmount();
    render(<WorldModel />);
    await screen.findByRole("region", { name: "Comparaison après relevé" });
    expect(api.calls.some((c) => c.path.endsWith(String(oldId)) && c.method === "GET")).toBe(true);
    expect(api.states.size).toBe(1);
    const journal = screen.getByRole("region", { name: "Journal du parcours" });
    expect(within(journal).getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Nouveau parcours" }));
    await start();
    expect(api.states.size).toBe(2);
    expect(within(screen.getByRole("region", { name: "Journal du parcours" })).getAllByRole("listitem")).toHaveLength(1);
  });

  it("montre les minima par famille et conserve une option personnelle après repli", async () => {
    const fast = { ...sample("a", contexts[0]!).options[1]!, id: "fast", label: "Transport rapide", forecast: 1.2 };
    const slow = { ...fast, id: "slow", label: "Transport de renfort", forecast: 4.9 };
    fakeBackend([fast, slow]);
    render(<WorldModel />);
    expect((await screen.findAllByRole("radio")).map((r) => r.getAttribute("aria-label"))).toEqual([reference,fast.label,cleaner]);
    const more = screen.getByRole("button", { name: "Voir les autres affectations (2)" });
    fireEvent.click(more);
    expect(screen.getAllByRole("radio")).toHaveLength(5);
    fireEvent.click(screen.getByRole("radio", { name: slow.label }));
    fireEvent.click(screen.getByRole("button", { name: "Revenir au choix affiché" }));
    expect((screen.getByRole("radio", { name: slow.label }) as HTMLInputElement).checked).toBe(true);
    expect(document.activeElement).toBe(more);
    expect(screen.queryByRole("radio", { name: porter })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Valider en simulation" }));
    await screen.findByText("Affectation validée en simulation");
    expect(within(screen.getByRole("region", { name: "Journal du parcours" })).getByText(slow.label)).toBeTruthy();
  });

  it("garde les valeurs manquantes distinctes d’une file égale à zéro", async () => {
    fakeBackend();
    render(<WorldModel />);
    await start();
    fireEvent.change(screen.getByLabelText("Contexte synthétique"), { target: { value: "partiel" } });
    await validate(reference);
    fireEvent.click(screen.getByRole("button", { name: "Avancer à 16 h" }));
    const observed = await screen.findByRole("region", { name: "Comparaison après relevé" });
    expect(within(observed).getAllByText("Non renseignée")).toHaveLength(2);
    expect(within(observed).getByText(/total observé reste inconnu/)).toBeTruthy();
    const medicine = within(observed).getByRole("rowheader", { name: "Médecine" }).closest("tr")!;
    expect(within(medicine).getAllByRole("cell")[0]?.textContent).toBe("0");
  });

  it("attend la publication du flux retardé et utilise l’heure de départ à chaque avance", async () => {
    const api = fakeBackend();
    render(<WorldModel />); await start();
    fireEvent.change(screen.getByLabelText("Contexte synthétique"), { target: { value: "retarde" } });
    await validate();
    fireEvent.click(screen.getByRole("button", { name: "Avancer à 16 h" }));
    await screen.findByRole("heading", { name: "Le relevé de 16 h est en attente" });
    expect(screen.queryByRole("region", { name: "Comparaison après relevé" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Avancer à 18 h" }));
    await screen.findByRole("region", { name: "Comparaison après relevé" });
    expect(api.calls.filter((r) => r.path.endsWith("/advance")).map((r) => r.body?.from_hour)).toEqual([12,16]);
  });

  it("affiche un conflit, empêche les mutations obsolètes puis actualise depuis le serveur", async () => {
    const api = fakeBackend();
    render(<WorldModel />); fireEvent.click(await start()); api.rejectConfirm();
    fireEvent.click(screen.getByRole("button", { name: "Valider en simulation" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/déjà validé/);
    expect((screen.getByRole("button", { name: "Valider en simulation" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(api.calls.some((c) => c.method === "GET" && c.path.includes("/sessions/"))).toBe(true);
  });

  it("signale l’API indisponible et n’affiche aucune option enregistrée en dur", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<WorldModel />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/indisponible/);
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("rejette un relevé publié avant l’horloge, et un total incompatible avec les files d’unité", async () => {
    const s = sample("known",contexts[0]!);
    s.phase = "review"; s.hour = 16; s.selected_id = "port";
    s.observation = { sample_hour: 16, published_hour: 16, observed_stock: 3, by_ward: [1,null], visible_components: 10, total_components: 10 };
    vi.stubGlobal("fetch", vi.fn(async () => json(s)));
    await expect(worldApi.read("known","complet",new AbortController().signal)).rejects.toThrow(/incohérentes/);
    s.observation.by_ward=[1,2]; s.observation.published_hour=18;
    await expect(worldApi.read("known","complet",new AbortController().signal)).rejects.toThrow(/incohérentes/);
    s.observation.published_hour=16; s.observation.observed_stock=4;
    await expect(worldApi.read("known","complet",new AbortController().signal)).rejects.toThrow(/incohérentes/);
  });
});
