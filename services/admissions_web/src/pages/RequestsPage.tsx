import { Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { AdmissionRequest } from "../api/types";
import { useAuth } from "../auth";
import { RequestDetailPanel } from "../components/RequestDetail";
import { NewRequestModal } from "../components/RequestForms";
import { Empty, ErrorNote, Meter, PageHeader, Spinner, StatusChip } from "../components/ui";
import { fmtHours, fmtShort, plural } from "../lib/format";
import { label, useSites, useVocabulary } from "../lib/queries";
import { useRequests, type Scope } from "../lib/requests";

const SCOPES: Array<{ value: Scope; label: string }> = [
  { value: "a_traiter", label: "À traiter" },
  { value: "ouvertes", label: "En cours" },
  { value: "fermees", label: "Clôturées" }
];

export function RequestsPage() {
  const { id } = useParams();
  const selected = id ? Number(id) : null;
  const navigate = useNavigate();
  const { canWrite } = useAuth();
  const [scope, setScope] = useState<Scope>("a_traiter");
  const [siteId, setSiteId] = useState("");
  const [mention, setMention] = useState("");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const vocab = useVocabulary();
  const sites = useSites();
  const list = useRequests({ scope, site_id: siteId, mention, q: q.trim() || undefined });
  const pending = useRequests({ scope: "a_traiter" });

  const headline = useMemo(() => {
    const rows = pending.data ?? [];
    if (!pending.data) return { title: "Demandes d'admission", lead: undefined };
    if (rows.length === 0) {
      return {
        title: "Toutes les demandes ont une réponse",
        lead: "Les nouvelles demandes apparaîtront ici dès leur arrivée."
      };
    }
    const oldest = Math.max(...rows.map((r) => r.waiting_hours));
    return {
      title: `${plural(rows.length, "demande attend", "demandes attendent")} une réponse`,
      lead: `La plus ancienne attend depuis ${fmtHours(oldest)}. Les demandes sont classées par priorité : lit disponible, temps d'attente, date d'entrée souhaitée et adresseur.`
    };
  }, [pending.data]);

  return (
    <>
      <PageHeader
        title={headline.title}
        lead={headline.lead}
        actions={
          canWrite && (
            <button className="btn-primary" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" aria-hidden /> Saisir une demande
            </button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Filtrer par état" className="flex rounded-chip bg-paper p-1 shadow-lift">
          {SCOPES.map((s) => (
            <button
              key={s.value}
              role="tab"
              aria-selected={scope === s.value}
              onClick={() => setScope(s.value)}
              className={`rounded-chip px-4 py-1.5 text-[15px] font-bold ${
                scope === s.value ? "bg-ink text-white" : "text-ink-soft hover:text-ink"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="f-site">
          Site
        </label>
        <select id="f-site" className="input mt-0 w-auto" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
          <option value="">Tous les sites</option>
          {sites.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="f-mention">
          Mention
        </label>
        <select
          id="f-mention"
          className="input mt-0 w-auto"
          value={mention}
          onChange={(e) => setMention(e.target.value)}
        >
          <option value="">Toutes les mentions</option>
          {Object.entries(vocab.data?.mentions ?? {}).map(([code, text]) => (
            <option key={code} value={code}>
              {text}
            </option>
          ))}
        </select>
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" aria-hidden />
          <label className="sr-only" htmlFor="f-q">
            Rechercher
          </label>
          <input
            id="f-q"
            className="input mt-0 pl-9"
            placeholder="Patient, adresseur ou référence"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(340px,440px)_1fr]">
        <section aria-label="Liste des demandes" className={`min-w-0 ${selected ? "hidden xl:block" : ""}`}>
          {list.isLoading && <Spinner />}
          {list.error && <ErrorNote error={list.error} />}
          {list.data && list.data.length === 0 && (
            <Empty title={scope === "a_traiter" ? "Rien à traiter" : "Aucune demande"}>
              {scope === "a_traiter"
                ? "Chaque demande reçue a une réponse. Les accords en attente de confirmation sont dans « En cours »."
                : "Aucune demande ne correspond à ces filtres."}
            </Empty>
          )}
          <ul className="space-y-2">
            {list.data?.map((r) => (
              <li key={r.id}>
                <QueueRow
                  request={r}
                  active={r.id === selected}
                  mentionLabel={label(vocab.data?.mentions, r.mention_requested)}
                  statusLabel={label(vocab.data?.statuses, r.status)}
                  onOpen={() => navigate(`/demandes/${r.id}`)}
                />
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Détail de la demande" className={`min-w-0 ${selected ? "" : "hidden xl:block"}`}>
          {selected ? (
            <RequestDetailPanel id={selected} onBack={() => navigate("/demandes")} />
          ) : (
            <div className="sticky top-8 rounded-panel border-2 border-dashed border-line px-8 py-16 text-center text-ink-soft">
              <p className="font-display text-lg font-semibold text-ink">Choisissez une demande</p>
              <p className="mx-auto mt-2 max-w-sm">
                Vous verrez où l'accueillir, à quelle date, et pourquoi elle est à ce rang dans la file.
              </p>
            </div>
          )}
        </section>
      </div>

      {creating && (
        <NewRequestModal
          onClose={() => setCreating(false)}
          onCreated={(newId) => {
            setCreating(false);
            navigate(`/demandes/${newId}`);
          }}
        />
      )}
    </>
  );
}

function QueueRow({
  request: r,
  active,
  mentionLabel,
  statusLabel,
  onOpen
}: {
  request: AdmissionRequest;
  active: boolean;
  mentionLabel: string;
  statusLabel: string;
  onOpen: () => void;
}) {
  const waiting = r.status === "nouvelle" || r.status === "en_etude";
  const late = waiting && r.waiting_hours >= 24;
  const date = r.proposed_date ?? r.best?.safe_date ?? r.best?.probable_date;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-current={active ? "true" : undefined}
      className={`w-full rounded-panel border-2 bg-paper px-4 py-3 text-left transition-colors ${
        active ? "border-violet" : "border-transparent hover:border-line"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-display text-[17px] font-semibold">
            {mentionLabel}
            {r.patient_age !== null && <span className="font-sans font-normal text-ink-soft">, {r.patient_age} ans</span>}
          </p>
          <p className="truncate text-[14px] text-ink-soft">
            {r.referrer_facility}
            {r.referrer_unit ? `, ${r.referrer_unit}` : ""}
          </p>
        </div>
        <StatusChip status={r.status} label={statusLabel} />
      </div>
      <div className="mt-3 flex items-center gap-3 text-[14px]">
        {waiting ? (
          <span className={`whitespace-nowrap font-bold ${late ? "text-coral-dark" : "text-ink-soft"}`}>
            Attend depuis {fmtHours(r.waiting_hours)}
          </span>
        ) : (
          <span className="whitespace-nowrap text-ink-soft">Répondu en {fmtHours(r.waiting_hours)}</span>
        )}
        <span className="min-w-0 flex-1 truncate text-right text-ink-soft">
          {r.status === "accord" || r.status === "confirmee"
            ? `Entrée le ${fmtShort(r.proposed_date)}, ${r.site_name ?? ""}`
            : r.best
              ? `${r.best.safe_date ? "Lit sûr" : r.best.probable_date ? "Lit probable" : "Pas de lit"}${date ? ` le ${fmtShort(date)}` : ""}, ${r.best.site_name}`
              : waiting
                ? "Aucun site compatible"
                : ""}
        </span>
      </div>
      {waiting && (
        <div className="mt-2 flex items-center gap-2">
          <Meter value={r.priority} tone={r.priority >= 70 ? "violet" : "sun"} />
          <span className="num w-8 text-right text-[13px] font-bold text-ink-soft" aria-label={`Priorité ${Math.round(r.priority)} sur 100`}>
            {Math.round(r.priority)}
          </span>
        </div>
      )}
    </button>
  );
}
