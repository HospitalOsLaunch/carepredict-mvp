import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileCheck2, Upload } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import type { ImportResult } from "../api/types";
import { ErrorNote, PageHeader } from "../components/ui";

type Kind = "lits" | "sejours" | "demandes";

const STEPS: Array<{ kind: Kind; title: string; text: string; updatedLabel: string }> = [
  {
    kind: "lits",
    title: "Sites et lits",
    text: "Une ligne par site et par mention : lits installés, lits ouverts, chambres d'isolement, capacités techniques. Les sites absents sont créés.",
    updatedLabel: "mises à jour"
  },
  {
    kind: "sejours",
    title: "Séjours",
    text: "L'historique des séjours (24 mois au moins pour mesurer l'effet du pilote) et les patients présents, avec la date de sortie prévue si elle est connue.",
    updatedLabel: "mis à jour"
  },
  {
    kind: "demandes",
    title: "Demandes en attente",
    text: "Les demandes reçues qui n'ont pas encore de réponse. Une demande déjà présente (même source et même référence) n'est jamais modifiée.",
    updatedLabel: "déjà présentes, ignorées"
  }
];

export function ImportsPage() {
  return (
    <>
      <PageHeader
        title="Importer les données du groupe"
        lead="Dans cet ordre : les lits d'abord, puis les séjours, puis les demandes. Chaque fichier est vérifié en entier ; une seule ligne invalide et rien n'est importé."
      />
      <ol className="space-y-5">
        {STEPS.map((step, i) => (
          <li key={step.kind}>
            <ImportStep index={i + 1} {...step} />
          </li>
        ))}
      </ol>
      <p className="mt-8 max-w-3xl text-[14px] text-ink-soft">
        Seules des références patient pseudonymisées sont acceptées : une valeur qui ressemble à un numéro de sécurité
        sociale est refusée. Aucun nom, aucune adresse.
      </p>
    </>
  );
}

function ImportStep({
  index,
  kind,
  title,
  text,
  updatedLabel
}: {
  index: number;
  kind: Kind;
  title: string;
  text: string;
  updatedLabel: string;
}) {
  const queryClient = useQueryClient();
  const [csv, setCsv] = useState("");
  const [fileName, setFileName] = useState("");
  const [checked, setChecked] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) =>
      api<ImportResult>(`/imports/${kind}`, { method: "POST", json: { csv_text: csv, dry_run: dryRun } }),
    onSuccess: (result) => {
      if (result.dry_run && result.errors.length === 0) setChecked(csv);
      if (result.committed) {
        setChecked(null);
        void queryClient.invalidateQueries();
      }
    }
  });
  const result = run.data;

  async function downloadTemplate() {
    const body = await api<string>(`/imports/templates/${kind}`);
    const url = URL.createObjectURL(new Blob([body], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `modele_${kind}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="panel px-6 py-5" aria-labelledby={`imp-${kind}`}>
      <div className="flex flex-wrap items-start gap-4">
        <span className="num grid h-9 w-9 shrink-0 place-items-center rounded-full bg-sun font-bold" aria-hidden>
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <h2 id={`imp-${kind}`}>{title}</h2>
          <p className="mt-1 max-w-2xl text-ink-soft">{text}</p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button className="btn-quiet" onClick={() => void downloadTemplate()}>
              <Download className="h-4 w-4" aria-hidden /> Télécharger le modèle
            </button>
            <label className="btn-quiet cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-violet">
              <Upload className="h-4 w-4" aria-hidden /> Choisir un fichier CSV
              <input
                type="file"
                accept=".csv,text/csv"
                className="sr-only"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setFileName(file.name);
                  setCsv(await file.text());
                  setChecked(null);
                  run.reset();
                }}
              />
            </label>
            {fileName && <span className="text-[14px] text-ink-soft">{fileName}</span>}
          </div>
          <details className="mt-3">
            <summary className="cursor-pointer text-[14px] font-bold text-ink-soft">Ou coller le contenu</summary>
            <label className="sr-only" htmlFor={`csv-${kind}`}>
              Contenu CSV
            </label>
            <textarea
              id={`csv-${kind}`}
              className="input font-mono text-[13px]"
              rows={5}
              value={csv}
              onChange={(e) => {
                setCsv(e.target.value);
                setChecked(null);
              }}
            />
          </details>
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="btn-quiet" disabled={!csv.trim() || run.isPending} onClick={() => run.mutate(true)}>
              <FileCheck2 className="h-4 w-4" aria-hidden /> Vérifier le fichier
            </button>
            <button
              className="btn-primary"
              disabled={checked !== csv || !csv.trim() || run.isPending}
              onClick={() => run.mutate(false)}
              title={checked !== csv ? "Vérifiez le fichier avant de l'importer" : undefined}
            >
              Importer
            </button>
          </div>
          {run.error && (
            <div className="mt-3">
              <ErrorNote error={run.error} />
            </div>
          )}
          {result && (
            <div className="mt-4" role="status">
              {result.errors.length > 0 ? (
                <div className="rounded-xl bg-coral-soft px-4 py-3">
                  <p className="font-bold text-coral-dark">
                    {result.errors.length} erreur{result.errors.length > 1 ? "s" : ""} : rien n'a été importé.
                  </p>
                  <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto text-[14px]">
                    {result.errors.map((e, i) => (
                      <li key={i}>
                        Ligne {e.line}
                        {e.column ? `, colonne « ${e.column} »` : ""} : {e.message}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className={`rounded-xl px-4 py-3 ${result.committed ? "bg-lagoon-soft text-lagoon-dark" : "bg-sky"}`}>
                  {result.committed ? "Importé : " : "Fichier valide : "}
                  {result.rows} lignes, {result.created} créé{result.created > 1 ? "s" : ""}, {result.updated} {updatedLabel}.
                  {!result.committed && " Vous pouvez l'importer."}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
