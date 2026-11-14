// HospitalOS decision-support view — auto first, manual scenario second.
// No figure is typed here: every number shown is read from a versioned engine document and
// carries data-src="<doc id>#<JSON pointer>" plus data-raw (its exact value) for audit (T32).

type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any

const TZ = "Europe/Paris";
const $ = (id: string): HTMLElement => document.getElementById(id) as HTMLElement;
const state: { unit: string; snapshot: Json; snapId: string; auto: Json; autoId: string; manual: Json; manualId: string; events: Json[] } = {
  unit: "nominal_auto", snapshot: null, snapId: "", auto: null, autoId: "", manual: null, manualId: "", events: [],
};

const STATUS: Record<string, string> = {
  RECOMMENDATION_READY: "Proposition prête",
  NO_ACTION_PREFERRED: "Rien à changer : la pratique habituelle suffit",
  INSUFFICIENT_DATA: "Abstention : données insuffisantes",
  INFEASIBLE: "Impossible en l'état",
  HYPOTHETICAL_ONLY: "Hypothèse simulée — non exécutable",
  INVALIDATED: "Proposition invalidée",
};

function el(tag: string, attrs: Record<string, string> = {}, ...kids: (Node | string | null)[]): HTMLElement {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const kid of kids) if (kid !== null) node.append(kid);
  return node;
}

function pointer(doc: Json, ptr: string): Json {
  return ptr.split("/").slice(1).reduce((cur: Json, raw) => {
    const token = raw.replace(/~1/g, "/").replace(/~0/g, "~");
    return Array.isArray(cur) ? cur[Number(token)] : cur?.[token];
  }, doc);
}

function fmtNumber(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
}

/** A figure bound to its source document. */
function fig(docId: string, doc: Json, ptr: string, format: (v: Json) => string = (v) => fmtNumber(v)): HTMLElement {
  const value = pointer(doc, ptr);
  const span = el("span", { "data-src": `${docId}#${ptr}`, "data-raw": JSON.stringify(value ?? null) });
  span.textContent = value === null || value === undefined ? "—" : format(value);
  return span;
}

function local(iso: string, withDay = false): string {
  const opts: Intl.DateTimeFormatOptions = { timeZone: TZ, hour: "2-digit", minute: "2-digit" };
  if (withDay) Object.assign(opts, { weekday: "short", day: "2-digit", month: "short" });
  return new Intl.DateTimeFormat("fr-FR", opts).format(new Date(iso));
}

async function api(path: string, body?: Json): Promise<Json> {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? res.statusText);
  return data;
}

function evalIndex(reco: Json, planId: string | null): number {
  if (!planId || !reco.bundle) return -1;
  return reco.bundle.evaluations.findIndex((e: Json) => e.plan.plan_id === planId);
}

function option(id: string): Json {
  return state.snapshot.reinforcements.find((r: Json) => r.option_id === id);
}

function actionText(a: Json): HTMLElement {
  const li = el("li");
  if (a.type === "coordinate_discharge") {
    li.append(`Coordonner la sortie de ${a.target} : départ visé ${local(a.window_start)} (transport demandé maintenant, nettoyage après départ)`);
  } else if (a.type === "reinforcement") {
    const o = option(a.target);
    li.append(`Renfort ${o?.skill ?? ""} ${local(a.window_start)}–${local(a.window_end)} (${a.target}, ${o?.source ?? ""})`);
    if (a.conditional) li.append(el("span", { class: "ds-tag ds-tag--cond" }, `demandé, non confirmé`));
  } else if (a.type === "locked_discharge") {
    li.append(`Sortie de ${a.target} à ${local(a.window_start)}`);
  } else if (a.type === "locked_extension") {
    li.append(`Présence de ${a.target} prolongée jusqu'à ${local(a.window_start)} (${a.preconditions[0]})`);
  }
  if (a.origin === "manual_lock") li.append(el("span", { class: "ds-tag ds-tag--lock" }, "verrouillé"));
  if (a.basis === "hypothesis_only") li.append(el("span", { class: "ds-tag ds-tag--cond" }, "hypothèse"));
  return li;
}

