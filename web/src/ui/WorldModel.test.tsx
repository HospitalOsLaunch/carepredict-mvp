import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { WorldModel } from "./WorldModel";
import { COMPARISON_OBJECTIVES, worldApi, type WmContext, type WmOption, type WmSession } from "../api/worldModel";

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

function fakeBackend(extraOptions: WmOption[] = [], initialize?: (session: WmSession) => void) {
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
      initialize?.(next);
      states.set(id, next);
    }
    const s = states.get(id);
    if (!s) return json({ detail: "Parcours inconnu" }, 404);
    if (matched[2] === "confirm") {
      if (failedConfirm) return json({ detail: "Une autre session a déjà validé ce choix." }, 409);
      s.selected_id = String(body?.option_id);
      s.decision_objective = COMPARISON_OBJECTIVES.find((o) => o === body?.objective) ?? null;
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

  it("classe uniquement les affectations réalisables et expose le motif d’une famille indisponible", async () => {
    const template = sample("seed", contexts[0]!).options[1]!;
    const staff: WmOption = { ...template, kind: "staffing", id: "as", label: "Renfort AS en médecine", forecast: 2.1,
      jepa_forecast: null, constraint: "Une aide-soignante est disponible pour cette vacation." };
    const nurse: WmOption = { ...staff, id: "ide", label: "Renfort IDE en gériatrie", forecast: 3.2 };
    const noNurse: WmOption = { ...staff, id: "rh", label: "Prêt IDE depuis la médecine", eligible: false,
      forecast: 0, constraint: "Le seuil de présence du donneur serait franchi." };
    const smr: WmOption = { ...staff, id: "smr", kind: "smr", label: "Ouvrir une place de réadaptation", forecast: 4 };
    const noBed: WmOption = { ...staff, id: "bed", kind: "beds", label: "Ouvrir un lit de gériatrie",
      eligible: false, forecast: 1, constraint: "Aucun lit équipé disponible." };
    const api = fakeBackend([noNurse, nurse, staff, smr, { ...smr, id: "else", label: "SMR en gériatrie", forecast: 5 }, noBed]);
    render(<WorldModel />);
    expect((await screen.findAllByRole("radio")).map(el => el.getAttribute("aria-label"))).toEqual(
      [reference, porter, cleaner, staff.label, smr.label, noBed.label],
    );
    const denied = screen.getByRole("radio", { name: noBed.label }) as HTMLInputElement;
    expect(denied.disabled).toBe(true);
    expect(denied.closest("label")?.textContent).toContain(noBed.constraint);
    fireEvent.click(denied);
    expect((screen.getByRole("button", { name: "Valider en simulation" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.calls.some(c => c.path.endsWith("/confirm"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Voir les autres affectations (3)" }));
    const filter = screen.getByLabelText("Famille de ressources");
    fireEvent.change(filter, { target: { value: "staffing" } });
    expect((screen.getByRole("radio", { name: noNurse.label }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByRole("radio", { name: "SMR en gériatrie" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: nurse.label }));
    fireEvent.change(filter, { target: { value: "smr" } });
    expect((screen.getByRole("radio", { name: nurse.label }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Valider en simulation" }));
    await screen.findByText("Affectation validée en simulation");
    expect(api.calls.filter(c => c.path.endsWith("/confirm")).map(c => c.body?.option_id)).toEqual(["ide"]);
    fireEvent.click(screen.getByRole("button", { name: "Avancer à 16 h" }));
    const compared = await screen.findByRole("region", { name: "Comparaison après relevé" });
    expect(within(compared).getByRole("option", { name: /Ouvrir un lit de gériatrie.*Indisponible/ }).hasAttribute("disabled")).toBe(true);
  });

  it.each([
    ["staffing", "Prêt d’une IDE à la gériatrie"],
    ["smr", "Réserver une place en SMR"],
    ["beds", "Ouvrir un lit de médecine"],
  ] as const)("compare les effets du choix %s, valide puis retrouve ce choix au journal", async (kind, label) => {
    const opt: WmOption = {
      ...sample("seed", contexts[0]!).options[1]!, id: "new", kind, label, eligible: true, jepa_forecast: null,
      constraint: "Disponible de midi à 16 h sur le budget de l’établissement.",
      uncovered_ide_minutes: 24, uncovered_as_minutes: 0, bed_wait_patient_hours: 15.5, cost_eur: 80,
    };
    const api = fakeBackend([opt], (s) => Object.assign(s.options[0]!, {
      uncovered_ide_minutes: 39, uncovered_as_minutes: 8, bed_wait_patient_hours: 18.2, cost_eur: 0,
    }));
    const mounted = render(<WorldModel />);
    fireEvent.click(await screen.findByRole("radio", { name: label }));
    const projection = screen.getByRole("region", { name: "Détail de la projection à midi" });
    fireEvent.click(screen.getByRole("button", { name: "Voir les effets estimés" }));
    expect(document.activeElement).toBe(projection);
    expect(within(projection).getByText(opt.constraint!)).toBeTruthy();
    const effects = within(projection).getByRole("table", { name: "Conséquences prévues à midi pour l’établissement" });
    const cellValues = (name: string) => within(within(effects).getByRole("rowheader", { name }).closest("tr")!)
      .getAllByRole("cell").map((cell) => cell.textContent);
    expect(cellValues("Soins infirmiers non couverts (min)")).toEqual(["39","24"]);
    expect(cellValues("Soins aides-soignants non couverts (min)")).toEqual(["8","0"]);
    expect(cellValues("Attente d’un lit (heures-patients)")).toEqual(["18,2","15,5"]);
    expect(cellValues("Coût de l’affectation (€)")).toEqual(["0","80"]);
    fireEvent.click(within(projection).getByText("Projection secondaire JEPA"));
    expect(within(projection).getByText("Projection JEPA indisponible pour cette affectation.")).toBeTruthy();
    fireEvent.click(within(projection).getByRole("button", { name: "Revenir à la validation" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Valider en simulation" }));
    fireEvent.click(document.activeElement!);
    await screen.findByText("Affectation validée en simulation");
    fireEvent.click(screen.getByRole("button", { name: "Avancer à 16 h" }));
    await screen.findByRole("region", { name: "Comparaison après relevé" });
    mounted.unmount();
    render(<WorldModel />);
    await screen.findByRole("region", { name: "Comparaison après relevé" });
    expect(within(screen.getByRole("region", { name: "Journal du parcours" })).getAllByText(label)).toHaveLength(2);
    expect(api.calls.filter(c => c.path.endsWith("/confirm"))).toHaveLength(1);
  });

  it("reclasse les objectifs avec leur unité, le coût à égalité et le choix humain préservé", async () => {
    const base: WmOption = { ...sample("seed", contexts[0]!).options[1]!, kind: "staffing", jepa_forecast: null };
    const options = [
      { ...base, id: "a", label: "IDE de réserve", forecast: 1, bed_wait_patient_hours: 4, cost_eur: 300,
        uncovered_ide_minutes: 2, uncovered_as_minutes: 1 },
      { ...base, id: "b", label: "AS de nuit", forecast: 2, bed_wait_patient_hours: 3, cost_eur: 200,
        uncovered_ide_minutes: 1, uncovered_as_minutes: 2 },
      { ...base, id: "c", label: "AS du volant", forecast: 3, bed_wait_patient_hours: 3, cost_eur: 100,
        uncovered_ide_minutes: 2, uncovered_as_minutes: 5 },
      { ...base, id: "d", label: "Prêt non chiffré", forecast: 4, cost_eur: 0, uncovered_ide_minutes: null, uncovered_as_minutes: 0 },
      { ...base, id: "e", label: "Prêt sans prix", forecast: 4.5, cost_eur: null,
        bed_wait_patient_hours: 3, uncovered_ide_minutes: 0, uncovered_as_minutes: 3 },
    ];
    const api = fakeBackend(options);
    const mounted = render(<WorldModel />);
    const criterion = await screen.findByLabelText("Critère de comparaison à midi");
    const change = (value: string) => fireEvent.change(criterion, { target: { value } });
    const group = screen.getByRole("group", { name: "Affectation à simuler à midi" });
    const staff = () => within(group).getAllByRole("radio").slice(3).map(el => el.getAttribute("aria-label"));
    expect(staff()).toEqual(["IDE de réserve"]);
    expect(within(group).getByText("patients", { selector: "small" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "IDE de réserve" }));
    change("bed_wait");
    expect(staff()).toEqual(["AS du volant","IDE de réserve"]);
    expect(within(group).getByText("heures-patients", { selector: "small" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "AS du volant" }).closest("label")?.textContent).toContain("3 heures-patients");
    change("uncovered_care");
    expect(staff()).toEqual(["AS de nuit","IDE de réserve"]);
    expect(within(group).getByText("minutes", { selector: "small" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "AS de nuit" }).closest("label")?.textContent).toContain("3 minutes");
    expect(screen.queryByRole("radio", { name: "Prêt non chiffré" })).toBeNull();
    expect(within(group).getByRole("radio", { name: cleaner }).closest("label")?.textContent).toContain("Non renseigné");
    change("transfer_queue");
    expect(staff()).toEqual(["IDE de réserve"]);
    expect((screen.getByRole("radio", { name: "IDE de réserve" }) as HTMLInputElement).checked).toBe(true);
    change("bed_wait");
    fireEvent.click(screen.getByRole("button", { name: "Valider en simulation" }));
    await screen.findByText("Affectation validée en simulation");
    const frozen = screen.getByLabelText("Critère de comparaison à midi") as HTMLSelectElement;
    expect(frozen.disabled).toBe(true);
    expect(frozen.value).toBe("bed_wait");
    expect(api.calls.filter(c => c.path.endsWith("/confirm")).map(c => c.body)).toEqual([
      { option_id: "a", objective: "bed_wait" },
    ]);
    mounted.unmount();
    render(<WorldModel />);
    const record = await screen.findByText("Critère enregistré · Attente d’un lit de 12 h à 16 h");
    expect(record.closest("li")?.textContent).toContain("IDE de réserve");
  });

  it("préserve le critère inconnu des anciens journaux et masque les critères sans valeur réalisable", async () => {
    fakeBackend([], (s) => {
      s.phase = "confirmed"; s.selected_id = "ref";
      s.journal.push({ hour: 12, event: "confirmed", option_id: "ref" });
      const partial = s.options[1]!;
      partial.uncovered_ide_minutes = 1;
      partial.uncovered_as_minutes = null;
    });
    render(<WorldModel />);
    await screen.findByText("Affectation validée en simulation");
    expect(screen.queryByLabelText("Critère de comparaison à midi")).toBeNull();
    expect(screen.getByText("Critère de comparaison non renseigné")).toBeTruthy();
  });

  it("révoque le brouillon si l’option devient indisponible à l’actualisation", async () => {
    const api = fakeBackend();
    render(<WorldModel />);
    fireEvent.click(await start());
    const opt = [...api.states.values()][0]!.options[1]!;
    opt.eligible = false;
    opt.constraint = "L’équipe est désormais affectée.";
    fireEvent.click(screen.getByRole("button", { name: "Actualiser" }));
    await screen.findByText(opt.constraint);
    const submit = screen.getByRole("button", { name: "Valider en simulation" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(submit);
    expect(api.calls.some(c => c.path.endsWith("/confirm"))).toBe(false);
  });

  it("réserve la place supplémentaire à l’option lits et à son unité, y compris pour le relevé", async () => {
    const s = sample("known", contexts[0]!);
    const bed: WmOption = { ...s.options[1]!, kind: "beds", id: "open", ward_id: "med", jepa_forecast: null,
      forecast: 22, by_ward: [21,1], reconstruction: 22, reconstructed_by_ward: [21,1] };
    s.options.push(bed);
    s.phase = "review"; s.hour = s.publication_hour; s.selected_id = bed.id;
    s.observation = { sample_hour: 16, published_hour: 16, by_ward: [21,1], observed_stock: 22,
      visible_components: 10, total_components: 10 };
    vi.stubGlobal("fetch", vi.fn(async () => json(s)));
    const read = () => worldApi.read("known","complet",new AbortController().signal);
    expect((await read()).selected_id).toBe("open");
    bed.by_ward = [22,0]; await expect(read()).rejects.toThrow(/incohérentes/);
    bed.by_ward = [1,31]; await expect(read()).rejects.toThrow(/incohérentes/);
    bed.by_ward = [21,1]; bed.reconstructed_by_ward = [22,0]; await expect(read()).rejects.toThrow(/incohérentes/);
    bed.reconstructed_by_ward = [21,1]; s.selected_id = "port"; await expect(read()).rejects.toThrow(/incohérentes/);
    s.selected_id = "open"; bed.kind = "staffing"; await expect(read()).rejects.toThrow(/incohérentes/);
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
