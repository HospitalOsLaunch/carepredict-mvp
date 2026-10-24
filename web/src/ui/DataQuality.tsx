import type { ResourceBudget, ShadowSummary, SourceReceipt } from "../api/types";
import { entityLabel, explain } from "../domain/labels";
import { type Assessment, age, duration, freshnessIndex, longClock, minutesBetween } from "../domain/view";
import { Fresh } from "./common";
import { Back, Ban, Check } from "./icons";

const RESOURCE_NAME: Record<string, string> = {
  staffed: "Lits armés disponibles",
  cleaning: "Équipes de bionettoyage",
  transport: "Transport sanitaire",
  downstream: "Places d'aval",
};

export function DataQuality({
  a,
  quality,
  summary,
}: {
  a: Assessment;
  quality: SourceReceipt | null;
  summary: ShadowSummary | null;
}) {
  const fresh = [...freshnessIndex(a).values()].sort((x, y) => (y.minutes || 1e9) - (x.minutes || 1e9));
  const stale = fresh.filter((f) => f.stale).length;
  const codes = [...a.state.issues, ...a.gateReasons.filter((c) => !a.state.issues.includes(c))];
  return (
    <>
      <header className="page-head">
        <a className="back" href="#/">
          <Back size={14} /> Unité
        </a>
        <h1>Qualité des données</h1>
        <p>
          Une proposition ne vaut que ce que valent les informations reçues. Ici : ce qui est arrivé, quand,
          et ce qui empêche une évaluation.
        </p>
      </header>
      <div className="grid-2">
        <div className="stack">
          <section className="panel" aria-labelledby="state-title">
            <header className="panel__head">
              <h2 className="panel__title" id="state-title">
                État reconstruit
              </h2>
              {codes.length ? (
                <span className="pill pill--warn">{codes.length} contrôles en échec</span>
              ) : (
                <span className="pill pill--ok">
                  <Check size={12} /> Évaluable
                </span>
              )}
            </header>
            <div className="kv-strip">
              <div className="kv">
                <span>Instant</span>
                <b className="num">{longClock(a.state.at).replace(/^\w+ /, "")}</b>
              </div>
              <div className="kv">
                <span>Informations suivies</span>
                <b className="num">{fresh.length}</b>
              </div>
              <div className="kv">
                <span>Périmées</span>
                <b className="num">{stale}</b>
              </div>
              <div className="kv">
                <span>Budget de fraîcheur</span>
                <b className="num">{duration(a.factBudgetMinutes)}</b>
              </div>
            </div>
            {codes.length ? (
              <div className="panel__body" style={{ paddingTop: "var(--s4)" }}>
                <ul className="issue-list">
                  {codes.slice(0, 12).map((c) => (
                    <li key={c} title={c}>
                      {explain(c)}
                    </li>
                  ))}
                  {codes.length > 12 ? <li className="mute">et {codes.length - 12} autres</li> : null}
                </ul>
              </div>
            ) : null}
          </section>

          <section className="panel" aria-labelledby="ages-title">
            <header className="panel__head">
              <h2 className="panel__title" id="ages-title">
                Informations les plus anciennes
              </h2>
              <span className="panel__aside">l'encre pâlit avec l'âge</span>
            </header>
            <div
              className="table-wrap"
              tabIndex={0}
              role="group"
              aria-label="Tableau, défilement horizontal possible"
            >
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Information</th>
                    <th scope="col">Source</th>
                    <th scope="col" className="r">
                      Reçue
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {fresh.slice(0, 10).map((f) => (
                    <tr key={f.key}>
                      <td>{entityLabel(f.key)}</td>
                      <td className="mute" translate="no">
                        {f.source || "—"}
                      </td>
                      <td className="r">
                        <Fresh f={f} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {a.resources ? <Resources resources={a.resources} at={a.state.at} /> : null}
        </div>

        <div className="stack">
          {quality ? <Source receipt={quality} /> : null}
          {a.receivedAtBySource ? (
            <section className="panel" aria-labelledby="recv-title">
              <header className="panel__head">
                <h2 className="panel__title" id="recv-title">
                  Dernières réceptions
                </h2>
              </header>
              <div className="panel__body">
                <dl className="dl">
                  {Object.entries(a.receivedAtBySource).map(([source, at]) => (
                    <div key={source} style={{ display: "contents" }}>
                      <dt translate="no">{source}</dt>
                      <dd>{age(minutesBetween(at, a.state.at))}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </section>
          ) : null}
          {summary ? <Journal summary={summary} /> : null}
          <Limits />
        </div>
      </div>
    </>
  );
}

function Resources({ resources, at }: { resources: ResourceBudget[]; at: string }) {
  return (
    <section className="panel" aria-labelledby="res-title">
      <header className="panel__head">
        <h2 className="panel__title" id="res-title">
          Ressources confirmées
        </h2>
        <span className="panel__aside">un signal de vie ne vaut pas confirmation</span>
      </header>
      <div
        className="table-wrap"
        tabIndex={0}
        role="group"
        aria-label="Tableau, défilement horizontal possible"
      >
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Ressource</th>
              <th scope="col" className="r">
                Observé
              </th>
              <th scope="col" className="r">
                Retenu
              </th>
              <th scope="col" className="r">
                Restant
              </th>
              <th scope="col" className="r">
                Confirmé
              </th>
            </tr>
          </thead>
          <tbody>
            {resources.map((r) => {
              const [kind, target] = r.key.split(":");
              const obs = r.observations[0];
              return (
                <tr key={r.key}>
                  <td>
                    {RESOURCE_NAME[kind ?? ""] ?? kind}
                    <div className="mute" translate="no">
                      {target}
                    </div>
                    {r.issues.map((i) => (
                      <div key={i} className="fresh--stale">
                        {explain(i)}
                      </div>
                    ))}
                  </td>
                  <td className="r num">{r.observed_available ?? "inconnu"}</td>
                  <td className="r num">{r.held}</td>
                  <td className="r num">{r.remaining ?? "inconnu"}</td>
                  <td className="r">{obs ? age(minutesBetween(obs.observed_at, at)) : "jamais"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const STATUS: Record<string, [string, string]> = {
  REJECTED: ["Rejeté : source bloquée", "pill--bad"],
  OBSERVATION_ONLY: ["Qualifié, observation seule", "pill--ok"],
  SHADOW_EVALUATED: ["Qualifié, épisode enregistré", "pill--ok"],
};

function Source({ receipt }: { receipt: SourceReceipt }) {
  const r = receipt.report;
  const [label, tone] = STATUS[r.status] ?? [r.status, ""];
  const missing = Object.entries(r.missing_values_by_field);
  const seconds = (s: number | null) => (s == null ? "—" : s < 60 ? `${Math.round(s)} s` : duration(s / 60));
  return (
    <section className="panel" aria-labelledby="src-title">
      <header className="panel__head">
        <h2 className="panel__title" id="src-title">
          Dernier export de la source
        </h2>
        <span className={`pill ${tone}`}>{label}</span>
      </header>
      <div className="kv-strip">
        <div className="kv">
          <span>Entités reçues</span>
          <b className="num">
            {r.delivered_entities ?? "—"}/{r.expected_entities ?? "—"}
          </b>
        </div>
        <div className="kv">
          <span>Info la plus ancienne</span>
          <b className="num">{seconds(r.max_fact_age_seconds)}</b>
        </div>
        <div className="kv">
          <span>Retard source</span>
          <b className="num">{seconds(r.max_source_delay_seconds)}</b>
        </div>
        <div className="kv">
          <span>Confirmations</span>
          <b className="num">{seconds(r.max_resource_age_seconds)}</b>
        </div>
      </div>
      <div className="panel__body" style={{ paddingTop: "var(--s4)" }}>
        <p className="note" style={{ marginBottom: "var(--s3)" }}>
          Reçu le {longClock(r.receipt_at)}. Le contrôle ne lit que des identifiants déjà pseudonymisés en
          amont et ne renvoie aucune valeur source.
        </p>
        {r.issues.length ? (
          <ul className="gates" style={{ marginBottom: "var(--s3)" }}>
            {r.issues.map((i, n) => (
              <li key={n}>
                {i.code.replace(/_/g, " ")}
                {i.kind ? ` (${i.kind}${i.field ? `.${i.field}` : ""})` : ""} × {i.count}
              </li>
            ))}
          </ul>
        ) : null}
        {missing.length ? (
          <div
            className="table-wrap"
            tabIndex={0}
            role="group"
            aria-label="Tableau, défilement horizontal possible"
          >
            <table className="table">
              <caption className="visually-hidden">Valeurs non renseignées par champ</caption>
              <thead>
                <tr>
                  <th scope="col">Champ non renseigné (inconnu, pas zéro)</th>
                  <th scope="col" className="r">
                    Lignes
                  </th>
                </tr>
              </thead>
              <tbody>
                {missing.map(([field, n]) => (
                  <tr key={field}>
                    <td translate="no">{field.replace(".fact.", " · ")}</td>
                    <td className="r num">{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Journal({ summary }: { summary: ShadowSummary }) {
  const top = Object.entries(summary.gate_reason_counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
  return (
    <section className="panel" aria-labelledby="journal-title">
      <header className="panel__head">
        <h2 className="panel__title" id="journal-title">
          Journal d'observation
        </h2>
        <span className="pill">aucune commande émise</span>
      </header>
      <div className="kv-strip">
        <div className="kv">
          <span>Épisodes</span>
          <b className="num">{summary.episodes}</b>
        </div>
        <div className="kv">
          <span>Bloqués par un contrôle</span>
          <b className="num">{summary.blocked_episodes}</b>
        </div>
        <div className="kv">
          <span>Propositions</span>
          <b className="num">{summary.planner_decisions.recommend ?? 0}</b>
        </div>
      </div>
      {top.length ? (
        <div className="panel__body" style={{ paddingTop: "var(--s4)" }}>
          <p className="note" style={{ marginBottom: "var(--s2)" }}>
            Motifs de blocage les plus fréquents
          </p>
          <ul className="issue-list">
            {top.map(([code, n]) => (
              <li key={code} title={code}>
                {explain(code)} ({n})
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function Limits() {
  const items: Array<[boolean, string]> = [
    [true, "Reconstruit l'état de l'unité à partir d'informations datées et sourcées."],
    [true, "Compare des actions sur les mêmes scénarios simulés, et s'abstient si l'état n'est pas fiable."],
    [false, "N'envoie aucune demande, réservation ni commande au système d'information."],
    [false, "Ne décide pas d'une sortie : l'autorisation médicale reste saisie par un médecin."],
    [false, "N'infère pas les priorités : elles sont saisies par un soignant."],
    [false, "N'a pas démontré de gain réel : le protocole de décision v2 conclut « non concluant »."],
  ];
  return (
    <section className="panel" aria-labelledby="limits-title">
      <header className="panel__head">
        <h2 className="panel__title" id="limits-title">
          Ce que fait ce prototype, et ce qu'il ne fait pas
        </h2>
      </header>
      <ul className="panel__body limits">
        {items.map(([does, text]) => (
          <li key={text}>
            {does ? <Check size={14} /> : <Ban size={14} />}
            {text}
          </li>
        ))}
      </ul>
    </section>
  );
}
