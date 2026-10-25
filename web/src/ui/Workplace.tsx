import { useState } from "react";
import type { Workspace } from "../data/useVirtualHospitals";
import type { OperationsWorkspace } from "../data/useOperations";
import type { PlacementPatient, WorkTask } from "../api/operations";
import { displayId } from "./common";
const when = (at: string) =>
  new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Europe/Paris",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(at));
const names: Record<string, string> = {
  geriatrie: "Gériatrie",
  medecine: "Médecine polyvalente",
  pneumologie: "Pneumologie",
  chirurgie: "Chirurgie",
};
const kinds: Record<string, string> = {
  place: "Placement",
  documents: "Documents de sortie",
  transport: "Transport",
  downstream: "Accord d’aval",
  cleaning: "Nettoyage",
  capacity: "Capacité du poste",
  close_bed: "Fermeture de lit",
  reopen_bed: "Réouverture de lit",
  protect: "Lit protégé",
  release_hold: "Protection levée",
  plan_decision: "Proposition",
  accept: "Acceptation",
  reject: "Refus",
  cancel: "Annulation",
  remind: "Relance",
  assign: "Transmission",
};
const statuses: Record<string, string> = {
  requested: "Accord attendu",
  in_progress: "Pris en charge · résultat attendu",
  completed: "Résultat observé",
  failed: "Échec à traiter",
  rejected: "Refusé par le destinataire",
  cancelled: "Annulé",
};
const closed = (status: string) =>
  ["completed", "failed", "rejected", "cancelled"].includes(status);