function figures(docId: string, reco: Json, i: number, base: number): HTMLElement {
  const p = `/bundle/evaluations/${i}/metrics`;
  const b = `/bundle/evaluations/${base}/metrics`;
  const box = el("div", { class: "ds-figs" });
  const item = (label: string, ...value: (Node | string)[]) =>
    box.append(el("div", { class: "ds-fig" }, el("small", {}, label), el("b", {}, ...value)));
  item("Minutes de soins non couvertes", fig(docId, reco, `${b}/uncovered_care_minutes`), " → ", fig(docId, reco, `${p}/uncovered_care_minutes`));
  item("Attente de lit (patients·h)", fig(docId, reco, `${b}/waiting_patient_hours`), " → ", fig(docId, reco, `${p}/waiting_patient_hours`));
  item("IDE requis au pic (total)", fig(docId, reco, `${p}/max_total_staff_required/IDE`));
  item("IDE en plus du planning (pic)", fig(docId, reco, `${p}/max_additional_staff_required/IDE`));
  item("Heures de renfort", fig(docId, reco, `${p}/reinforcement_hours`));
  item("Pression max (score expérimental)", fig(docId, reco, `${b}/peak_pressure`), " → ", fig(docId, reco, `${p}/peak_pressure`));
  item("Heures au-dessus du seuil", fig(docId, reco, `${b}/hours_above_threshold`), " → ", fig(docId, reco, `${p}/hours_above_threshold`));
  item("Lits remis à disposition", fig(docId, reco, `${p}/beds_returned`));
  return box;
}

function chart(reco: Json, i: number, base: number): HTMLElement {
  const ev = reco.bundle.evaluations;
  const series = [
    { name: "Pratique habituelle", color: "var(--ink-3)", pts: ev[base].trajectory },
    { name: "Plan", color: "var(--hos-violet)", pts: ev[i].trajectory },
  ];
  const W = 640, H = 180, pad = 28, n = series[0].pts.length;
  const x = (h: number) => pad + (h * (W - 2 * pad)) / Math.max(1, n - 1);
  const threshold = reco.bundle.score.threshold;
  const yMax = 10;
  const y = (v: number) => H - pad - (v * (H - 2 * pad)) / yMax;
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Trajectoire horaire du score de pression expérimental, pratique habituelle et plan");
  const line = (x1: number, y1: number, x2: number, y2: number, stroke: string, dash = "") => {
    const l = document.createElementNS(svgNS, "line");
    Object.entries({ x1, y1, x2, y2, stroke, "stroke-dasharray": dash, "stroke-width": 1 }).forEach(([k, v]) => l.setAttribute(k, String(v)));
    svg.append(l);
  };
  line(pad, y(0), W - pad, y(0), "var(--line-strong)");
  if (typeof threshold === "number") line(pad, y(threshold), W - pad, y(threshold), "var(--alerte)", "4 4");
  for (const s of series) {
    if (s.pts.some((p: Json) => p.pressure_score === null)) continue;
    const path = document.createElementNS(svgNS, "polyline");
    path.setAttribute("points", s.pts.map((p: Json, h: number) => `${x(h)},${y(p.pressure_score)}`).join(" "));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", s.color);
    path.setAttribute("stroke-width", "2.5");
    svg.append(path);
  }
  for (let h = 0; h < n; h += 4) {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", String(x(h)));
    t.setAttribute("y", String(H - 8));
    t.setAttribute("font-size", "11");
    t.setAttribute("fill", "var(--ink-3)");
    t.setAttribute("text-anchor", "middle");
    t.textContent = series[0].pts[h].local_label;
    svg.append(t);
  }
  const legend = el("div", { class: "ds-legend" },
    ...series.map((s) => el("span", {}, el("i", { class: "ds-sw", style: `background:${s.color}` }), s.name)),
    el("span", {}, el("i", { class: "ds-sw", style: "background:var(--alerte)" }), `seuil (${reco.bundle.score.score_status})`));
  return el("div", { class: "ds-card ds-chart" }, el("h3", {}, "Trajectoire de pression, heure par heure"), svg, legend,
    el("p", { class: "ds-muted" }, "Moyennes ponctuelles sur les scénarios de prévision : pas une garantie simultanée sur tout l'horizon. Le pic et le temps au-dessus du seuil comptent autant que la valeur finale."));
}

