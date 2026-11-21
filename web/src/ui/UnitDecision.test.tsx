import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { UnitDecision } from "./UnitDecision";
import type { ComparisonObjective, WmSession } from "../api/worldModel";
import { readUnitMenu, type PlanAction, type PlanEvaluation, type PlanMenu, type PlanMetrics } from "../api/worldPlans";

const wards = [{ id: "u1", label: "Médecine", beds: 20 }, { id: "u2", label: "Observation", beds: 28 }];
const state: WmSession = {
  id: "journal", context:{ id:"rives",label:"Hôpital des Rives",ward_count:2,feed:"full" }, model_version:"test",
  phase:"planning", hour:12, decision_hour:12,target_hour:16,publication_hour:16,wards, plan_version:"test-1",
  morning_plan:[], selected_id:null, reference_id:"ref", options:[{ id:"ref",label:"Référence",kind:"reference",
    ward_id:null,forecast:4,jepa_forecast:null,by_ward:[2,2],reconstruction:null,reconstructed_by_ward:null }],
  journal:[{hour:12,event:"opened",option_id:null}], observation:null,
};
const actions: PlanAction[] = [
  { id:"A2",label:"Avancer l’entrée A2",kind:"admission",ward_id:"u2", unit:"patient",quantity:1,start_hour:12,end_hour:16,cost_eur:0,eligible:true,constraint:"Admission acceptée par le service." },
  { id:"r",label:"Renfort IDE",kind:"reinforcement",ward_id:"u2",unit:"personne",quantity:1,start_hour:12,end_hour:16,cost_eur:90,eligible:true,constraint:"Offre confirmée." },
];
function evaluate(ids: string[], ward = "u2"): PlanEvaluation {
  const metrics: PlanMetrics={ transfer_queue:100,bed_wait_patient_hours:100,uncovered_ide_minutes:20,uncovered_as_minutes:5,
    transport_used:5,beds_cleaned:5,smr_transfers:2,open_beds:30,available_beds:4,admissions:7,discharges:8 };
  return { context_id:"rives",ward_id:ward,id:ids.join("-")||"keep", action_ids:ids, feasible:true, conflicts:[], cost_eur:ids.includes("r")?90:0,
    metrics, realized:{}, ward_metrics:{ transfer_queue:3,bed_wait_patient_hours:ids.length?17.5:22,uncovered_ide_minutes:2,uncovered_as_minutes:4 },
    ward_impacts:wards.map(w => ({ward_id:w.id,admissions:1,redirected_patients:0,transfer_queue:0,care_minutes:2,available_beds:1,transport_used:0,beds_cleaned:0,smr_transfers:0})) };
}
function menu(ward = "u2", objective: ComparisonObjective = "bed_wait"): PlanMenu {
  const ids = ward === "u1" ? [] : objective === "uncovered_care" ? ["r"] : ["A2","r"];
  return { context_id:"rives",objective,actions,ward_id:ward,reference:evaluate([],ward),recommendations:[evaluate(ids,ward)],budget_eur:200,
    search:{evaluated:3,examined:4,scope_size:2,complete:true},ward_state:{ context_id:"rives",ward_id:ward,as_of_hour:12,capacity_beds:22,available_beds:2.5,admission_queue:4,transfer_queue:1,
    cases:[{id:ward==="u1"?"S1":"S2",kind:"discharge",available_hour:12,scheduled_hour:15,eligible:true}] }};
}
const json = (value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
function commit(m: PlanMenu, plan=m.recommendations[0]!): WmSession {
  return {...state,phase:"confirmed",decision_ward_id:m.ward_id,decision_objective:m.objective,selected_id:plan.id,confirmed_plan:plan,plan_snapshot:m,
    journal:[...state.journal,{hour:12,event:"confirmed",option_id:plan.id,ward_id:m.ward_id}]};
}
function Host({initial=state, ward="u2", view="action"}: {initial?:WmSession;ward?:string;view?:"action"|"unite"}) {
  const [session,setSession]=useState(initial);
  return <UnitDecision view={view} session={session} ward={wards.find(w=>w.id===ward)!} onConfirmed={setSession}/>;
}
afterEach(()=>{ vi.unstubAllGlobals(); window.sessionStorage.clear(); });

describe("décision sur la page Unité",()=>{
  it("affiche la cohorte de l’unité et valide ensemble les quantités du meilleur plan courant",async()=>{
    const m=menu();
    const posts: unknown[]=[];
    vi.stubGlobal("fetch",vi.fn(async(url:string,options:RequestInit)=>{
      if(url.includes("/plans?")) {
        const p=new URL(url,"http://local").searchParams;
        expect([p.get("ward_id"),p.get("objective")]).toEqual(["u2","bed_wait"]);
        return json(m);
      }
      posts.push(JSON.parse(String(options.body)));
      return json(commit(m));
    }));
    render(<Host/>);
    const approve=await screen.findByRole("button",{name:"Valider les 2 actions"});
    expect(screen.getByRole("heading",{name:"Coordonner 2 actions"})).toBeTruthy();
    expect(screen.getByText("17,5")).toBeTruthy();
    const conditions=screen.getByText("Conditions et disponibilité des ressources");
    fireEvent.click(conditions);
    expect(screen.getByText("Offre confirmée.")).toBeTruthy();
    fireEvent.click(approve);
    expect(await screen.findByText("Décision validée")).toBeTruthy();
    expect(posts).toEqual([{context_id:"rives",ward_id:"u2",action_ids:["A2","r"],objective:"bed_wait"}]);
    expect(screen.queryByRole("button",{name:/Valider/})).toBeNull();
    expect(screen.getByText("Choix enregistré dans le journal de l’établissement.")).toBeTruthy();
  });

  it("traite une absence de gain en proposant le maintien du planning",async()=>{
    vi.stubGlobal("fetch",vi.fn(async()=>json(menu("u1"))));
    render(<Host ward="u1"/>);
    expect(await screen.findByRole("button",{name:"Valider le maintien du planning"})).toBeTruthy();
    expect(screen.queryByText("S2")).toBeNull();
  });

  it("désactive l’ancien plan pendant le changement de priorité",async()=>{
    let release=()=>{};
    vi.stubGlobal("fetch",vi.fn(async(url:string)=>{
      const objective = new URL(url,"http://local").searchParams.get("objective") as ComparisonObjective;
      if (objective === "uncovered_care") await new Promise<void>(resolve=>{release=resolve;});
      return json(menu("u2",objective));
    }));
    render(<Host/>);
    await screen.findByRole("button",{name:"Valider les 2 actions"});
    fireEvent.change(screen.getByRole("combobox",{name:"Priorité de l’unité"}),{target:{value:"uncovered_care"}});
    expect(screen.queryByRole("button",{name:/Valider/})).toBeNull();
    await act(async()=>release());
    expect(await screen.findByRole("button",{name:"Valider l’action"})).toBeTruthy();
    expect(screen.getByRole("heading",{name:"Renfort IDE"})).toBeTruthy();
  });

  it("relit le journal après un conflit externe et ne présente pas les stocks de l’autre unité",async()=>{
    vi.stubGlobal("fetch",vi.fn(async(url:string)=>{
      if(url.includes("/plans?")) return json(menu("u2"));
      if(url.endsWith("/wards/u2/state")) return json(menu("u2").ward_state);
      if(url.endsWith("/plans/confirm")) return json({detail:"Autre décision validée."},409);
      return json(commit(menu("u1")));
    }));
    render(<Host/>);
    fireEvent.click(await screen.findByRole("button",{name:"Valider les 2 actions"}));
    expect(await screen.findByRole("heading",{name:"Décision enregistrée pour Médecine"})).toBeTruthy();
    expect(screen.queryByRole("button",{name:/Valider/})).toBeNull();
    expect(screen.queryByText("S1")).toBeNull();
    expect(screen.getByText("Effets sur les ressources · Observation")).toBeTruthy();
  });

  it("valide une alternative avec ses propres actions et ses propres effets",async()=>{
    const m=menu();
    const alternative=evaluate(["r"]);
    alternative.ward_metrics={...alternative.ward_metrics!,bed_wait_patient_hours:19};
    m.recommendations.push(alternative);
    let submitted: Record<string,unknown> | undefined;
    vi.stubGlobal("fetch",vi.fn(async(url:string,opts:RequestInit)=>{
      if (url.includes("/plans?")) return json(m);
      submitted=JSON.parse(String(opts.body));
      return json(commit(m,alternative));
    }));
    render(<Host/>);
    await screen.findByRole("button",{name:"Valider les 2 actions"});
    fireEvent.click(screen.getByText("Comparer les alternatives"));
    fireEvent.click(screen.getAllByRole("radio")[1]!);
    expect(screen.getByRole("heading",{name:"Renfort IDE"})).toBeTruthy();
    expect(screen.getByText("19")).toBeTruthy();
    fireEvent.click(screen.getByRole("button",{name:"Valider l’action"}));
    await screen.findByText("Décision validée");
    expect(submitted?.action_ids).toEqual(["r"]);
  });

  it("impose une nouvelle évaluation après modification et bloque les conflits",async()=>{
    const m=menu();
    const manual=evaluate(["r"]);
    let submitted: Record<string,unknown> | undefined;
    vi.stubGlobal("fetch",vi.fn(async(url:string,opts:RequestInit)=>{
      if (url.includes("/plans?")) return json(m);
      const body=JSON.parse(String(opts.body));
      if (url.endsWith("/plans/preview")) return json(body.action_ids.length===2
        ? {...evaluate(["r","A2"]),feasible:false,metrics:null,ward_metrics:null,conflicts:["Ressource déjà réservée."]}
        : manual);
      submitted=body;
      return json(commit(m,manual));
    }));
    render(<Host/>);
    await screen.findByRole("button",{name:"Valider les 2 actions"});
    fireEvent.click(screen.getByRole("button",{name:"Ajuster les actions"}));
    expect(screen.queryByRole("button",{name:/Valider/})).toBeNull();
    fireEvent.click(screen.getByRole("button",{name:"Évaluer les actions"}));
    await screen.findByText("Ressource déjà réservée.");
    expect(screen.queryByRole("button",{name:/Valider/})).toBeNull();
    fireEvent.click(screen.getByRole("checkbox",{name:/Avancer l’entrée A2/}));
    fireEvent.click(screen.getByRole("button",{name:"Évaluer les actions"}));
    await screen.findByRole("button",{name:"Valider l’action"});
    fireEvent.click(screen.getByRole("checkbox",{name:/Avancer l’entrée A2/}));
    expect(screen.queryByRole("button",{name:/Valider/})).toBeNull();
    fireEvent.click(screen.getByRole("checkbox",{name:/Avancer l’entrée A2/}));
    fireEvent.click(screen.getByRole("button",{name:"Évaluer les actions"}));
    fireEvent.click(await screen.findByRole("button",{name:"Valider l’action"}));
    await screen.findByText("Décision validée");
    expect(submitted).toEqual({ward_id:"u2",context_id:"rives",objective:"bed_wait",action_ids:["r"],preview_id:manual.id});
  });

  it("garde la même combinaison, son coût et sa validation quand on passe d’Unité à Action", async()=>{
    const m = menu();
    let reads = 0, writes = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/plans?")) { reads++; return json(m); }
      writes++; return json(commit(m));
    }));
    const page = render(<Host view="unite"/>);
    const summary = () => within(screen.getByRole("region",{name:"Recommandation de l’unité"}));
    await summary().findByRole("heading",{name:"Coordonner 2 actions"});
    expect(summary().getByRole("link",{name:"Ouvrir dans Action"}).getAttribute("href")).toBe("#/action");
    expect(summary().getByText("Renfort IDE")).toBeTruthy();
    expect(summary().getByText("Avancer l’entrée A2")).toBeTruthy();
    expect(summary().getByText("90 €")).toBeTruthy();
    expect(summary().getByText(/4,5 heures-patients/)).toBeTruthy();
    expect(screen.getByRole("heading",{name:"Libérer"})).toBeTruthy();
    expect(screen.getByText("S2")).toBeTruthy();
    page.rerender(<Host view="action"/>);
    expect(summary().getByRole("heading",{name:"Coordonner 2 actions"})).toBeTruthy();
    fireEvent.click(summary().getByRole("button",{name:"Valider les 2 actions"}));
    await summary().findByText("Décision validée");
    page.rerender(<Host view="unite"/>);
    expect(summary().getByText("Choix enregistré dans le journal de l’établissement.")).toBeTruthy();
    expect(reads).toBe(1);
    expect(writes).toBe(1);
  });

  it("restaure la priorité et le brouillon du même épisode après recharge en exigeant une nouvelle évaluation", async()=>{
    const reads: string[] = [];
    vi.stubGlobal("fetch",vi.fn(async(url:string)=>{
      const objective=new URL(url,"http://local").searchParams.get("objective") as ComparisonObjective;
      reads.push(objective); return json(menu("u2", objective));
    }));
    const first=render(<Host/>);
    await screen.findByRole("button",{name:"Valider les 2 actions"});
    fireEvent.change(screen.getByLabelText("Priorité de l’unité"),{target:{value:"uncovered_care"}});
    await screen.findByRole("button",{name:"Valider l’action"});
    fireEvent.click(screen.getByRole("button",{name:"Ajuster les actions"}));
    fireEvent.click(screen.getByRole("checkbox",{name:/Avancer l’entrée A2/}));
    first.unmount();
    const second=render(<Host view="unite"/>);
    const summary=within(screen.getByRole("region",{name:"Recommandation de l’unité"}));
    expect(await summary.findByText("Avancer l’entrée A2")).toBeTruthy();
    expect(summary.getByRole("heading",{name:"Composition à évaluer"})).toBeTruthy();
    expect(summary.queryByText("90 €")).toBeNull();
    second.rerender(<Host view="action"/>);
    expect((screen.getByLabelText("Priorité de l’unité") as HTMLSelectElement).value).toBe("uncovered_care");
    expect((screen.getByRole("checkbox",{name:/Renfort IDE/}) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("checkbox",{name:/Avancer l’entrée A2/}) as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByRole("button",{name:/Valider/})).toBeNull();
    expect(reads).toEqual(["bed_wait","uncovered_care","uncovered_care"]);
  });

  it("restaure uniquement l’identifiant d’une alternative et actualise ses mesures serveur", async()=>{
    let round = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      const m = menu(); const alt=evaluate(["r"]); alt.ward_metrics!.bed_wait_patient_hours = round++ ? 20 : 18;
      m.recommendations.push(alt); return json(m);
    }));
    const first=render(<Host/>);
    await screen.findByRole("button",{name:"Valider les 2 actions"});
    fireEvent.click(screen.getByText("Comparer les alternatives"));
    fireEvent.click(screen.getAllByRole("radio")[1]!);
    expect(screen.getByText("18")).toBeTruthy();
    first.unmount();
    render(<Host/>);
    await screen.findByRole("button",{name:"Valider l’action"});
    expect(screen.getByRole("heading",{name:"Renfort IDE"})).toBeTruthy();
    expect(screen.getByText("20")).toBeTruthy();
    expect(screen.queryByText("18")).toBeNull();
  });

  it("bloque une réponse au mauvais périmètre ou privée de ses mesures locales",()=>{
    expect(()=>readUnitMenu(menu("u1"),"bed_wait","u2","rives")).toThrow();
    expect(()=>readUnitMenu({...menu(),ward_state:null},"bed_wait","u2","rives")).toThrow();
    expect(()=>readUnitMenu({...menu(),recommendations:[{...evaluate(["r"]),ward_metrics:null}]},"bed_wait","u2","rives")).toThrow();
  });
});
