"use strict";
// HospitalOS decision-support view — auto first, manual scenario second. Same grammar and
// words as the cockpit's « Plan 24 h » (web/src/ui/DecisionPlan.tsx, src/domain/planLabels.ts):
// band, title, actions with their basis, the effect, two answers; the rest one click away.
// No figure is typed here: every number shown is read from a versioned engine document and
// carries data-src="<doc id>#<JSON pointer>" plus data-raw (its exact value) for audit (T32).
const TZ = "Europe/Paris";
const $ = (id) => document.getElementById(id);
const state = {
    unit: "nominal_auto", snapshot: null, snapId: "", auto: null, autoId: "", manual: null, manualId: "", events: [],
};
const STATUS = {
    RECOMMENDATION_READY: "Plan proposé",
    NO_ACTION_PREFERRED: "Rien à changer",
    INSUFFICIENT_DATA: "Données à vérifier",
    INFEASIBLE: "Impossible en l'état",
    HYPOTHETICAL_ONLY: "Hypothèse simulée, non applicable",
    INVALIDATED: "Proposition invalidée",
};
function el(tag, attrs = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs))
        node.setAttribute(k, v);
    for (const kid of kids)
        if (kid !== null)
            node.append(kid);
    return node;
}
function pointer(doc, ptr) {
    return ptr.split("/").slice(1).reduce((cur, raw) => {
        const token = raw.replace(/~1/g, "/").replace(/~0/g, "~");
        return Array.isArray(cur) ? cur[Number(token)] : cur?.[token];
    }, doc);
}
function fmtNumber(v) {
    return Number.isInteger(v) ? String(v) : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
}
/** A figure bound to its source document. */
function fig(docId, doc, ptr, format = (v) => fmtNumber(v)) {
    const value = pointer(doc, ptr);
    const span = el("span", { "data-src": `${docId}#${ptr}`, "data-raw": JSON.stringify(value ?? null) });
    span.textContent = value === null || value === undefined ? "—" : format(value);
    return span;
}
function local(iso, withDay = false) {
    const opts = { timeZone: TZ, hour: "2-digit", minute: "2-digit" };
    if (withDay)
        Object.assign(opts, { weekday: "short", day: "2-digit", month: "short" });
    return new Intl.DateTimeFormat("fr-FR", opts).format(new Date(iso));
}
async function api(path, body) {
    const res = await fetch(path, body === undefined ? {} : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok)
        throw new Error(data.error ?? res.statusText);
    return data;
}
function evalIndex(reco, planId) {
    if (!planId || !reco.bundle)
        return -1;
    return reco.bundle.evaluations.findIndex((e) => e.plan.plan_id === planId);
}
function option(id) {
    return state.snapshot.reinforcements.find((r) => r.option_id === id);
}
// ------------------------------------------------------------------ words (mirror of planLabels.ts)
const SOURCE = { internal_pool: "pool interne", interim: "intérim" };
const BASIS = {
    observed_authorization: ["autorisation médicale observée", "fact"],
    validated_instruction: ["consigne validée", "choice"],
    hypothesis_only: ["hypothèse", "hypothesis"],
    resource_option: ["option de renfort", "option"],
};
const CONFIRMATION = {
    confirmed: "confirmé", requested: "demandé, non confirmé", not_requested: "non demandé", unknown: "confirmation inconnue",
};
const AUTHORIZATION = {
    authorized: "sortie autorisée", not_authorized: "sortie non autorisée", revoked: "autorisation retirée", unknown: "autorisation inconnue",
};
/** Same reasons as the cockpit (journal.ts PLAN_REASONS): one habit, comparable refusals. */
const REASONS = [
    ["already_done", "Déjà fait ou déjà prévu"],
    ["information_missing", "Information manquante ou fausse"],
    ["clinical_priority", "Autre priorité clinique"],
    ["resource_unavailable", "Ressource indisponible"],
    ["plan_unsuitable", "Inadapté à l'unité (effectif, compétences, règles)"],
    ["other", "Autre raison"],
];
const REASON = {
    lexicographic_objective_improvement_requires_human_approval: "Le plan fait mieux que la pratique habituelle : il attend votre décision.",
    habitual_practice_preferred_no_material_improvement: "Aucun plan ne fait sensiblement mieux que la pratique habituelle.",
    abstention_data_insufficient: "Données insuffisantes : HospitalOS préfère ne rien proposer.",
    complements_to_locked_scenario_require_human_approval: "Des compléments sont proposés autour de vos choix : ils attendent votre décision.",
    conditional_simulation_of_hypothesis_not_executable: "Simulation d'une hypothèse : elle ne peut pas devenir un plan à appliquer.",
    locked_scenario_violates_constraints: "Vos choix enfreignent une contrainte : ce plan est impossible.",
};
const CONDITION = {
    medical_authorization_observed_at_decision: "autorisation médicale observée au moment du calcul",
    revalidate_authorization_before_approval: "revérifier l'autorisation avant de valider",
    transport_requested_now_lead_time_respected: "demander le transport maintenant",
    cleaning_only_after_effective_departure: "bionettoyage seulement après le départ effectif",
    "fixed departure hour": "heure de départ imposée",
    "basis:validated_instruction": "consigne validée",
    "basis:hypothesis_only": "hypothèse seulement",
    user_lock_not_a_system_clinical_decision: "votre choix, pas une décision clinique du système",
    "confirmation:requested": "demandé, non confirmé",
    "confirmation:confirmed": "confirmé",
    "requested, NOT confirmed -> result conditional on its presence": "le résultat suppose qu'il vienne",
};
const REJECT = {
    no_target_hour_before_habitual_plan: "aucune heure utile avant le départ déjà prévu",
    medical_authorization_not_authorized: "sortie non autorisée",
    medical_authorization_revoked: "autorisation retirée",
    destination_unknown: "destination inconnue",
    transport_need_unknown: "besoin de transport inconnu",
    readiness_estimate_unknown: "heure de préparation inconnue",
    "obstacle:aval_non_confirme": "aval non confirmé",
};
function provenance(o) {
    if (!o)
        return "provenance inconnue";
    if (o.source === "shared_unit")
        return o.lending_unit ? `prêté par ${o.lending_unit}` : "prêté par une unité non renseignée";
    return SOURCE[o.source] ?? String(o.source);
}
function humanReasons(reasons) {
    const out = [];
    for (const r of reasons) {
        if (REASON[r])
            out.push(REASON[r]);
        else if (r.startsWith("plan remains insufficient"))
            out.push("Même avec ce plan, des soins restent non couverts : il réduit le manque sans le combler.");
    }
    return out;
}
function subject(prefix) {
    const [kind, a, b] = prefix.split(":");
    if (kind === "coord")
        return `Sortie de ${a}`;
    if (kind === "renfort")
        return `Renfort ${a}`;
    if (kind === "lock" && a === "locked_discharge")
        return `Sortie imposée de ${b}`;
    if (kind === "lock" && a === "locked_extension")
        return `Prolongation de ${b}`;
    return prefix;
}
function conditions(list) {
    const groups = new Map();
    for (const c of list) {
        const cut = c.lastIndexOf(": ");
        const [head, code] = cut < 0 ? ["", c] : [c.slice(0, cut), c.slice(cut + 2)];
        if (code.startsWith("skill:"))
            continue;
        const about = head ? subject(head) : "Plan";
        groups.set(about, [...(groups.get(about) ?? []), CONDITION[code] ?? code]);
    }
    if (!groups.size)
        return null;
    return el("ul", { class: "ds-conds" }, ...[...groups].map(([about, items]) => el("li", {}, el("b", {}, about), ` : ${items.join(" · ")}`)));
}
function uncertainty(u) {
    let m = /^(\d+) forecast scenarios/.exec(u);
    if (m)
        return `Calculé sur ${m[1]} scénarios, les mêmes que ceux qui ont servi à choisir le plan.`;
    m = /^uncovered minutes range over scenarios: ([\d.]+)\.\.([\d.]+)/.exec(u);
    if (m)
        return `Selon le scénario, de ${Number(m[1])} à ${Number(m[2])} minutes de soins non couvertes.`;
    if (u.startsWith("pointwise scenario means"))
        return "Moyennes heure par heure : pas une garantie sur toute la période.";
    if (u.startsWith("synthetic declared distributions"))
        return "Durées déclarées pour la démonstration, non calibrées sur un établissement réel.";
    return u;
}
function rejection(key, codes) {
    const r = option(key);
    const about = r ? `Renfort ${r.skill} ${key}, ${provenance(r)}` : `Sortie de ${key}`;
    const why = codes.split(",").map((c) => {
        const m = /^violates_lending_unit_minimum:([^:]+):(\d+)-(\d+)<(\d+)$/.exec(c);
        return m ? `le prêt laisserait ${m[1]} sous son minimum (${m[2]} − ${m[3]}, minimum ${m[4]})` : (REJECT[c] ?? c);
    }).join(", ");
    return el("li", {}, el("b", {}, about), ` : ${why}`);
}
function diagnostic(d) {
    let m = /^roster_unknown:([^:]+):(.+)$/.exec(d);
    let text = d;
    if (m)
        text = `Planning ${m[1]} inconnu sur ${m[2]}`;
    else if ((m = /^locked_transport_unavailable:([^:]+):/.exec(d)))
        text = `Aucun transport disponible pour la sortie imposée de ${m[1]}`;
    return el("li", {}, text, " ", el("code", { class: "ds-code" }, d));
}
function bullets(items) {
    return items.length ? el("ul", { class: "facts" }, ...items.map((t) => el("li", {}, t))) : null;
}
function details(title, ...kids) {
    const shown = kids.filter((k) => k !== null);
    if (!shown.length)
        return null;
    return el("details", { class: "ds-details" }, el("summary", {}, title), el("div", { class: "ds-details__body" }, ...shown));
}
// ------------------------------------------------------------------ pieces
function actionText(a) {
    let text;
    if (a.type === "coordinate_discharge")
        text = `Coordonner la sortie de ${a.target} : départ visé à ${local(a.window_start)}, transport demandé maintenant, bionettoyage après le départ`;
    else if (a.type === "reinforcement") {
        const o = option(a.target);
        text = `Renfort ${o?.skill ?? ""} de ${local(a.window_start)} à ${local(a.window_end)}, ${provenance(o)} (${a.target})`;
    }
    else if (a.type === "locked_discharge")
        text = `Sortie de ${a.target} à ${local(a.window_start)}`;
    else
        text = `Présence de ${a.target} prolongée jusqu'à ${local(a.window_start)}`;
    const tags = el("span", { class: "ds-action__tags" });
    if (a.origin === "manual_lock")
        tags.append(el("span", { class: "ds-tag ds-tag--lock" }, "imposé par vous"));
    const [label, tone] = BASIS[String(a.basis)] ?? [String(a.basis), ""];
    tags.append(el("span", { class: `ds-tag ds-tag--${tone}` }, label));
    const o = a.type === "reinforcement" ? option(a.target) : null;
    // Every reinforcement says whether it is confirmed, not only the doubtful ones (user testing).
    if (a.conditional || o?.confirmation === "requested")
        tags.append(el("span", { class: "ds-tag ds-tag--cond" }, "demandé, non confirmé"));
    else if (o?.confirmation === "confirmed")
        tags.append(el("span", { class: "ds-tag ds-tag--fact" }, "confirmé"));
    else if (o)
        tags.append(el("span", { class: "ds-tag ds-tag--cond" }, CONFIRMATION[o.confirmation] ?? o.confirmation));
    if (o?.source === "shared_unit")
        tags.append(el("span", { class: "ds-tag ds-tag--loan", "data-testid": "lending-unit" }, provenance(o)));
    return el("li", { class: "ds-action", "data-basis": String(a.basis) }, el("span", { class: "ds-action__text" }, text), tags);
}
function value(reco, ptr) {
    const v = pointer(reco, ptr);
    return typeof v === "number" ? v : 0;
}
function effect(docId, reco, i, base) {
    const p = `/bundle/evaluations/${i}/metrics`;
    const b = `/bundle/evaluations/${base}/metrics`;
    const max = Math.max(value(reco, `${b}/uncovered_care_minutes`), value(reco, `${p}/uncovered_care_minutes`), 1);
    const row = (label, ptr, on) => el("div", { class: "pair__row" }, el("span", { class: "pair__label" }, label), el("span", { class: "pair__track" }, el("span", { class: `pair__bar${on ? " pair__bar--on" : ""}`, style: `width:${(value(reco, ptr) / max) * 100}%` })), el("span", { class: "pair__value" }, fig(docId, reco, ptr)));
    const item = (label, ...v) => el("div", { class: "ds-fig" }, el("small", {}, label), el("b", {}, ...v));
    const all = el("div", { class: "ds-figs" }, item("Minutes de soins non couvertes", fig(docId, reco, `${b}/uncovered_care_minutes`), " → ", fig(docId, reco, `${p}/uncovered_care_minutes`)), item("Attente de lit (patients·h)", fig(docId, reco, `${b}/waiting_patient_hours`), " → ", fig(docId, reco, `${p}/waiting_patient_hours`)), item("IDE requis au pic", fig(docId, reco, `${p}/max_total_staff_required/IDE`)), item("IDE en plus du planning au pic", fig(docId, reco, `${p}/max_additional_staff_required/IDE`)), item("Heures de renfort", fig(docId, reco, `${p}/reinforcement_hours`)), item("Tension maximale (score expérimental)", fig(docId, reco, `${b}/peak_pressure`), " → ", fig(docId, reco, `${p}/peak_pressure`)), item("Heures au-dessus du seuil", fig(docId, reco, `${b}/hours_above_threshold`), " → ", fig(docId, reco, `${p}/hours_above_threshold`)), item("Lits remis à disposition", fig(docId, reco, `${p}/beds_returned`)));
    return el("div", { class: "ds-effect", "aria-label": "Effet simulé du plan" }, el("p", { class: "ds-effect__lead" }, `Soins non couverts d'ici ${local(reco.bundle.horizon_end, true)}, en minutes`), el("div", { class: "pair" }, row("Pratique habituelle", `${b}/uncovered_care_minutes`, false), row("Avec le plan", `${p}/uncovered_care_minutes`, true)), el("div", { class: "ds-figs ds-figs--key" }, item("Attente de lit (patients·h)", fig(docId, reco, `${b}/waiting_patient_hours`), " → ", fig(docId, reco, `${p}/waiting_patient_hours`)), item("Heures de renfort", fig(docId, reco, `${p}/reinforcement_hours`)), item("Lits remis à disposition", fig(docId, reco, `${p}/beds_returned`))), details("Tous les indicateurs", all) ?? "");
}
function chart(reco, i, base) {
    const ev = reco.bundle.evaluations;
    const series = [
        { name: "Pratique habituelle", color: "var(--ink-3)", pts: ev[base].trajectory },
        { name: "Avec le plan", color: "var(--brand)", pts: ev[i].trajectory },
    ];
    const W = 640, H = 180, pad = 28, n = series[0].pts.length, top = 10;
    const x = (h) => pad + (h * (W - 2 * pad)) / Math.max(1, n - 1);
    const y = (v) => H - pad - (v * (H - 2 * pad)) / top;
    const threshold = reco.bundle.score.threshold;
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Score de tension expérimental heure par heure, pratique habituelle et plan");
    const add = (tag, attrs, text) => {
        const node = document.createElementNS(svgNS, tag);
        for (const [k, v] of Object.entries(attrs))
            node.setAttribute(k, String(v));
        if (text !== undefined)
            node.textContent = text;
        svg.append(node);
    };
    add("line", { x1: pad, y1: y(0), x2: W - pad, y2: y(0), stroke: "var(--line-strong)" });
    add("text", { x: pad - 6, y: y(0) + 4, "font-size": 11, fill: "var(--ink-3)", "text-anchor": "end" }, "0");
    add("text", { x: pad - 6, y: y(top) + 4, "font-size": 11, fill: "var(--ink-3)", "text-anchor": "end" }, String(top));
    if (typeof threshold === "number")
        add("line", { x1: pad, y1: y(threshold), x2: W - pad, y2: y(threshold), stroke: "var(--alerte)", "stroke-dasharray": "4 4" });
    for (const s of series) {
        if (s.pts.some((p) => p.pressure_score === null))
            continue;
        add("polyline", { points: s.pts.map((p, h) => `${x(h)},${y(p.pressure_score)}`).join(" "), fill: "none", stroke: s.color, "stroke-width": 2.5 });
    }
    for (let h = 0; h < n; h += 4)
        add("text", { x: x(h), y: H - 8, "font-size": 11, fill: "var(--ink-3)", "text-anchor": "middle" }, series[0].pts[h].local_label);
    const legend = el("div", { class: "ds-legend" }, ...series.map((s) => el("span", {}, el("i", { class: "ds-sw", style: `background:${s.color}` }), s.name)), el("span", {}, el("i", { class: "ds-sw ds-sw--dash" }), "Seuil de tension"));
    return el("section", { class: "panel" }, el("header", { class: "panel__head" }, el("h2", { class: "panel__title" }, "Tension heure par heure")), el("div", { class: "panel__body ds-chart" }, svg, legend, el("p", { class: "mute" }, "Score expérimental sur 10, moyenne des scénarios heure par heure : pas une garantie sur toute la période. Le pic et le temps passé au-dessus du seuil comptent autant que l'heure finale.")));
}
function band(reco, right) {
    return el("div", { class: "proposal__band" }, el("span", { class: "proposal__kind", "data-testid": "status", "data-status": reco.status }, STATUS[reco.status] ?? reco.status), right ? el("span", { class: "expiry" }, right) : null);
}
function statusPill(reco) {
    const tone = reco.status === "RECOMMENDATION_READY" ? "brand" : reco.status === "NO_ACTION_PREFERRED" ? "ok" : reco.status === "HYPOTHETICAL_ONLY" ? "warn" : "bad";
    return el("span", { class: `pill pill--${tone}`, "data-testid": "status", "data-status": reco.status }, STATUS[reco.status] ?? reco.status);
}
function reviewButtons(reco, target, onModify) {
    const box = el("div", { class: "proposal__actions" });
    const asking = el("div", { class: "feedback", role: "group" });
    asking.hidden = true;
    const feedbackSlot = el("div", {});
    const send = async (decision, reason) => {
        asking.hidden = true;
        let r;
        const feedback = el("div", { class: "ds-outcome", "data-testid": "review-feedback", role: "status" });
        feedbackSlot.replaceChildren(feedback);
        try {
            r = await api("/api/review", {
                unit: state.unit, recommendation_id: reco.recommendation_id, decision,
                idempotency_key: `${reco.recommendation_id}:${decision}`,
            });
        }
        catch (error) {
            feedback.dataset.outcome = "ERROR";
            feedback.classList.add("ds-outcome--bad");
            feedback.append(el("p", { class: "ds-outcome__title" }, `Demande non traitée : ${String(error)}`));
            return;
        }
        const outcome = r.review.outcome;
        feedback.dataset.outcome = outcome;
        feedback.classList.add(outcome === "APPROVED_IN_DEMO" ? "ds-outcome--todo" : outcome === "REJECTED" ? "ds-outcome--quiet" : "ds-outcome--bad");
        const texts = {
            APPROVED_IN_DEMO: "Plan validé. Rien n'a été envoyé : appliquez-le dans vos outils habituels.",
            REJECTED: "Refus noté, merci : c'est ce qui aide à mieux viser.",
            MODIFY_REQUESTED: "Modification demandée.",
            INVALIDATED: `Proposition invalidée (${r.review.reasons.join(", ")}) : une nouvelle information est arrivée. Recalculez avant de valider.`,
            REFUSED: `Validation impossible : ${r.review.reasons.join(", ")}.`,
        };
        const motif = reason ? ` Motif : ${REASONS.find(([id]) => id === reason)?.[1].toLowerCase() ?? reason}.` : "";
        feedback.append(el("p", { class: "ds-outcome__title" }, (texts[outcome] ?? outcome) + motif));
        if (r.review.replayed)
            feedback.append(el("p", { class: "mute" }, `Reçu déjà enregistré ; validité actuelle : ${r.review.current_validity}.`));
        if (outcome === "APPROVED_IN_DEMO" || outcome === "REJECTED")
            box.hidden = true;
        if (r.review.recompute_required) {
            const again = el("button", { class: "btn btn--small", type: "button", "data-testid": "recompute" }, "Recalculer maintenant");
            again.addEventListener("click", () => void loadAuto());
            feedback.append(el("div", { class: "ds-outcome__actions" }, again));
        }
    };
    const approve = el("button", { class: "btn btn--primary", type: "button", "data-testid": "approve" }, "Valider le plan");
    // A discharge in the plan waits for a person to re-check the medical authorization.
    const recheck = [...new Set(reco.conditions.filter((c) => c.endsWith("revalidate_authorization_before_approval")).map((c) => c.split(":")[1]))];
    const boxes = recheck.map((id) => el("input", { type: "checkbox", "data-testid": `recheck-${id}` }));
    const refresh = () => {
        approve.disabled = !reco.approvable || boxes.some((b) => !b.checked);
        approve.title = !reco.approvable ? "Non applicable : hypothèse, abstention ou impossibilité" : approve.disabled ? "Cochez d'abord la vérification de l'autorisation médicale" : "";
    };
    boxes.forEach((b) => b.addEventListener("change", refresh));
    refresh();
    if (recheck.length && reco.approvable) {
        target.append(el("fieldset", { class: "ds-recheck" }, el("legend", {}, "Avant de valider"), ...recheck.map((id, k) => el("label", { class: "ds-check" }, boxes[k], ` J'ai revérifié l'autorisation médicale de sortie de ${id}`))));
    }
    approve.addEventListener("click", () => void send("approve"));
    const reject = el("button", { class: "btn", type: "button", "data-testid": "reject", "aria-expanded": "false" }, "Refuser");
    reject.addEventListener("click", () => {
        asking.hidden = !asking.hidden;
        reject.setAttribute("aria-expanded", String(!asking.hidden));
        if (!asking.hidden)
            asking.querySelector("button")?.focus();
    });
    asking.append(el("p", { class: "feedback__label" }, "Pourquoi ? Un appui suffit."), el("div", { class: "chips" }, ...REASONS.map(([id, label], k) => {
        const chip = el("button", { class: "chip", type: "button", "data-testid": `reason-${id}` }, el("kbd", { class: "kbd", "aria-hidden": "true" }, String(k + 1)), label);
        chip.addEventListener("click", () => void send("reject", id));
        return chip;
    })));
    box.append(approve, reject);
    if (onModify) {
        const modify = el("button", { class: "btn btn--quiet", type: "button", "data-testid": "modify" }, "Simuler une variante");
        modify.addEventListener("click", onModify);
        box.append(el("span", { class: "spacer" }), modify);
    }
    target.append(box, asking, feedbackSlot);
}
// ------------------------------------------------------------------ automatic plan
function renderAuto() {
    const { auto: reco, autoId: id } = state;
    const body = $("auto-body");
    body.replaceChildren();
    if (!reco.bundle) {
        body.append(el("section", { class: "panel proposal proposal--abstain ds-primary", "data-testid": "auto-card" }, band(reco), el("div", { class: "proposal__main ds-stack" }, el("h2", { class: "proposal__title" }, "Pas de plan pour l'instant"), el("p", {}, "Mieux vaut ne rien proposer qu'inventer des valeurs. Complétez ces informations dans vos outils habituels (planning, dossier), puis recalculez :"), el("ul", { class: "facts ds-err", "data-testid": "diagnostics" }, ...reco.diagnostics.map(diagnostic))), (() => {
            const again = el("button", { class: "btn", type: "button" }, "Recalculer");
            again.addEventListener("click", () => void loadAuto());
            return el("div", { class: "proposal__actions" }, again);
        })()));
        renderHow(reco, id);
        return;
    }
    const i = evalIndex(reco, reco.primary_plan_id);
    const base = evalIndex(reco, reco.baseline_plan_id);
    const primary = reco.bundle.evaluations[i];
    const quiet = !primary.plan.actions.length;
    const main = el("div", { class: "proposal__main ds-stack" }, el("h2", { class: "proposal__title" }, quiet ? "Maintenir la pratique habituelle" : `À organiser d'ici ${local(reco.bundle.horizon_end, true)}`), quiet ? el("p", {}, "Aucune action n'apporte d'amélioration sensible : rien n'est ajouté pour animer l'écran.")
        : el("ol", { class: "ds-actions", "data-testid": "actions" }, ...primary.plan.actions.map(actionText)));
    if (primary.conditional_on.length) {
        main.append(el("p", { class: "ds-warn", "data-testid": "conditional" }, `Le résultat suppose la venue de ${primary.conditional_on.join(", ")}, demandé mais non confirmé. Sans ce renfort : `, fig(id, reco, `/bundle/evaluations/${i}/confirmed_only/uncovered_care_minutes`), " minutes de soins non couvertes."));
    }
    main.append(effect(id, reco, i, base));
    const why = bullets(humanReasons(reco.reasons));
    if (why)
        main.append(why);
    const before = details("Avant de valider : conditions et incertitudes", conditions(reco.conditions), bullets(reco.uncertainties.map(uncertainty)), reco.diagnostics.length ? el("ul", { class: "facts" }, ...reco.diagnostics.map(diagnostic)) : null);
    if (before)
        main.append(before);
    const card = el("section", { class: `panel proposal ds-primary${quiet ? " proposal--quiet" : ""}`, "data-testid": "auto-card" }, band(reco, `Valable jusqu'à ${local(reco.valid_until)}`), main);
    reviewButtons(reco, card, () => openManual(primary));
    body.append(card);
    if (reco.alternative_plan_id) {
        const a = evalIndex(reco, reco.alternative_plan_id);
        body.append(el("section", { class: "panel", "data-testid": "alternative" }, el("header", { class: "panel__head" }, el("h2", { class: "panel__title" }, "Autre plan possible")), el("div", { class: "panel__body ds-stack" }, el("ol", { class: "ds-actions" }, ...reco.bundle.evaluations[a].plan.actions.map(actionText)), el("p", { class: "mute" }, "Soins non couverts : ", fig(id, reco, `/bundle/evaluations/${a}/metrics/uncovered_care_minutes`), " min · renfort : ", fig(id, reco, `/bundle/evaluations/${a}/metrics/reinforcement_hours`), " h"))));
    }
    body.append(chart(reco, i, base));
    renderHow(reco, id);
}
function renderHow(reco, id) {
    const b = reco.bundle;
    const panel = el("section", { class: "panel", "data-testid": "search" }, el("header", { class: "panel__head" }, el("h2", { class: "panel__title" }, "Comment ce plan a été trouvé")));
    const inner = el("div", { class: "panel__body ds-stack" });
    if (b) {
        inner.append(el("p", {}, fig(id, reco, "/bundle/search/evaluated"), " plans simulés sur ", fig(id, reco, "/bundle/search/enumerated"), " possibles ; recherche ", fig(id, reco, "/bundle/search/complete", (v) => (v ? "complète dans ce périmètre" : "incomplète : meilleur parmi les plans simulés, sans optimum revendiqué")), "."));
        const rejected = Object.entries(b.search.rejected);
        if (rejected.length)
            inner.append(details(`Options écartées (${rejected.length})`, el("ul", { class: "facts" }, ...rejected.map(([k, v]) => rejection(k, v)))));
    }
    inner.append(details("Détail du calcul (moteur)", el("ul", { class: "facts ds-raw" }, ...[...reco.reasons, ...reco.uncertainties].map((t) => el("li", {}, el("code", {}, t))))));
    inner.append(el("p", { class: "ds-prov mute", "data-testid": "provenance" }, `Recommandation ${reco.recommendation_id} · moteur ${reco.engine_version} · objectif ${reco.objective_version} · état ${reco.snapshot_id}`
        + (b ? ` · backend ${b.backend.name} ${b.backend.version} (${b.backend.code_sha256.slice(0, 12)})` : "")
        + ` · ${reco.scientific_status} · validation clinique : non · G2 ${reco.g2} · doc ${id}`));
    panel.append(inner);
    $("how").replaceChildren(panel);
}
// ------------------------------------------------------------------ manual mode (secondary)
function hourOptions(selected) {
    const start = new Date(state.snapshot.as_of).getTime();
    const out = [];
    for (let h = 1; h < 24; h++) {
        const iso = new Date(start + h * 3600_000).toISOString().replace(".000Z", "+00:00");
        const o = el("option", { value: iso }, local(iso, true));
        if (selected && new Date(selected).getTime() === new Date(iso).getTime())
            o.setAttribute("selected", "");
        out.push(o);
    }
    return out;
}
function openManual(fromPlan) {
    const form = $("manual-form");
    form.hidden = false;
    $("open-manual").hidden = true;
    const stays = state.snapshot.stays;
    const coord = fromPlan?.plan.actions.find((a) => a.type === "coordinate_discharge");
    const x1Default = coord?.target ?? stays.find((s) => s.medical_authorization === "authorized")?.stay_id ?? stays[0].stay_id;
    const x2Default = stays.find((s) => s.planned_departure)?.stay_id ?? "";
    const stayOpt = (s, sel) => {
        const o = el("option", { value: s.stay_id }, `${s.stay_id} — ${AUTHORIZATION[s.medical_authorization] ?? s.medical_authorization}`);
        if (s.stay_id === sel)
            o.setAttribute("selected", "");
        return o;
    };
    const x2 = stays.find((s) => s.stay_id === x2Default);
    form.replaceChildren(el("fieldset", {}, el("legend", {}, "X1 · Sortie à une heure donnée"), el("div", { class: "ds-row" }, el("label", {}, "Patient", el("select", { name: "x1", class: "select" }, ...stays.map((s) => stayOpt(s, x1Default)))), el("label", {}, "Heure", el("select", { name: "x1_at", class: "select" }, ...hourOptions(coord?.window_start ?? null))), el("label", {}, "Statut", el("select", { name: "x1_basis", class: "select" }, el("option", { value: "validated_instruction" }, "consigne validée"), el("option", { value: "hypothesis_only" }, "hypothèse seulement"))))), el("fieldset", {}, el("legend", {}, "X2 · Présence prolongée"), el("div", { class: "ds-row" }, el("label", {}, "Patient", el("select", { name: "x2", class: "select" }, el("option", { value: "" }, "aucun"), ...stays.map((s) => stayOpt(s, x2Default)))), el("label", {}, "À partir de", el("select", { name: "x2_ref", class: "select" }, ...hourOptions(x2?.planned_departure ?? null))), el("label", {}, "Durée (heures)", el("input", { name: "x2_t", type: "number", min: "0", max: "12", value: "4", "data-testid": "x2-t" })))), el("fieldset", {}, el("legend", {}, "Renforts et échéance"), el("div", { class: "ds-row" }, ...state.snapshot.reinforcements.map((r) => el("label", {}, `${r.option_id} · ${r.skill} · ${provenance(r)} · ${CONFIRMATION[r.confirmation] ?? r.confirmation}`, el("select", { name: `r_${r.option_id}`, class: "select" }, el("option", { value: "free" }, "laisser HospitalOS choisir"), el("option", { value: "include" }, "imposer"), el("option", { value: "exclude" }, "exclure")))), el("label", {}, "Jusqu'à demain", el("input", { name: "deadline", type: "time", value: "20:00" }))), el("label", { class: "ds-check" }, el("input", { name: "complements", type: "checkbox", checked: "" }), " compléter avec d'autres actions compatibles")), el("div", { class: "proposal__actions" }, el("button", { class: "btn btn--primary", type: "submit", "data-testid": "run-manual" }, "Calculer la variante")));
    $("manual-title").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function runManual(ev) {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const locks = [{ kind: "discharge_at", stay_id: f.get("x1"), at: f.get("x1_at"), basis: f.get("x1_basis") }];
    if (f.get("x2"))
        locks.push({ kind: "extend_presence", stay_id: f.get("x2"), reference_time: f.get("x2_ref"), extension_hours: Number(f.get("x2_t")), basis: "validated_instruction" });
    for (const r of state.snapshot.reinforcements) {
        const v = f.get(`r_${r.option_id}`);
        if (v !== "free")
            locks.push({ kind: "reinforcement", option_id: r.option_id, include: v === "include" });
    }
    const payload = { unit: state.unit, locks: { locks, deadline: { day_offset: 1, local_time: `${f.get("deadline")}:00` }, search_complements: f.get("complements") === "on" } };
    const body = $("manual-body");
    try {
        const r = await api("/api/simulate", payload);
        state.manual = r.recommendation;
        state.manualId = r.doc_id;
        renderManual();
    }
    catch (error) {
        body.replaceChildren(el("p", { class: "ds-err", "data-testid": "manual-error" }, String(error)));
    }
}
function renderManual() {
    const { manual: reco, manualId: id } = state;
    const body = $("manual-body");
    const card = el("section", { class: "panel", "data-testid": "manual-card" });
    const inner = el("div", { class: "panel__body ds-stack" }, statusPill(reco));
    card.append(inner);
    body.replaceChildren(card);
    if (!reco.bundle) {
        inner.append(el("ul", { class: "facts ds-err", "data-testid": "manual-diagnostics" }, ...reco.diagnostics.map(diagnostic)));
        return;
    }
    const rows = [["Pratique habituelle", reco.baseline_plan_id], ["Vos choix seuls", reco.locked_plan_id], ["Vos choix + compléments", reco.primary_plan_id]];
    const table = el("table", { class: "table", "data-testid": "branches" }, el("caption", { class: "ds-caption" }, "Soins non couverts en minutes · attente de lit en patients·h · renfort en heures"), el("thead", {}, el("tr", {}, el("th", {}, "Variante"), el("th", { class: "r" }, "Non couvert"), el("th", { class: "r" }, "Attente"), el("th", { class: "r" }, "Renfort"))));
    const tb = el("tbody");
    for (const [label, pid] of rows) {
        const k = evalIndex(reco, pid);
        if (k < 0)
            continue;
        const m = `/bundle/evaluations/${k}/metrics`;
        tb.append(el("tr", {}, el("td", {}, label), el("td", { class: "r" }, fig(id, reco, `${m}/uncovered_care_minutes`)), el("td", { class: "r" }, fig(id, reco, `${m}/waiting_patient_hours`)), el("td", { class: "r" }, fig(id, reco, `${m}/reinforcement_hours`))));
    }
    table.append(tb);
    const i = evalIndex(reco, reco.primary_plan_id);
    inner.append(el("ol", { class: "ds-actions", "data-testid": "manual-actions" }, ...reco.bundle.evaluations[i].plan.actions.map(actionText)), el("div", { class: "table-wrap" }, table));
    if (reco.diagnostics.length)
        inner.append(el("ul", { class: "facts ds-err" }, ...reco.diagnostics.map(diagnostic)));
    if (reco.status === "HYPOTHETICAL_ONLY")
        inner.append(el("p", { class: "ds-warn" }, "Simulation d'une hypothèse : elle ne peut pas devenir un plan à appliquer."));
    const why = bullets(humanReasons(reco.reasons));
    if (why)
        inner.append(why);
    const cond = details("Conditions", conditions(reco.conditions));
    if (cond)
        inner.append(cond);
    reviewButtons(reco, inner);
}
// ------------------------------------------------------------------ boot
let request = 0;
async function loadAuto() {
    // Only the latest request renders: a reset answered after a unit change must not overwrite it.
    const token = ++request;
    $("auto-body").replaceChildren(el("div", { class: "skeleton", "aria-busy": "true", "aria-label": "Calcul du plan" }));
    const r = await api(`/api/auto?unit=${encodeURIComponent(state.unit)}`);
    if (token !== request)
        return;
    state.snapshot = r.snapshot;
    state.snapId = r.snapshot_doc_id;
    state.auto = r.recommendation;
    state.autoId = r.doc_id;
    $("asof").replaceChildren("situation au ", fig(state.snapId, state.snapshot, "/as_of", (v) => local(v, true)));
    renderAuto();
    const events = state.events.filter((e) => e.unit === state.unit);
    if (events.length) {
        const bar = el("div", { class: "demobar" }, el("span", { class: "demobar__tag" }, "Démonstration"), el("span", { class: "demobar__text" }, "Faire arriver une information :"));
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
    $("manual-form").hidden = true;
    $("open-manual").hidden = false;
    $("manual-body").replaceChildren();
}
async function boot() {
    const meta = await api("/api/units");
    state.events = meta.events;
    const select = $("unit");
    select.replaceChildren(...meta.units.map((u) => el("option", { value: u.id }, u.name)));
    select.addEventListener("change", () => { state.unit = select.value; void loadAuto(); });
    $("open-manual").addEventListener("click", () => openManual(state.auto?.bundle?.evaluations[evalIndex(state.auto, state.auto.primary_plan_id)]));
    $("manual-form").addEventListener("submit", (e) => void runManual(e));
    await loadAuto(); // automatic recommendation first, without any user input
}
void boot();