function statusChip(reco: Json): HTMLElement {
  return el("span", { class: `ds-status ds-status--${reco.status}`, "data-testid": "status", "data-status": reco.status }, STATUS[reco.status] ?? reco.status);
}

function list(title: string, items: string[]): HTMLElement | null {
  if (!items.length) return null;
  return el("details", { class: "ds-details" }, el("summary", {}, `${title} (${items.length})`), el("ul", { class: "facts" }, ...items.map((t) => el("li", {}, t))));
}

function reviewButtons(docId: string, reco: Json, target: HTMLElement, onModify?: () => void): HTMLElement {
  const box = el("div", { class: "ds-buttons" });
  const feedback = el("p", { class: "ds-feedback", "data-testid": "review-feedback", role: "status" });
  const send = async (decision: string) => {
    const r = await api("/api/review", {
      unit: state.unit, recommendation_id: reco.recommendation_id, decision,
      idempotency_key: `${reco.recommendation_id}:${decision}`,
    });
    const outcome = r.review.outcome;
    feedback.dataset.outcome = outcome;
    const texts: Record<string, string> = {
      APPROVED_IN_DEMO: "Validée dans la démonstration. Aucune commande n'a été envoyée ; agissez dans vos outils habituels.",
      REJECTED: "Refusée. Merci, c'est noté.",
      MODIFY_REQUESTED: "Modification demandée.",
      INVALIDATED: `Proposition invalidée (${r.review.reasons.join(", ")}). Un recalcul est nécessaire avant toute validation.`,
      REFUSED: `Validation impossible : ${r.review.reasons.join(", ")}.`,
    };
    feedback.textContent = texts[outcome] ?? outcome;
    if (r.review.recompute_required) {
      const again = el("button", { class: "btn", type: "button", "data-testid": "recompute" }, "Recalculer maintenant");
      again.addEventListener("click", () => void loadAuto());
      feedback.append(" ", again);
    }
  };
  const approve = el("button", { class: "btn btn--primary", type: "button", "data-testid": "approve" }, "Valider (démo)") as HTMLButtonElement;
  approve.disabled = !reco.approvable;
  if (!reco.approvable) approve.title = "Non approuvable : hypothèse, abstention ou impossibilité";
  approve.addEventListener("click", () => void send("approve"));
  const reject = el("button", { class: "btn", type: "button", "data-testid": "reject" }, "Refuser");
  reject.addEventListener("click", () => void send("reject"));
  box.append(approve, reject);
  if (onModify) {
    const modify = el("button", { class: "btn btn--quiet", type: "button", "data-testid": "modify" }, "Modifier");
    modify.addEventListener("click", onModify);
    box.append(modify);
  }
  target.append(box, feedback);
  void docId;
  return box;
}

