import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { WorldModel } from "./WorldModel";
import type { ComparisonObjective, WmContext, WmSession } from "../api/worldModel";
import { type PlanAction, type PlanEvaluation, type PlanMenu, type PlanMetrics } from "../api/worldPlans";

const context: WmContext = { id: "demo", label: "Hôpital du test", feed: "full", ward_count: 2 };
const indicators: PlanMetrics = {
  transfer_queue: 10, bed_wait_patient_hours: 38, uncovered_ide_minutes: 140, uncovered_as_minutes: 32,
  transport_used: 2, beds_cleaned: 3, smr_transfers: 2, open_beds: 42, available_beds: 4, admissions: 2, discharges: 3,
  redirected_patients:1, admission_queue_at_16:3, named_admissions:3, named_discharges:1,
};
function action(id: string, label: string, kind: PlanAction["kind"], unit = "patient"): PlanAction {
  return { id, label, kind, ward_id: "u1", unit, quantity: 1, start_hour: 12, end_hour: 16, cost_eur: 0,
    eligible: true, constraint: "Disponibilité confirmée à midi." };
}
const actions: PlanAction[] = [
  action("S1", "Coordonner la sortie S1", "discharge"), action("S2", "Coordonner la sortie S2", "discharge"),
  ...["A1","A2","A3"].map(id => action(id, "Admettre " + id, "admission")),
  action("r", "Remplacer une IDE", "replacement", "personne"), action("move", "Réaffecter une AS", "redeployment", "personne"),
  action("as-hire", "Demander un renfort AS", "reinforcement", "personne"),
  action("hire", "Demander un renfort IDE", "reinforcement", "personne"), action("t", "Transport en gériatrie", "transport", "équipe"),
  action("clean", "Nettoyer en médecine", "cleaning", "équipe"), action("s", "Réserver une place en SMR", "smr", "place"),
  { ...action("bed", "Ouvrir un lit en gériatrie", "beds", "lit"), eligible: false, constraint: "Pas de lit équipé." },
];
function evaluate(ids: string[]): PlanEvaluation {
  const conflict = ids.includes("hire") && ids.includes("r");
  const key = [...ids].sort();
  return { id: "P-" + (key.join("-") || "ref"), action_ids: key, feasible: !conflict,
    conflicts: conflict ? ["La même IDE est réservée deux fois."] : [], cost_eur: ids.length*10,
    metrics: { ...indicators, transfer_queue: 10-ids.length*.5, beds_cleaned: ids.includes("clean") ? 6 : 3,
      redirected_patients:ids.includes("clean") ? 2 : 1, named_admissions:ids.includes("clean") ? 2 : 3 },
    case_hours:{A1:15,A2:14,A3:ids.includes("clean")?null:16,S1:14,S2:null},
    access_warnings:ids.includes("clean")?["Le dossier A3 ne serait plus admis avant 16 h."]:[],
    ward_impacts:["u1","u2"].map((ward_id,i)=>({ward_id,transfer_queue:ids.length?(i?-1:1):0,admissions:0,redirected_patients:0,
      care_minutes:ids.includes("r")?(i?30:-30):0,transport_used:0,beds_cleaned:0,smr_transfers:0,available_beds:0})),
    realized: Object.fromEntries(ids.map(id => [id, /^[AS][1-3]$/.test(id) ? 1 : 120])) };
}
const example = ["S1","S2","A1","A2","A3","r","move","as-hire"];
function menu(objective: ComparisonObjective, subset?: string[], withExample = false): PlanMenu {
  const recs = subset ? [subset.slice(0,1),[]] : objective === "bed_wait" ? [["A1","A3"],["S2","t"],["r"]] : [["S1","r"],["S2","t"],["r"]];
  const examined = subset ? 2**subset.length : 40;
  const evaluated = withExample && examined > 10 ? examined - 5 : examined;
  return { objective, actions, reference: evaluate([]), recommendations: recs.map(evaluate),
    search: { evaluated, complete: !!subset, ...(withExample ? { examined, feasible: evaluated, scope_size: subset?.length ?? actions.length } : {}) },
    ...(withExample ? {example_action_ids:example, scope_ids:subset ?? actions.map(a=>a.id)} : {}), budget_eur:250 };
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type":"application/json" } });
type Config = { feed?: WmContext["feed"]; holdPreview?: boolean; withExample?: boolean };
function backend({ feed = "full", holdPreview = false, withExample = false }: Config = {}) {
  const c = { ...context, feed };
  const states = new Map<string,WmSession>();
  const calls: Array<{ path: string; body: { action_ids?: string[]; scope_ids?: string[]; objective?: ComparisonObjective; from_hour?: number } }> = [];
  let release: (()=>void) | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const path = String(input);
    const body = JSON.parse(String(init?.body ?? "{}")) as (typeof calls)[number]["body"];
    calls.push({ path, body });
    if (path.endsWith("/contexts")) return json({ contexts:[c], model_version:"plan-v2" });
    const match = path.match(/\/sessions\/([^/?]+)(.*)/)!;
    const id = match[1]!, suffix = match[2]!;
    if (!states.has(id) && init?.method === "PUT") {
      states.set(id, { id, context:c, phase:"planning", hour:12, decision_hour:12, target_hour:16,
        publication_hour:feed === "delayed" ? 18 : 16, model_version:"plan-v2", plan_version:"compose-1",
        morning_plan:["Transport en médecine"], wards:[{id:"u1",label:"Médecine",beds:20},{id:"u2",label:"Gériatrie",beds:22}],
        reference_id:"solo-ref", selected_id:null, options:[{id:"solo-ref",label:"Référence unitaire",kind:"reference",
          ward_id:null,forecast:10,jepa_forecast:9,by_ward:[7,3],reconstruction:null,reconstructed_by_ward:null}],
        journal:[{hour:12,event:"opened",option_id:null}], observation:null });
    }
    const s = states.get(id)!;
    if (suffix.startsWith("/plans?")) return json(s.plan_snapshot ?? menu(new URL(path,"http://test").searchParams.get("objective") as ComparisonObjective,undefined,withExample));
    if (suffix === "/plans/preview") {
      if (holdPreview) await new Promise<void>(resolve => { release=resolve; });
      return json(evaluate(body.action_ids!));
    }
    if (suffix === "/plans/optimize") return json(menu(body.objective!,body.action_ids!,withExample));
    if (suffix === "/plans/confirm") {
      const plan = evaluate(body.action_ids!);
      if (!plan.feasible) return json({detail:plan.conflicts[0]},409);
      s.confirmed_plan=plan; s.plan_snapshot=menu(body.objective!,body.scope_ids,withExample); s.decision_objective=body.objective!;
      s.selected_id=plan.id; s.phase="confirmed"; s.journal.push({hour:12,event:"confirmed",option_id:plan.id});
    }
    if (suffix === "/advance") {
      if (s.hour===12 && feed==="delayed") {
        s.hour=16; s.phase="awaiting_report"; s.journal.push({hour:16,event:"awaiting_report",option_id:s.selected_id});
      } else {
        s.hour=s.publication_hour; s.phase="review";
        s.observation={ sample_hour:16,published_hour:s.hour,observed_stock:feed==="full"?8:null,by_ward:[5,feed==="full"?3:null],
          visible_components:feed==="full"?10:4,total_components:10 };
        s.plan_report={actual_metrics:feed==="full"?{...indicators,transfer_queue:8}:null,realized:feed==="full"?s.confirmed_plan!.realized:null,
          case_hours:feed==="full"?{A1:14,A2:15,A3:16,S1:15,S2:null}:null,
          alternatives:[{plan:evaluate([]),reconstructed_queue:9.5},{plan:evaluate(["S2","t"]),reconstructed_queue:8.7}]};
        s.journal.push({hour:s.hour,event:"report_received",option_id:s.selected_id});
      }
    }
    return json(s);
  }));
  return { calls,states,release:()=>release?.() };
}
const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;
const begin = () => screen.findByRole("radio", { name:"Meilleur plan évalué" });
const draft = () => screen.getByRole("region",{name:"Éditeur de composition"});
const summary = () => screen.getByRole("region",{name:"Plan à valider"});
const toggleAction = (label: string) => fireEvent.click(within(draft()).getByRole("checkbox",{name:label}));
beforeEach(()=>window.localStorage.clear());
afterEach(()=>vi.unstubAllGlobals());

