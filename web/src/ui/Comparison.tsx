import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { compareEpisodes, downloadComparison, type ComparisonConfig, type ComparisonResult } from "../api/comparison";

const number = (value: number) => value.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
const policies = {
  accept: "Recommandations acceptées",
  refuse: "Recommandations refusées, lecture coûteuse",
  disabled: "Recommandations désactivées, coût nul",
};

export function ComparisonPanel() {
  const [seed, setSeed] = useState("7");
  const [horizon, setHorizon] = useState(180);
  const [policy, setPolicy] = useState<ComparisonConfig["policy"]>("accept");
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);

  function clear() { setResult(null); setError(null); }

  async function run() {
    if (pending.current) return;
    pending.current = true;
    const token = ++generation.current;
    clear();
    setBusy(true);
    try {
      const next = await compareEpisodes({ seed: Number(seed), horizon_minutes: horizon, policy });
      if (token === generation.current) setResult(next);
    } catch (e) {
      if (token === generation.current) setError(e instanceof ApiError && e.detail === "comparison_environment_changed_restart_required"
        ? "Le code ou les dépendances ont changé. Arrêtez la démo puis relancez demo.py avant de comparer."
        : e instanceof ApiError && e.status === 429
        ? "Une comparaison est déjà en cours. Réessayez une fois son calcul terminé."
        : "La comparaison n'a pas abouti. Vérifiez la connexion au simulateur puis réessayez. Aucun résultat de remplacement n'est affiché.");
    } finally {
      if (token === generation.current) { pending.current = false; setBusy(false); }
    }
  }

  const saved = result?.waiting_patient_minutes_saved ?? 0;
  const rows: [string, number, number][] = result ? [
    ["Attente cumulée (minutes-patients)", result.a0.evaluation.waiting_patient_minutes, result.a1.evaluation.waiting_patient_minutes],
    ["Patients installés pendant l'épisode", result.a0.installed_during_episode, result.a1.installed_during_episode],
    ["Patients encore en attente à la fin", result.a0.evaluation.waiting_at_end, result.a1.evaluation.waiting_at_end],
    ["Patients hospitalisés à la fin", result.a0.evaluation.admitted_at_end, result.a1.evaluation.admitted_at_end],
    ["Départs pendant l'épisode", result.a0.evaluation.departed, result.a1.evaluation.departed],
    ["Sollicitations de coordination", result.a0.evaluation.coordination_tasks, result.a1.evaluation.coordination_tasks],
    ["Temps demandé par les sollicitations (s)", result.a0.solicitation_seconds_requested, result.a1.solicitation_seconds_requested],
  ] : [];
  return (
    <section className="simulation-panel comparison-panel" aria-label="Comparer sans et avec HospitalOS">
      <span className="demobar__tag">Comparaison sur simulateur</span>
      <h2>Sans / avec HospitalOS</h2>
      <p>Deux exécutions depuis le début : mêmes patients, ressources et aléas. A0 suit les règles métier ; A1 y ajoute une évaluation HospitalOS toutes les cinq minutes.</p>
      <p>Cette comparaison est indépendante de votre séance interactive. L'acceptation est une hypothèse de simulation.</p>
      <form onSubmit={(event) => { event.preventDefault(); void run(); }}>
        <fieldset disabled={busy} className="comparison-panel__settings">
          <legend className="visually-hidden">Paramètres de comparaison</legend>
          <label>Graine du scénario
            <input className="comparison-panel__seed" type="number" required min="0" max="2147483647" step="1"
              value={seed} onChange={(e) => { setSeed(e.target.value); clear(); }} />
          </label>
          <label>Durée simulée
            <select className="select" value={horizon} onChange={(e) => { setHorizon(Number(e.target.value)); clear(); }}>
              <option value={60}>1 heure</option><option value={120}>2 heures</option><option value={180}>3 heures</option>
            </select>
          </label>
          <label>Réponse aux recommandations en A1
            <select className="select" value={policy} onChange={(e) => { setPolicy(e.target.value as ComparisonConfig["policy"]); clear(); }}>
              {Object.entries(policies).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <button type="submit" className="btn btn--primary">{busy ? "Comparaison en cours…" : "Comparer"}</button>
        </fieldset>
      </form>
      {busy ? <p role="status">Les deux épisodes sont en cours de calcul. Le résultat sera mesuré après leur clôture.</p> : null}
      {error ? <p className="notice notice--error" role="alert">{error}</p> : null}
      {result ? <div aria-label="Résultats de comparaison">
        <div className="comparison-panel__outcome" role="status">
          <strong>{saved > 0 ? `${number(saved)} minutes-patients d'attente en moins` : saved < 0 ? `${number(-saved)} minutes-patients d'attente en plus` : "Aucune différence d'attente cumulée"}</strong>
          <p>Écart A0 − A1 : {number(saved)} minutes-patients. Les attentes encore en cours à la clôture sont incluses.</p>
        </div>
        <p>Graine {result.manifest.config.seed} · {result.manifest.config.horizon_minutes} minutes · {policies[result.manifest.config.policy]}.</p>
        <div className="comparison-panel__table">
          <table>
            <caption className="visually-hidden">Mesures finales des deux épisodes</caption>
            <thead><tr><th scope="col">Mesure</th><th scope="col">A0 · Référence métier</th><th scope="col">A1 · HospitalOS{policy === "disabled" ? " désactivé" : ""}</th></tr></thead>
            <tbody>{rows.map(([label, a0, a1]) => <tr key={label}><th scope="row">{label}</th><td>{number(a0)}</td><td>{number(a1)}</td></tr>)}</tbody>
          </table>
        </div>
        {policy === "disabled" ? <p>{result.physical_trajectories_identical ? "Contrôle de neutralité : trajectoires physiques identiques." : "Contrôle de neutralité en échec : les trajectoires diffèrent."}</p> : null}
        <p>Le temps demandé est de 30 secondes par sollicitation, y compris en cas de refus ; il ne représente pas toute la charge de travail.</p>
        <p>Un seul scénario fictif : ce résultat ne mesure pas un bénéfice hospitalier et ne fournit pas d'intervalle d'incertitude.</p>
        <button className="btn" onClick={() => downloadComparison(result)}>Exporter la comparaison (JSON)</button>
        <details>
          <summary>Décisions et reproductibilité</summary>
          <p>{result.a1.decisions.length} évaluations · {result.a1.commands.filter(c => c.status === "executed").length} actions exécutées · {result.a1.commands.filter(c => c.status === "refused").length} refus · {result.a1.commands.filter(c => c.status === "failed").length} échecs.</p>
          <p>L'export contient les paramètres, les aléas indexés, les décisions, les journaux des deux épisodes, les résultats et les empreintes du code.</p>
          <p>Identifiant : <code>{result.comparison_id.slice(0, 12)}</code></p>
        </details>
      </div> : null}
    </section>
  );
}