function renderAuto(): void {
  const { auto: reco, autoId: id } = state;
  const body = $("auto-body");
  body.replaceChildren();
  const top = el("div", { class: "ds-card ds-card--primary", "data-testid": "auto-card" }, statusChip(reco));
  body.append(top);
  if (!reco.bundle) {
    top.append(el("p", {}, "HospitalOS s'abstient plutôt que d'inventer des valeurs."),
      el("ul", { class: "facts", "data-testid": "diagnostics" }, ...reco.diagnostics.map((d: string) => el("li", { class: "ds-err" }, d))));
    renderProvenance(reco, id);
    return;
  }
  const i = evalIndex(reco, reco.primary_plan_id);
  const base = evalIndex(reco, reco.baseline_plan_id);
  const primary = reco.bundle.evaluations[i];
  top.append(el("h3", {}, primary.plan.actions.length ? "Plan prioritaire" : "Maintenir la pratique habituelle"));
  if (primary.plan.actions.length) top.append(el("ol", { class: "ds-actions", "data-testid": "actions" }, ...primary.plan.actions.map(actionText)));
  else top.append(el("p", {}, "Aucune action n'apporte d'amélioration matérielle selon l'objectif versionné : rien n'est ajouté pour animer l'écran."));
  top.append(figures(id, reco, i, base));
  if (primary.conditional_on.length) {
    top.append(el("p", { class: "ds-warn", "data-testid": "conditional" }, `Résultat conditionnel : ${primary.conditional_on.join(", ")} demandé(s) mais non confirmé(s). Sans ce renfort : `,
      fig(id, reco, `/bundle/evaluations/${i}/confirmed_only/uncovered_care_minutes`), " minutes non couvertes."));
  }
  const det = el("div", {});
  [list("Raisons", reco.reasons), list("Conditions", reco.conditions), list("Incertitudes", reco.uncertainties)].forEach((n) => n && det.append(n));
  top.append(det);
  reviewButtons(id, reco, top, () => openManual(primary));
  if (reco.alternative_plan_id) {
    const a = evalIndex(reco, reco.alternative_plan_id);
    body.append(el("div", { class: "ds-card", "data-testid": "alternative" }, el("h3", {}, "Alternative réellement distincte"),
      el("ol", { class: "ds-actions" }, ...reco.bundle.evaluations[a].plan.actions.map(actionText)),
      el("p", {}, "Minutes non couvertes : ", fig(id, reco, `/bundle/evaluations/${a}/metrics/uncovered_care_minutes`),
        " · heures de renfort : ", fig(id, reco, `/bundle/evaluations/${a}/metrics/reinforcement_hours`))));
  }
  body.append(chart(reco, i, base));
  const s = reco.bundle.search;
  const rejected = Object.entries(s.rejected).map(([k, v]) => `${k} : ${v}`);
  body.append(el("div", { class: "ds-card", "data-testid": "search" }, el("h3", {}, "Recherche"),
    el("p", {}, fig(id, reco, "/bundle/search/evaluated"), " plans évalués sur ", fig(id, reco, "/bundle/search/enumerated"), " admissibles ; recherche ",
      fig(id, reco, "/bundle/search/complete", (v) => (v ? "complète sur cet univers borné" : "incomplète : meilleur parmi les évalués, aucun optimum revendiqué"))),
    list("Écartés et pourquoi", rejected) ?? ""));
  renderProvenance(reco, id);
}

function renderProvenance(reco: Json, id: string): void {
  const b = reco.bundle;
  $("prov").replaceChildren(el("span", {}, `Recommandation ${reco.recommendation_id}`), el("span", {}, `moteur ${reco.engine_version}`),
    el("span", {}, `objectif ${reco.objective_version}`), el("span", {}, `snapshot ${reco.snapshot_id}`),
    el("span", {}, b ? `backend ${b.backend.name} ${b.backend.version} (${b.backend.code_sha256.slice(0, 12)})` : "pas de prévision"),
    el("span", {}, `${reco.scientific_status} · validation clinique : non · G2 ${reco.g2}`), el("span", { class: "hash" }, `doc ${id}`));
}

// ------------------------------------------------------------------ manual mode (secondary)

function hourOptions(selected: string | null): HTMLElement[] {
  const start = new Date(state.snapshot.as_of).getTime();
  const out: HTMLElement[] = [];
  for (let h = 1; h < 24; h++) {
    const iso = new Date(start + h * 3600_000).toISOString().replace(".000Z", "+00:00");
    const o = el("option", { value: iso }, local(iso, true));
    if (selected && new Date(selected).getTime() === new Date(iso).getTime()) o.setAttribute("selected", "");
    out.push(o);
  }
  return out;
}

