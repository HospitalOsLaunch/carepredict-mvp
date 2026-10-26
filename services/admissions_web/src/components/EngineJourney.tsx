import type { EngineStep } from "../api/types";
const money = (cost: number) => new Intl.NumberFormat("fr-FR", {
  style: "currency", currency: "USD", minimumFractionDigits: 4, maximumFractionDigits: 4,
}).format(cost);

const DECISIONS = {
  success: "succès",
  failure: "échec",
  skipped: "sauté",
  unverified: "non validé",
};

export function EngineJourney({ steps, cost }: { steps: EngineStep[]; cost: number }) {
  return (
    <div className="mt-2 text-[13px]" aria-label="Parcours des moteurs">
      {steps.length ? (
        <ol className="space-y-2">
          {steps.map((step, index) => (
            <li key={index} className="rounded-lg border border-line p-2">
              <p className="font-bold">
                {index > 0 && <span aria-hidden>→ </span>}
                {step.engine} — {DECISIONS[step.decision]}
                <span className="num ml-2 font-normal">{money(step.cost_usd)}</span>
              </p>
              <p className="text-ink-soft">{step.reason}</p>
            </li>
          ))}
        </ol>
      ) : <p className="text-ink-faint">Aucun moteur exécuté pour ce passage.</p>}
      <p className="num mt-2 text-ink-soft">Coût cumulé de la tâche : {money(cost)}</p>
    </div>
  );
}