describe("plans composés à midi", () => {
  it("propose le plan conjoint, ses alternatives et la référence ; le parcours unitaire reste accessible", async () => {
    backend(); render(<WorldModel />); await begin();
    expect(button("Plan composé").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    expect(screen.getByText(/40 combinaisons évaluées.*partielle/)).toBeTruthy();
    expect(within(summary()).getByText("Coordonner la sortie S1")).toBeTruthy();
    const impacts = screen.getByRole("region",{name:"Impacts du plan par ressource"});
    ["Transport","Personnel","Bionettoyage","SMR","Lits"].forEach(name=>expect(within(impacts).getByText(name)).toBeTruthy());
    fireEvent.click(button("Comparer les impacts sur les ressources")); expect(document.activeElement).toBe(impacts);
    fireEvent.click(button("Action unique"));
    expect(screen.getByRole("heading",{name:"Comparer les affectations"})).toBeTruthy();
    fireEvent.click(button("Plan composé")); await begin();
    fireEvent.change(screen.getByLabelText("Critère du plan à midi"),{target:{value:"bed_wait"}});
    await within(summary()).findByText("Admettre A3");
    fireEvent.click(screen.getByRole("radio",{name:"Planning horaire de référence"}));
    expect(within(summary()).getByText("Le plan conserve les affectations horaires prévues à midi.")).toBeTruthy();
    fireEvent.click(button("Valider le plan en simulation"));
    await screen.findByRole("heading",{name:"Plan validé en simulation"});
    expect(within(screen.getByRole("region",{name:"Journal du parcours"})).getByText(/Critère enregistré.*Attente d’un lit/)).toBeTruthy();
  });

  it("sépare les cinq patients, les équipes et les conflits ; une seule confirmation persiste le plan exact", async () => {
    const api=backend();
    const initial=render(<WorldModel />); await begin(); fireEvent.click(button("Modifier les actions"));
    for(const label of ["Coordonner la sortie S2","Admettre A1","Admettre A2","Admettre A3","Réaffecter une AS","Demander un renfort IDE"]) toggleAction(label);
    expect((within(draft()).getByRole("checkbox",{name:"Ouvrir un lit en gériatrie"}) as HTMLInputElement).disabled).toBe(true);
    expect(button("Valider le plan en simulation").disabled).toBe(true);
    fireEvent.click(button("Évaluer ma composition")); await screen.findByText("La même IDE est réservée deux fois.");
    expect(button("Valider le plan en simulation").disabled).toBe(true);
    expect(screen.getByRole("region",{name:"Impacts du plan par ressource"})).toBeTruthy();
    toggleAction("Demander un renfort IDE");
    expect(screen.queryByRole("region",{name:"Impacts du plan par ressource"})).toBeNull();
    fireEvent.click(button("Évaluer ma composition")); await within(summary()).findByText("Admettre A3");
    const submit=button("Valider le plan en simulation");fireEvent.click(submit);fireEvent.click(submit);
    await screen.findByRole("heading",{name:"Plan validé en simulation"});
    const confirmation=api.calls.filter(c=>c.path.endsWith("/plans/confirm"));
    expect(confirmation).toHaveLength(1);
    expect(confirmation[0]?.body.action_ids).toEqual(["A1","A2","A3","S1","S2","move","r"]);
    fireEvent.click(button("Avancer à 16 h")); await screen.findByRole("region",{name:"Relevé du plan composé"});
    initial.unmount();render(<WorldModel />);
    const log=await screen.findByRole("region",{name:"Journal du parcours"});
    expect(within(log).getByText(/Admettre A3.*1 patient/)).toBeTruthy();
    const detail=screen.getByRole("region",{name:"Plan composé validé"});
    expect(within(detail).getAllByText("Réalisation relevée · 1 sur 1")).toHaveLength(5);
    expect(api.calls.filter(c=>c.path.includes("/plans?"))).toHaveLength(1);
    const table=screen.getByRole("table",{name:"Impacts chiffrés du plan comparés au planning horaire"});
    expect(within(table).getByRole("columnheader",{name:"Relevé"})).toBeTruthy();
    expect(screen.queryByRole("button",{name:"Action unique"})).toBeNull();
  });

  it("calcule les sous-ensembles sans remplacer le brouillon et restaure les identifiants après rechargement", async () => {
    const api=backend(); const start=render(<WorldModel/>); await begin(); fireEvent.click(button("Modifier les actions"));
    toggleAction("Admettre A2");
    fireEvent.click(button("Comparer les sous-ensembles"));
    const alternatives=await screen.findByRole("region",{name:"Sous-plans du brouillon"});
    expect(within(alternatives).getByText(/8 combinaisons évaluées.*exhaustive/)).toBeTruthy();
    fireEvent.click(within(alternatives).getByRole("radio",{name:"Meilleur plan évalué"}));
    expect(within(summary()).getByText("1 intervention")).toBeTruthy();
    expect((within(draft()).getByRole("checkbox",{name:"Admettre A2"}) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(button("Revenir au brouillon complet")); expect(button("Valider le plan en simulation").disabled).toBe(true);
    start.unmount();render(<WorldModel />); await screen.findByRole("region",{name:"Éditeur de composition"});
    expect((within(draft()).getByRole("checkbox",{name:"Admettre A2"}) as HTMLInputElement).checked).toBe(true);
    expect(button("Valider le plan en simulation").disabled).toBe(true);
    expect(api.calls.filter(c=>c.path.endsWith("/plans/optimize"))[0]?.body.action_ids?.sort()).toEqual(["A2","S1","r"]);
  });

  it("ignore un ancien calcul qui arrive après une modification de composition", async () => {
    const api=backend({holdPreview:true});render(<WorldModel/>);await begin();fireEvent.click(button("Modifier les actions"));
    fireEvent.click(button("Évaluer ma composition")); toggleAction("Coordonner la sortie S2");
    await act(async()=>api.release());
    expect(button("Valider le plan en simulation").disabled).toBe(true);
    expect(screen.queryByRole("region",{name:"Impacts du plan par ressource"})).toBeNull();
  });

  it("simule l’exemple en un clic, compare son périmètre complet et archive les alternatives du sous-plan validé", async () => {
    const api=backend({withExample:true}); render(<WorldModel/>); await begin();
    fireEvent.click(button("Essayer le plan à 8 actions"));
    await within(summary()).findByText("8 interventions");
    expect(within(draft()).getAllByRole("checkbox",{checked:true})).toHaveLength(8);
    expect(api.calls.filter(c=>c.path.endsWith("/plans/preview"))[0]?.body.action_ids).toEqual(example);
    expect(api.calls.some(c=>c.path.endsWith("/plans/confirm"))).toBe(false);
    expect(within(summary()).getAllByText("Temps mobilisé prévu · 120 min")).toHaveLength(3);
    fireEvent.click(button("Comparer les sous-ensembles"));
    const sub=await screen.findByRole("region",{name:"Sous-plans du brouillon"});
    expect(within(sub).getByText(/256 combinaisons examinées.*251 simulées.*251 réalisables.*exhaustive/)).toBeTruthy();
    fireEvent.click(within(sub).getByRole("radio",{name:"Meilleur plan évalué"}));
    fireEvent.click(button("Valider le plan en simulation")); await screen.findByRole("heading",{name:"Plan validé en simulation"});
    const confirms=api.calls.filter(c=>c.path.endsWith("/plans/confirm"));
    expect(confirms.map(c=>c.body)).toEqual([{action_ids:["S1"],objective:"transfer_queue",scope_ids:example}]);
    expect(screen.getByText("Comparaison archivée à midi")).toBeTruthy();
  });

  it("archive le catalogue global si le cadre ajoute une intervention en dehors du périmètre comparé", async () => {
    const api=backend({withExample:true}); render(<WorldModel/>); await begin();
    fireEvent.click(button("Essayer le plan à 8 actions")); await within(summary()).findByText("8 interventions");
    fireEvent.click(button("Comparer les sous-ensembles"));
    const sub=await screen.findByRole("region",{name:"Sous-plans du brouillon"});
    fireEvent.click(within(sub).getByRole("radio",{name:"Meilleur plan évalué"}));
    toggleAction("Transport en gériatrie"); expect(screen.queryByRole("region",{name:"Sous-plans du brouillon"})).toBeNull();
    fireEvent.click(button("Évaluer ma composition")); await within(summary()).findByText("9 interventions");
    fireEvent.click(button("Valider le plan en simulation")); await screen.findByRole("heading",{name:"Plan validé en simulation"});
    expect(api.calls.find(c=>c.path.endsWith("/plans/confirm"))?.body.scope_ids).toBeUndefined();
  });

  it("montre la dégradation d’accès d’un plan manuel et l’heure perdue pour A3 avant sa validation", async () => {
    backend(); render(<WorldModel/>); await begin();
    expect(screen.getByText(/le classement maintient au moins les admissions prévues/)).toBeTruthy();
    fireEvent.click(button("Modifier les actions")); toggleAction("Nettoyer en médecine");
    fireEvent.click(button("Évaluer ma composition"));
    await within(summary()).findByText("Le dossier A3 ne serait plus admis avant 16 h.");
    expect(within(summary()).getByText(/Réorientations prévues · 2/)).toBeTruthy();
    const row=within(summary()).getByRole("rowheader",{name:"A3",hidden:true}).closest("tr")!;
    expect(row.textContent).toContain("16 hNon réalisé à 16 h");
    expect(button("Valider le plan en simulation").disabled).toBe(false);
    const impact=screen.getByRole("region",{name:"Impacts du plan par ressource"});
    expect(within(impact).getByRole("rowheader",{name:"Patients réorientés"})).toBeTruthy();
    expect(within(impact).getByRole("rowheader",{name:"En attente d’admission à 16 h"})).toBeTruthy();
    fireEvent.click(within(impact).getByText("Effets par unité"));
    fireEvent.change(within(impact).getByLabelText("Indicateur par unité"),{target:{value:"care_minutes"}});
    const table=within(impact).getByRole("table",{name:"Écarts prévus par unité"});
    expect(within(table).getByRole("row",{name:"Médecine -30"})).toBeTruthy();
    expect(within(table).getByRole("row",{name:"Gériatrie +30"})).toBeTruthy();
  });

  it("respecte le retard du relevé et distingue la file d’un autre plan de la mesure absente", async () => {
    backend({feed:"delayed"});render(<WorldModel/>); await begin();
    fireEvent.click(button("Valider le plan en simulation")); await screen.findByRole("heading",{name:"Plan validé en simulation"});
    fireEvent.click(button("Avancer à 16 h")); await screen.findByRole("heading",{name:"Le relevé de 16 h est en attente"});
    expect(screen.queryByRole("region",{name:"Relevé du plan composé"})).toBeNull();
    fireEvent.click(button("Avancer à 18 h"));const reading=await screen.findByRole("region",{name:"Relevé du plan composé"});
    expect(within(reading).getByText("9,5")).toBeTruthy();
    expect(within(reading).getByText("Non renseignée",{selector:"strong"})).toBeTruthy();
    fireEvent.change(within(reading).getByRole("combobox"),{target:{value:"P-S2-t"}});
    expect(within(reading).getByText("8,7")).toBeTruthy();
    expect(within(screen.getByRole("region",{name:"Impacts du plan par ressource"})).queryByRole("columnheader",{name:"Relevé"})).toBeNull();
  });
});