function openManual(fromPlan?: Json): void {
  const form = $("manual-form") as HTMLFormElement;
  form.hidden = false;
  $("open-manual").hidden = true;
  const stays: Json[] = state.snapshot.stays;
  const coord = fromPlan?.plan.actions.find((a: Json) => a.type === "coordinate_discharge");
  const x1Default = coord?.target ?? stays.find((s) => s.medical_authorization === "authorized")?.stay_id ?? stays[0].stay_id;
  const x2Default = stays.find((s) => s.planned_departure)?.stay_id ?? "";
  const stayOpt = (s: Json, sel: string) => {
    const o = el("option", { value: s.stay_id }, `${s.stay_id} — autorisation : ${s.medical_authorization}`);
    if (s.stay_id === sel) o.setAttribute("selected", "");
    return o;
  };
  const x2 = stays.find((s) => s.stay_id === x2Default);
  form.replaceChildren(
    el("fieldset", {}, el("legend", {}, "X1 — sortie à une heure donnée"),
      el("div", { class: "ds-row" },
        el("label", {}, "Séjour", el("select", { name: "x1" }, ...stays.map((s) => stayOpt(s, x1Default)))),
        el("label", {}, "Heure", el("select", { name: "x1_at" }, ...hourOptions(coord?.window_start ?? null))),
        el("label", {}, "Statut", el("select", { name: "x1_basis" }, el("option", { value: "validated_instruction" }, "instruction validée"), el("option", { value: "hypothesis_only" }, "hypothèse seulement"))))),
    el("fieldset", {}, el("legend", {}, "X2 — présence prolongée de t heures"),
      el("div", { class: "ds-row" },
        el("label", {}, "Séjour", el("select", { name: "x2" }, el("option", { value: "" }, "aucun"), ...stays.map((s) => stayOpt(s, x2Default)))),
        el("label", {}, "Heure de référence", el("select", { name: "x2_ref" }, ...hourOptions(x2?.planned_departure ?? null))),
        el("label", {}, "t (heures)", el("input", { name: "x2_t", type: "number", min: "0", max: "12", value: "4", "data-testid": "x2-t" })))),
    el("fieldset", {}, el("legend", {}, "Renforts et échéance"),
      el("div", { class: "ds-row" }, ...state.snapshot.reinforcements.map((r: Json) =>
        el("label", {}, `${r.option_id} (${r.skill}, ${r.confirmation})`, el("select", { name: `r_${r.option_id}` },
          el("option", { value: "free" }, "laisser chercher"), el("option", { value: "include" }, "imposer"), el("option", { value: "exclude" }, "exclure")))),
        el("label", {}, "Jusqu'à demain", el("input", { name: "deadline", type: "time", value: "20:00" }))),
      el("label", {}, el("span", {}, el("input", { name: "complements", type: "checkbox", checked: "" }), " rechercher des compléments compatibles"))),
    el("div", { class: "ds-buttons" }, el("button", { class: "btn btn--primary", type: "submit", "data-testid": "run-manual" }, "Calculer avec le même moteur")),
  );
}

async function runManual(ev: Event): Promise<void> {
  ev.preventDefault();
  const f = new FormData(ev.target as HTMLFormElement);
  const locks: Json[] = [{ kind: "discharge_at", stay_id: f.get("x1"), at: f.get("x1_at"), basis: f.get("x1_basis") }];
  if (f.get("x2")) locks.push({ kind: "extend_presence", stay_id: f.get("x2"), reference_time: f.get("x2_ref"), extension_hours: Number(f.get("x2_t")), basis: "validated_instruction" });
  for (const r of state.snapshot.reinforcements) {
    const v = f.get(`r_${r.option_id}`);
    if (v !== "free") locks.push({ kind: "reinforcement", option_id: r.option_id, include: v === "include" });
  }
  const payload = { unit: state.unit, locks: { locks, deadline: { day_offset: 1, local_time: `${f.get("deadline")}:00` }, search_complements: f.get("complements") === "on" } };
  const body = $("manual-body");
  try {
    const r = await api("/api/simulate", payload);
    state.manual = r.recommendation;
    state.manualId = r.doc_id;
    renderManual();
  } catch (error) {
    body.replaceChildren(el("p", { class: "ds-err", "data-testid": "manual-error" }, String(error)));
  }
}