function PatientPlacement({
  patient: p,
  ops,
}: {
  patient: PlacementPatient;
  ops: OperationsWorkspace;
}) {
  const [choice, setChoice] = useState("");
  const options = p.options.filter((o) => o.eligible);
  const selected =
    options.find((o) => `${o.unit_id}|${o.bed_id}` === choice) ?? options[0];
  const pending = ops.data?.tasks.some(
    (t) => t.kind === "place" && t.patient_id === p.id && !closed(t.status),
  );
  return (
    <article className="work-card">
      <div className="work-row">
        <strong title={p.id}>{displayId(p.id)}</strong>
        <span>
          {names[p.unit_id]} · attente depuis {when(p.waiting_since)}
        </span>
      </div>
      <p>
        {p.programmed ? "Admission programmée" : "Demande d’hospitalisation"}
        {p.oxygen ? " · Oxygène requis" : ""}
        {p.isolation ? " · Isolement requis" : ""}
      </p>
      {pending ? (
        <p>
          Une demande de placement est déjà ouverte. Suivez son accord dans la
          relève.
        </p>
      ) : (
        <div className="work-form">
          <label>
            Lit compatible
            <select
              aria-label={`Lit compatible pour ${p.id}`}
              value={selected ? `${selected.unit_id}|${selected.bed_id}` : ""}
              onChange={(e) => setChoice(e.target.value)}
            >
              {!options.length ? (
                <option value="">Aucun lit compatible disponible</option>
              ) : (
                options.map((o) => (
                  <option key={o.bed_id} value={`${o.unit_id}|${o.bed_id}`}>
                    {names[o.unit_id]} · {displayId(o.bed_id)}
                  </option>
                ))
              )}
            </select>
          </label>
          <button
            className="btn btn--primary"
            disabled={!selected || ops.busy || !!ops.error || !!ops.retry}
            onClick={() =>
              selected &&
              ops.submit({
                kind: "place",
                unit_id: p.unit_id,
                target_unit: selected.unit_id,
                bed_id: selected.bed_id,
                patient_id: p.id,
              })
            }
          >
            Demander l’accord de l’unité
          </button>
        </div>
      )}
      <details>
        <summary>Pourquoi les autres lits sont-ils exclus ?</summary>
        <ul className="work-exclusions">
          {p.options
            .filter((o) => !o.eligible)
            .map((o) => (
              <li key={o.bed_id}>
                {names[o.unit_id]} · {displayId(o.bed_id)} :{" "}
                {o.reasons.join(" ; ")}
              </li>
            ))}
        </ul>
      </details>
    </article>
  );
}
function Task({ task: t, ops }: { task: WorkTask; ops: OperationsWorkspace }) {
  const [reason, setReason] = useState(""),
    [owner, setOwner] = useState(t.owner_id);
  const name = (id: string) =>
    ops.data?.staff.find((p) => p.id === id)?.name ?? id;
  const disabled = ops.busy || !!ops.error || !!ops.retry;
  return (
    <article className={`work-card${t.overdue ? " work-card--alert" : ""}`}>
      <div className="work-row">
        <strong>
          {kinds[t.kind]} · {displayId(t.patient_id ?? t.bed_id ?? "")}
        </strong>
        <span>
          {statuses[t.status]}
          {t.overdue ? " · Échéance dépassée" : ""}
        </span>
      </div>
      <p>
        {names[t.unit_id]}
        {t.target_unit
          ? ` → ${names[t.target_unit]} · ${displayId(t.bed_id ?? "")}`
          : ""}
      </p>
      <p>
        Responsable : {name(t.owner_id)}
        <br />
        Demandé par {name(t.requested_by)} · {when(t.created_at)}
        <br />
        Échéance de suivi : {when(t.due_at)}
      </p>
      {!closed(t.status) ? (
        <>
          <div className="work-form">
            {t.status === "requested" && ops.actorId === t.owner_id ? (
              <button
                className="btn btn--primary"
                disabled={disabled}
                onClick={() =>
                  ops.submit({
                    kind: "accept",
                    unit_id: t.unit_id,
                    task_id: t.id,
                  })
                }
              >
                Accepter la prise en charge
              </button>
            ) : null}
            <label>
              Motif / transmission
              <input
                aria-label={`Motif pour ${t.id}`}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={300}
              />
            </label>
            <button
              className="btn"
              disabled={disabled || !reason.trim()}
              onClick={() =>
                ops.submit({
                  kind: "remind",
                  unit_id: t.unit_id,
                  task_id: t.id,
                  reason,
                })
              }
            >
              Relancer
            </button>
            {t.status === "requested" ? (
              <button
                className="btn"
                disabled={disabled || !reason.trim()}
                onClick={() =>
                  ops.submit({
                    kind: ops.actorId === t.owner_id ? "reject" : "cancel",
                    unit_id: t.unit_id,
                    task_id: t.id,
                    reason,
                  })
                }
              >
                {ops.actorId === t.owner_id
                  ? "Refuser avec motif"
                  : "Annuler la demande"}
              </button>
            ) : null}
          </div>
          <details>
            <summary>Transmettre la responsabilité</summary>
            <div className="work-form">
              <label>
                Nouveau responsable
                <select
                  value={owner}
                  onChange={(e) => setOwner(e.target.value)}
                >
                  {ops.data?.staff
                    .filter((s) =>
                      t.kind === "place"
                        ? s.id === `cadre-${t.target_unit}`
                        : [`service-${t.kind}`, `cadre-${t.unit_id}`].includes(
                            s.id,
                          ),
                    )
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                </select>
              </label>
              <button
                className="btn"
                disabled={disabled || !reason.trim() || owner === t.owner_id}
                onClick={() =>
                  ops.submit({
                    kind: "assign",
                    unit_id: t.unit_id,
                    task_id: t.id,
                    owner_id: owner,
                    reason,
                  })
                }
              >
                Transmettre avec le motif
              </button>
            </div>
          </details>
        </>
      ) : null}
      <details>
        <summary>
          Historique de la demande · {t.events.length} événements
        </summary>
        <ol>
          {t.events.map((e, i) => (
            <li key={i}>
              {when(e.at)} · {name(e.actor)} · {statuses[e.status] ?? e.status}
              {e.note ? ` — ${e.note}` : ""}
            </li>
          ))}
        </ol>
      </details>
    </article>
  );
}
export function WorkplacePanel({
  workspace: w,
  initialTab = "patients",
}: {
  workspace: Workspace;
  initialTab?: string;
}) {
  const ops = w.operations;
  const [tab, setTab] = useState(initialTab),
    [search, setSearch] = useState(""),
    [showClosed, setShowClosed] = useState(false);
  if (!w.store.unitId.startsWith("H1/")) return null;
  const data = ops.data,
    unitId = w.store.unitId.split("/")[1]!;
  return (
    <section className="workplace" aria-labelledby="workplace-title">
      <div className="work-row">
        <div>
          <p className="eyebrow">Hôpital Saint-Clair</p>
          <h2 id="workplace-title">Travail du poste</h2>
        </div>
        <label className="work-identity">
          Identité de démonstration
          <select
            aria-label="Identité de démonstration"
            value={ops.actorId}
            disabled={ops.busy}
            onChange={(e) => ops.setActor(e.target.value)}
          >
            {data?.staff.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <small>Profils fictifs · aucune authentification hospitalière</small>
        </label>
      </div>
      {ops.error ? (
        <p className="work-error" role="alert">
          {ops.error}{" "}
          <button className="btn" onClick={ops.refresh}>
            Actualiser le poste
          </button>
          {ops.retry ? (
            <button className="btn" onClick={ops.retry} disabled={ops.busy}>
              Réessayer la même demande
            </button>
          ) : null}
        </p>
      ) : null}
      {!data ? (
        <p>Chargement du poste…</p>
      ) : (
        <>
          <div
            className="work-tabs"
            role="tablist"
            aria-label="Travail du poste"
          >
            {[
              ["patients", "À placer"],
              ["discharges", "Sorties"],
              ["tasks", "Relève & suivi"],
              ["admissions", "Admissions prévues"],
              ["capacity", "Capacité du poste"],
            ].map(([id, label]) => (
              <button
                key={id}
                role="tab"
                aria-selected={tab === id}
                aria-controls="work-content"
                id={`work-tab-${id}`}
                onClick={() => setTab(id!)}
              >
                {label}
                {id === "tasks"
                  ? ` (${data.tasks.filter((t) => !closed(t.status)).length})`
                  : ""}
              </button>
            ))}
          </div>
          <div
            id="work-content"
            role="tabpanel"
            aria-labelledby={`work-tab-${tab}`}
          >
            {tab === "patients" ? (
              <>
                <p>
                  File hospitalière · placement soumis à l’accord du cadre
                  receveur. Compatibilités déclarées dans cet hôpital fictif.
                </p>
                <label className="work-search">
                  Rechercher un patient
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Identifiant patient ou unité"
                  />
                </label>
                {data.patients
                  .filter((p) =>
                    `${p.id} ${names[p.unit_id]}`
                      .toLowerCase()
                      .includes(search.toLowerCase()),
                  )
                  .map((p) => (
                    <PatientPlacement key={p.id} patient={p} ops={ops} />
                  ))}
                {!data.patients.length ? (
                  <p>Aucun patient en attente observé dans l’hôpital.</p>
                ) : null}
              </>
            ) : null}
            {tab === "discharges" ? (
              <>
                <p>
                  {names[unitId]} · seuls les patients dont la préparation de
                  sortie a commencé sont affichés.
                </p>
                {data.discharges
                  .filter((p) => p.unit_id === unitId)
                  .map((p) => (
                    <article className="work-card" key={p.id}>
                      <strong>
                        {displayId(p.id)} ·{" "}
                        {p.phase === "authorized"
                          ? "Sortie autorisée"
                          : "Autorisation de sortie attendue"}
                      </strong>
                      <p>Dernière observation : {when(p.observed_at)}</p>
                      <div className="work-form">
                        {(
                          [
                            ["documents", true, p.documents_ready, "Documents"],
                            [
                              "transport",
                              p.transport_required,
                              p.transport_ready,
                              "Transport",
                            ],
                            [
                              "downstream",
                              p.downstream_required,
                              p.downstream_ready,
                              "Aval",
                            ],
                          ] as const
                        ).map(([kind, required, ready, label]) => (
                          <div key={kind}>
                            <p>
                              {label} :{" "}
                              {!required
                                ? "non requis"
                                : ready
                                  ? "confirmé"
                                  : "à organiser"}
                            </p>
                            {required && !ready ? (
                              <button
                                className="btn"
                                disabled={
                                  ops.busy ||
                                  !!ops.error ||
                                  !!ops.retry ||
                                  data.tasks.some(
                                    (t) =>
                                      t.patient_id === p.id &&
                                      t.kind === kind &&
                                      !closed(t.status),
                                  )
                                }
                                onClick={() =>
                                  ops.submit({
                                    kind,
                                    unit_id: unitId,
                                    patient_id: p.id,
                                  })
                                }
                              >
                                Confier : {label}
                              </button>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                {!data.discharges.some((p) => p.unit_id === unitId) ? (
                  <p>Aucune sortie en préparation dans cette unité.</p>
                ) : null}
              </>
            ) : null}
            {tab === "tasks" ? (
              <>
                <label className="work-check">
                  <input
                    type="checkbox"
                    checked={showClosed}
                    onChange={(e) => setShowClosed(e.target.checked)}
                  />
                  Afficher aussi les demandes terminées
                </label>
                <p>
                  Les équipes virtuelles de logistique répondent en
                  arrière-plan. Les placements attendent un accord explicite du
                  cadre receveur. Une échéance de suivi n’est pas une garantie
                  d’exécution.
                </p>
                {data.tasks
                  .filter((t) => showClosed || !closed(t.status))
                  .map((t) => (
                    <Task key={t.id} task={t} ops={ops} />
                  ))}
                {!data.tasks.length ? <p>Aucune demande enregistrée.</p> : null}
                <details>
                  <summary>Journal des décisions du poste</summary>
                  <ol>
                    {[...data.events].reverse().map((e) => (
                      <li key={e.id}>
                        {when(e.at)} ·{" "}
                        {data.staff.find((s) => s.id === e.actor_id)?.name} ·{" "}
                        {names[e.unit_id]} · {kinds[e.kind] ?? e.kind}
                        {e.capacity !== null ? ` : ${e.capacity} lits` : ""}
                        {e.reason ? ` — ${e.reason}` : ""}
                      </li>
                    ))}
                  </ol>
                </details>
              </>
            ) : null}
            {tab === "admissions" ? (
              <Admissions workspace={w} unitId={unitId} />
            ) : null}
            {tab === "capacity" ? (
              <Capacity workspace={w} key={unitId} unitId={unitId} />
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}
function Admissions({
  workspace: w,
  unitId,
}: {
  workspace: Workspace;
  unitId: string;
}) {
  const ops = w.operations,
    data = ops.data!;
  const [choices, setChoices] = useState<Record<string, string>>({}),
    [reason, setReason] = useState("");
  const beds = w.view?.snapshot.state.beds ?? [];
  const forecast = data.forecasts.find((f) => f.unit_id === unitId);
  return (
    <>
      <p>
        {names[unitId]} · admissions déclarées pour les prochaines 48 heures.
        Une protection immobilise dès maintenant un lit propre ; elle peut être
        levée avec un motif.
      </p>
      <div className="work-shift">
        {forecast?.forecasts.map((f) => (
          <article key={f.horizon_hours}>
            <strong>
              {f.horizon_hours === 8 ? "Prochain poste" : "Demain"} ·{" "}
              {when(f.at)}
            </strong>
            <p>
              {f.occupied} lits occupés prévus · plage {f.lower}–{f.upper}
            </p>
            <p>Capacité déclarée : {forecast.capacity} lits</p>
            {f.upper > forecast.capacity ? (
              <p className="work-risk">
                Risque de tension : examiner les entrées attendues, les sorties
                à préparer et la capacité du poste.
              </p>
            ) : null}
            <small>
              {f.interval_label}. Issue de l’historique, sans simuler les
              changements récents de capacité.
            </small>
          </article>
        ))}
      </div>
      {forecast ? (
        <p>
          <b>{forecast.planned_next_shift}</b> entrées programmées dans les 8 h
          · <b>{forecast.discharges_to_prepare}</b> sorties à préparer, sans
          garantie de départ.
        </p>
      ) : null}
      <label className="work-search">
        Motif de protection ou de levée
        <input
          value={reason}
          maxLength={300}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      {data.admissions
        .filter((a) => a.unit_id === unitId)
        .map((a) => {
          const eligible = beds.filter(
            (b) =>
              b.state === "clean" &&
              !b.reserved_for &&
              (!a.oxygen || b.capabilities.includes("oxygen")),
          );
          const choice = choices[a.id] ?? eligible[0]?.id ?? "";
          return (
            <article className="work-card" key={a.id}>
              <strong>
                {when(a.at)} · {displayId(a.id)}
              </strong>
              <p>
                {a.oxygen ? "Oxygène requis" : "Admission programmée"}
                {a.protected_bed
                  ? ` · Lit ${displayId(a.protected_bed)} protégé`
                  : " · Lit non engagé"}
              </p>
              <div className="work-form">
                {a.protected_bed ? (
                  <button
                    className="btn"
                    disabled={
                      ops.busy || !!ops.error || !!ops.retry || !reason.trim()
                    }
                    onClick={() =>
                      ops.submit({
                        kind: "release_hold",
                        unit_id: unitId,
                        bed_id: a.protected_bed!,
                        reason,
                      })
                    }
                  >
                    Lever la protection
                  </button>
                ) : (
                  <>
                    <label>
                      Lit à protéger
                      <select
                        aria-label={`Lit pour ${a.id}`}
                        value={choice}
                        onChange={(e) =>
                          setChoices({ ...choices, [a.id]: e.target.value })
                        }
                      >
                        {!eligible.length ? (
                          <option value="">Aucun lit propre disponible</option>
                        ) : (
                          eligible.map((b) => (
                            <option key={b.id} value={b.id}>
                              {displayId(b.id)}
                            </option>
                          ))
                        )}
                      </select>
                    </label>
                    <button
                      className="btn"
                      disabled={
                        ops.busy ||
                        !!ops.error ||
                        !!ops.retry ||
                        !reason.trim() ||
                        !choice
                      }
                      onClick={() =>
                        ops.submit({
                          kind: "protect",
                          unit_id: unitId,
                          patient_id: a.id,
                          bed_id: choice,
                          reason,
                        })
                      }
                    >
                      Protéger ce lit
                    </button>
                  </>
                )}
              </div>
            </article>
          );
        })}
    </>
  );
}
function Capacity({
  workspace: w,
  unitId,
}: {
  workspace: Workspace;
  unitId: string;
}) {
  const ops = w.operations,
    data = ops.data!,
    constraint = data.constraints.find((c) => c.unit_id === unitId)!;
  const [capacity, setCapacity] = useState(constraint.capacity),
    [hours, setHours] = useState(8),
    [reason, setReason] = useState(""),
    [bed, setBed] = useState("");
  const mayEdit = ops.actorId === `cadre-${unitId}`;
  const until = new Date(
    new Date(data.now).getTime() + hours * 3600000,
  ).toISOString();
  const available =
    w.view?.snapshot.state.beds.filter(
      (b) => !b.occupant && !b.reserved_for && b.state !== "closed",
    ) ?? [];
  const selected =
    available.find((b) => b.id === bed)?.id ?? available[0]?.id ?? "";
  const disabled =
    !mayEdit || ops.busy || !!ops.error || !!ops.retry || !reason.trim();
  return (
    <>
      <p>
        {names[unitId]} · {constraint.capacity} lits dotés déclarés sur{" "}
        {constraint.physical_beds} lits physiques.
      </p>
      <p>
        {constraint.reason}
        {constraint.until ? ` · Jusqu’au ${when(constraint.until)}` : ""}
      </p>
      {!mayEdit ? (
        <p>
          La déclaration de capacité et les fermetures relèvent du cadre de
          cette unité. Choisissez son profil de démonstration pour ce parcours.
        </p>
      ) : null}
      <div className="work-form">
        <label>
          Capacité du poste
          <input
            type="number"
            min={0}
            max={constraint.physical_beds}
            value={capacity}
            onChange={(e) => setCapacity(Number(e.target.value))}
          />
        </label>
        <label>
          Durée
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            {[1, 2, 4, 8, 12, 24].map((h) => (
              <option key={h} value={h}>
                {h} heures
              </option>
            ))}
          </select>
        </label>
        <label>
          Motif
          <input
            value={reason}
            maxLength={300}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Absence, compétence indisponible…"
          />
        </label>
        <button
          className="btn btn--primary"
          disabled={
            disabled ||
            !Number.isInteger(capacity) ||
            capacity < 0 ||
            capacity > constraint.physical_beds
          }
          onClick={() =>
            ops.submit({
              kind: "capacity",
              unit_id: unitId,
              capacity,
              until,
              reason,
            })
          }
        >
          Déclarer la capacité
        </button>
      </div>
      <p>
        Jusqu’au {when(until)}. Les patients déjà installés restent en place ;
        les nouvelles admissions respectent la capacité déclarée.
      </p>
      <div className="work-form">
        <label>
          Fermer temporairement un lit
          <select value={selected} onChange={(e) => setBed(e.target.value)}>
            {available.map((b) => (
              <option key={b.id} value={b.id}>
                {displayId(b.id)}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn"
          disabled={disabled || !selected}
          onClick={() =>
            ops.submit({
              kind: "close_bed",
              unit_id: unitId,
              bed_id: selected,
              until,
              reason,
            })
          }
        >
          Fermer avec le motif
        </button>
      </div>
      {constraint.closed_beds.map((b) => (
        <article className="work-card" key={b.bed_id}>
          {displayId(b.bed_id)} · {b.reason} · jusqu’au {when(b.until)}{" "}
          <button
            className="btn"
            disabled={disabled}
            onClick={() =>
              ops.submit({
                kind: "reopen_bed",
                unit_id: unitId,
                bed_id: b.bed_id,
                reason,
              })
            }
          >
            Rouvrir avec le motif
          </button>
        </article>
      ))}
    </>
  );
}