function renderManual(): void {
  const { manual: reco, manualId: id } = state;
  const body = $("manual-body");
  const card = el("div", { class: "ds-card", "data-testid": "manual-card" }, statusChip(reco));
  body.replaceChildren(card);
  if (!reco.bundle) {
    card.append(el("ul", { class: "facts", "data-testid": "manual-diagnostics" }, ...reco.diagnostics.map((d: string) => el("li", { class: "ds-err" }, d))));
    return;
  }
  const rows: [string, string | null][] = [["Pratique habituelle", reco.baseline_plan_id], ["Scénario verrouillé seul", reco.locked_plan_id], ["Verrouillé + compléments", reco.primary_plan_id]];
  const table = el("table", { class: "ds-table", "data-testid": "branches" }, el("thead", {}, el("tr", {}, el("th", {}, "Branche"), el("th", {}, "Non couvert (min)"), el("th", {}, "Attente (patients·h)"), el("th", {}, "Renfort (h)"))));
  const tb = el("tbody");
  for (const [label, pid] of rows) {
    const i = evalIndex(reco, pid);
    if (i < 0) continue;
    const m = `/bundle/evaluations/${i}/metrics`;
    tb.append(el("tr", {}, el("td", {}, label), el("td", { class: "n" }, fig(id, reco, `${m}/uncovered_care_minutes`)), el("td", { class: "n" }, fig(id, reco, `${m}/waiting_patient_hours`)), el("td", { class: "n" }, fig(id, reco, `${m}/reinforcement_hours`))));
  }
  table.append(tb);
  const i = evalIndex(reco, reco.primary_plan_id);
  card.append(el("ol", { class: "ds-actions", "data-testid": "manual-actions" }, ...reco.bundle.evaluations[i].plan.actions.map(actionText)), el("div", { class: "ds-scroll" }, table));
  if (reco.status === "HYPOTHETICAL_ONLY") card.append(el("p", { class: "ds-warn" }, "Simulation conditionnelle d'une hypothèse : elle ne peut pas devenir un plan exécutable."));
  const det = el("div", {});
  [list("Raisons", reco.reasons), list("Diagnostics", reco.diagnostics), list("Conditions", reco.conditions)].forEach((n) => n && det.append(n));
  card.append(det);
  reviewButtons(id, reco, card);
}

// ------------------------------------------------------------------ boot

async function loadAuto(): Promise<void> {
  $("auto-body").replaceChildren(el("p", { class: "ds-muted" }, "Calcul en cours…"));
  const r = await api(`/api/auto?unit=${encodeURIComponent(state.unit)}`);
  state.snapshot = r.snapshot;
  state.snapId = r.snapshot_doc_id;
  state.auto = r.recommendation;
  state.autoId = r.doc_id;
  $("asof").replaceChildren("Situation au ", fig(state.snapId, state.snapshot, "/as_of", (v) => local(v, true)), " (Europe/Paris)");
  renderAuto();
  const events = state.events.filter((e) => e.unit === state.unit);
  if (events.length) {
    const bar = el("div", { class: "demobar" }, "Démonstration :");
    for (const e of events) {
      const b = el("button", { class: "btn btn--quiet", type: "button", "data-testid": `inject-${e.id}` }, e.label);
      b.addEventListener("click", async () => { await api("/api/inject", { unit: state.unit, event: e.id }); b.setAttribute("disabled", ""); b.textContent = `${e.label} — reçue. Validez pour voir l'invalidation, puis recalculez.`; });
      bar.append(b);
    }
    const reset = el("button", { class: "btn btn--quiet", type: "button" }, "Réinitialiser la démo");
    reset.addEventListener("click", async () => { await api("/api/reset", { unit: state.unit }); await loadAuto(); });
    bar.append(reset);
    $("auto-body").append(bar);
  }
  ($("manual-form") as HTMLFormElement).hidden = true;
  $("open-manual").hidden = false;
  $("manual-body").replaceChildren();
}

async function boot(): Promise<void> {
  const meta = await api("/api/units");
  state.events = meta.events;
  const select = $("unit") as HTMLSelectElement;
  select.replaceChildren(...meta.units.map((u: Json) => el("option", { value: u.id }, u.name)));
  select.addEventListener("change", () => { state.unit = select.value; void loadAuto(); });
  $("open-manual").addEventListener("click", () => openManual(state.auto?.bundle?.evaluations[evalIndex(state.auto, state.auto.primary_plan_id)]));
  $("manual-form").addEventListener("submit", (e) => void runManual(e));
  await loadAuto(); // automatic recommendation first, without any user input
}

void boot();
