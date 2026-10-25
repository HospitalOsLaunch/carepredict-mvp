import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Check, ClipboardCopy, MessageSquarePlus, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { AgentTask, PortalReply, RequestDetail, Suggestion } from "../api/types";
import { useAuth } from "../auth";
import { fmtDateTime, fmtDay, fmtHours, fmtShort, isoDay } from "../lib/format";
import { label, useVocabulary } from "../lib/queries";
import { useForecast, useRequest, useRequestAction } from "../lib/requests";
import { LampLegend, LampStrip } from "./LampStrip";
import { AdmitModal, ReasonModal } from "./RequestForms";
import { ErrorNote, Spinner, StatusChip } from "./ui";

interface Pick {
  siteId: number;
  day: string;
}

const OPEN = ["nouvelle", "en_etude", "accord", "confirmee"];

export function RequestDetailPanel({ id, onBack }: { id: number; onBack: () => void }) {
  const query = useRequest(id);
  if (query.isLoading) return <Spinner />;
  if (query.error) return <ErrorNote error={query.error} />;
  if (!query.data) return null;
  return <Detail key={query.data.id} request={query.data} onBack={onBack} />;
}

function defaultPick(r: RequestDetail): Pick | null {
  if ((r.status === "accord" || r.status === "confirmee") && r.site_id && r.proposed_date) {
    return { siteId: r.site_id, day: r.proposed_date };
  }
  const best = r.best;
  const day = best?.safe_date ?? best?.probable_date;
  return best && day ? { siteId: best.site_id, day } : null;
}

function Detail({ request: r, onBack }: { request: RequestDetail; onBack: () => void }) {
  const vocab = useVocabulary();
  const forecast = useForecast();
  const { canWrite } = useAuth();
  const action = useRequestAction(r.id);
  const [pick, setPick] = useState<Pick | null>(() => defaultPick(r));
  const [modal, setModal] = useState<"refuse" | "lose" | "admit" | null>(null);
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setPick(defaultPick(r));
    // Reset the picked date only when the request itself moved on.
  }, [r.status, r.site_id, r.proposed_date]);

  const daysByPool = useMemo(() => {
    const map = new Map<string, NonNullable<typeof forecast.data>["pools"][number]["days"]>();
    forecast.data?.pools.forEach((p) => map.set(`${p.site_id}:${p.mention}`, p.days));
    return map;
  }, [forecast.data]);

  const open = OPEN.includes(r.status);
  const mention = label(vocab.data?.mentions, r.mention_requested);
  const pickSite = r.suggestions.find((s) => s.site_id === pick?.siteId);
  const today = forecast.data?.as_of ?? isoDay(new Date());

  function run(name: string, body?: unknown) {
    action.mutate({ action: name, body });
  }

  async function copy() {
    if (!r.draft_message) return;
    try {
      await navigator.clipboard.writeText(r.draft_message);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  const actions: ReactNode[] = [];
  if (canWrite) {
    if (r.status === "nouvelle" || r.status === "en_etude") {
      actions.push(
        <button
          key="accord"
          className="btn-primary"
          disabled={!pick || action.isPending}
          onClick={() => pick && run("accord", { site_id: pick.siteId, proposed_date: pick.day })}
        >
          <Check className="h-4 w-4" aria-hidden />
          {pick ? `Donner un accord pour le ${fmtShort(pick.day)}` : "Choisissez une date"}
        </button>
      );
      actions.push(
        <button key="refuse" className="btn-danger" onClick={() => setModal("refuse")}>
          Refuser
        </button>
      );
      if (r.status === "nouvelle") {
        actions.push(
          <button
            key="study"
            className="btn-quiet"
            disabled={action.isPending}
            onClick={() => run("start", { site_id: pick?.siteId ?? null })}
          >
            Mettre en étude
          </button>
        );
      }
    }
    if (r.status === "accord" || r.status === "confirmee") {
      const otherSite = pick && pick.siteId !== r.site_id;
      const otherDay = pick && pick.siteId === r.site_id && pick.day !== r.proposed_date;
      if (otherSite && pickSite) {
        actions.push(
          <button key="reorient" className="btn-sun" onClick={() => run("reorient", { site_id: pick.siteId })}>
            Réorienter vers {pickSite.site_name}
          </button>
        );
      } else if (r.status === "accord") {
        actions.push(
          <button
            key="confirm"
            className="btn-primary"
            disabled={action.isPending}
            onClick={() => run("confirm", otherDay && pick ? { proposed_date: pick.day } : {})}
          >
            <Check className="h-4 w-4" aria-hidden />
            {otherDay && pick ? `Confirmée pour le ${fmtShort(pick.day)}` : "L'adresseur a confirmé"}
          </button>
        );
      }
      actions.push(
        <button key="admit" className={r.status === "confirmee" ? "btn-primary" : "btn-quiet"} onClick={() => setModal("admit")}>
          Admettre le patient
        </button>
      );
      actions.push(
        <button key="lose" className="btn-danger" onClick={() => setModal("lose")}>
          Demande perdue
        </button>
      );
    }
    if (r.status === "refusee" || r.status === "perdue") {
      actions.push(
        <button key="reopen" className="btn-quiet" onClick={() => run("reopen", {})}>
          Rouvrir la demande
        </button>
      );
    }
  }

  return (
    <article className="panel min-w-0 overflow-hidden">
      <header className="border-b border-line px-6 pb-5 pt-5">
        <button className="btn-ghost -ml-3 mb-2 xl:hidden" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden /> Toutes les demandes
        </button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[26px]">
              {mention}, {r.patient_ref}
            </h2>
            <p className="mt-1 text-ink-soft">
              Reçue le {fmtDateTime(r.received_at)} via {label(vocab.data?.sources, r.source)}
              {r.external_ref ? ` (${r.external_ref})` : ""}.{" "}
              {r.first_response_at
                ? `Réponse envoyée en ${fmtHours(r.waiting_hours)}.`
                : `Sans réponse depuis ${fmtHours(r.waiting_hours)}.`}
            </p>
          </div>
          <StatusChip status={r.status} label={label(vocab.data?.statuses, r.status)} />
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 text-[15px] sm:grid-cols-3">
          <Fact term="Adresseur" value={`${r.referrer_facility}${r.referrer_unit ? `, ${r.referrer_unit}` : ""}`} />
          <Fact term="Motif" value={r.clinical_category ?? "Non précisé"} />
          <Fact
            term="Patient"
            value={[r.patient_age !== null ? `${r.patient_age} ans` : null, r.patient_sex === "F" ? "femme" : r.patient_sex === "M" ? "homme" : null]
              .filter(Boolean)
              .join(", ") || "Non précisé"}
          />
          <Fact term="Charge en soins" value={`Niveau ${r.care_level} sur 4`} />
          <Fact
            term="Besoins"
            value={
              [
                r.isolation_required ? "Isolement" : null,
                ...r.special_needs.map((n) => label(vocab.data?.special_needs, n))
              ]
                .filter(Boolean)
                .join(", ") || "Aucun particulier"
            }
          />
          <Fact term="Entrée souhaitée" value={r.desired_date ? fmtDay(r.desired_date) : "Dès que possible"} />
        </dl>
      </header>

      {open && (
        <section className="border-b border-line px-6 py-5" aria-labelledby="where">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 id="where">Où l'accueillir</h3>
            <LampLegend />
          </div>
          <p className="mt-1 text-[14px] text-ink-soft">
            Touchez un jour pour choisir la date d'entrée proposée. Les lits déjà promis sont déduits.
          </p>
          <ul className="mt-4 space-y-3">
            {r.suggestions.map((s) => (
              <SiteOption
                key={s.site_id}
                suggestion={s}
                current={s.site_id === r.site_id}
                days={daysByPool.get(`${s.site_id}:${r.mention_requested}`)}
                pick={pick}
                onPick={canWrite ? (day) => setPick({ siteId: s.site_id, day }) : undefined}
              />
            ))}
          </ul>
          {pick && pickSite && (
            <p className="mt-3 text-[14px] text-ink-soft">
              Sélection : {pickSite.site_name}, {fmtDay(pick.day)} ({relative(pick.day, today)}).
            </p>
          )}
        </section>
      )}

      {actions.length > 0 && (
        <div className="sticky bottom-0 flex flex-wrap gap-2 border-b border-line bg-paper/95 px-6 py-4 backdrop-blur">
          {actions}
        </div>
      )}
      {action.error && (
        <div className="px-6 pt-4">
          <ErrorNote error={action.error} />
        </div>
      )}

      {r.draft_message && (
        <section className="border-b border-line px-6 py-5" aria-labelledby="msg">
          <div className="flex items-center justify-between gap-2">
            <h3 id="msg">Message pour l'adresseur</h3>
            <button className="btn-quiet" onClick={copy}>
              <ClipboardCopy className="h-4 w-4" aria-hidden /> {copied ? "Copié" : "Copier le message"}
            </button>
          </div>
          <pre className="mt-3 whitespace-pre-wrap rounded-xl bg-sky px-4 py-3 font-sans text-[15px] leading-relaxed">
            {r.draft_message}
          </pre>
        </section>
      )}

      {r.portal_reply && <PortalReplyPanel reply={r.portal_reply} requestId={r.id} source={label(vocab.data?.sources, r.source)} />}

      {(pickSite ?? r.best) && open && (
        <details className="border-b border-line px-6 py-4">
          <summary className="cursor-pointer font-display text-[17px] font-semibold">
            Pourquoi cette priorité : {Math.round((pickSite ?? r.best)!.score)} sur 100
          </summary>
          <table className="mt-3 w-full text-[14px]">
            <caption className="sr-only">Facteurs de priorité</caption>
            <thead className="text-left text-ink-faint">
              <tr>
                <th className="py-1 font-normal">Critère</th>
                <th className="py-1 font-normal">Constat</th>
                <th className="py-1 text-right font-normal">Points</th>
              </tr>
            </thead>
            <tbody>
              {(pickSite ?? r.best)!.factors.map((f) => (
                <tr key={f.code} className="border-t border-line">
                  <td className="py-2 pr-3">{f.label}</td>
                  <td className="py-2 pr-3 text-ink-soft">{f.detail}</td>
                  <td className="num py-2 text-right font-bold">
                    {f.contribution.toLocaleString("fr-FR")}
                    <span className="font-normal text-ink-faint"> / {Math.round(f.weight * 100)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <section className="px-6 py-5" aria-labelledby="history">
        <h3 id="history">Historique</h3>
        <ol className="mt-3 space-y-3 border-l-2 border-line pl-4">
          {r.events.map((e, i) => (
            <li key={i} className="relative">
              <span className="absolute -left-[23px] top-1.5 h-3 w-3 rounded-full border-2 border-paper bg-violet" aria-hidden />
              <p className="text-[15px]">
                <span className="font-bold">{eventLabel(e.kind)}</span>
                {e.detail ? <span className="text-ink-soft"> : {e.detail}</span> : null}
              </p>
              <p className="text-[13px] text-ink-faint">
                {fmtDateTime(e.at)}
                {e.actor ? `, par ${e.actor}` : ""}
              </p>
            </li>
          ))}
        </ol>
        {canWrite && (
          <form
            className="mt-4 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!note.trim()) return;
              action.mutate({ action: "notes", body: { text: note.trim() } }, { onSuccess: () => setNote("") });
            }}
          >
            <label htmlFor="note" className="sr-only">
              Ajouter une note
            </label>
            <input
              id="note"
              className="input mt-0"
              placeholder="Ajouter une note (appel de l'adresseur, pièce manquante…)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <button className="btn-quiet shrink-0" type="submit" disabled={!note.trim()}>
              <MessageSquarePlus className="h-4 w-4" aria-hidden /> Ajouter
            </button>
          </form>
        )}
      </section>

      {modal === "refuse" && (
        <ReasonModal
          title="Refuser la demande"
          confirm="Refuser"
          reasons={vocab.data?.refusal_reasons ?? {}}
          busy={action.isPending}
          error={action.error}
          onClose={() => setModal(null)}
          onSubmit={(reason, comment) =>
            action.mutate({ action: "refuse", body: { reason, comment: comment || null } }, { onSuccess: () => setModal(null) })
          }
        />
      )}
      {modal === "lose" && (
        <ReasonModal
          title="Déclarer la demande perdue"
          confirm="Déclarer perdue"
          reasons={vocab.data?.loss_reasons ?? {}}
          busy={action.isPending}
          error={action.error}
          onClose={() => setModal(null)}
          onSubmit={(reason, comment) =>
            action.mutate({ action: "lose", body: { reason, comment: comment || null } }, { onSuccess: () => setModal(null) })
          }
        />
      )}
      {modal === "admit" && (
        <AdmitModal
          today={today}
          proposed={r.proposed_date}
          busy={action.isPending}
          error={action.error}
          onClose={() => setModal(null)}
          onSubmit={(admission, planned) =>
            action.mutate(
              { action: "admit", body: { admission_date: admission, planned_discharge_date: planned || null } },
              { onSuccess: () => setModal(null) }
            )
          }
        />
      )}
    </article>
  );
}

function relative(day: string, today: string): string {
  const diff = Math.round((new Date(`${day}T12:00:00`).getTime() - new Date(`${today}T12:00:00`).getTime()) / 86_400_000);
  if (diff === 0) return "aujourd'hui";
  if (diff === 1) return "demain";
  return `dans ${diff} jours`;
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <dt className="text-[13px] text-ink-faint">{term}</dt>
      <dd className="font-bold">{value}</dd>
    </div>
  );
}

function SiteOption({
  suggestion: s,
  current,
  days,
  pick,
  onPick
}: {
  suggestion: Suggestion;
  current: boolean;
  days: Parameters<typeof LampStrip>[0]["days"] | undefined;
  pick: Pick | null;
  onPick?: (day: string) => void;
}) {
  const selected = pick?.siteId === s.site_id;
  return (
    <li className={`min-w-0 rounded-2xl border-2 px-4 py-3 ${selected ? "border-violet bg-violet-soft/40" : "border-line"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-display text-[17px] font-semibold">
          {s.site_name}
          {current && <span className="ml-2 font-sans text-[13px] font-bold text-violet">site actuel</span>}
        </p>
        {s.eligible ? (
          <p className="text-[14px] text-ink-soft">
            {s.safe_date
              ? `Lit sûr dès le ${fmtShort(s.safe_date)}`
              : s.probable_date
                ? `Lit probable dès le ${fmtShort(s.probable_date)}`
                : "Pas de lit sur 14 jours"}
          </p>
        ) : (
          <p className="text-[14px] font-bold text-coral-dark">Incompatible</p>
        )}
      </div>
      {s.eligible ? (
        days ? (
          <div className="mt-2 overflow-x-auto">
            <LampStrip days={days} onPick={onPick} highlight={selected ? pick?.day : null} />
          </div>
        ) : (
          <Spinner label="Prévision" />
        )
      ) : (
        <ul className="mt-1 list-disc pl-5 text-[14px] text-ink-soft">
          {s.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

const EVENT_LABELS: Record<string, string> = {
  recue: "Demande reçue",
  recue_auto: "Demande déposée par l'agent",
  etude: "Mise en étude",
  accord: "Accord envoyé",
  refus: "Refus envoyé",
  confirmation: "Confirmée par l'adresseur",
  admission: "Patient admis",
  perte: "Demande perdue",
  reouverture: "Demande rouverte",
  reorientation: "Réorientée",
  note: "Note"
};

function eventLabel(kind: string): string {
  return EVENT_LABELS[kind] ?? kind;
}


const REPLY_STATE: Record<string, { text: string; tone: string }> = {
  pending: { text: "En file : l'agent va reporter la réponse sur le portail", tone: "bg-violet-soft text-violet-dark" },
  running: { text: "L'agent saisit la réponse sur le portail", tone: "bg-violet-soft text-violet-dark" },
  done: { text: "Réponse reportée et relue sur le portail", tone: "bg-lagoon-soft text-lagoon-dark" },
  manual: { text: "Réponse saisie à la main sur le portail", tone: "bg-sky-deep text-ink-soft" },
  needs_human: { text: "À reprendre à la main : l'agent n'a pas pu confirmer la saisie", tone: "bg-coral-soft text-coral-dark" },
  failed: { text: "Échec de la saisie sur le portail", tone: "bg-coral-soft text-coral-dark" },
  cancelled: { text: "Report annulé", tone: "bg-sky-deep text-ink-soft" }
};

function PortalReplyPanel({ reply, requestId, source }: { reply: PortalReply; requestId: number; source: string }) {
  const { canWrite } = useAuth();
  const queryClient = useQueryClient();
  const act = useMutation({
    mutationFn: (what: "retry" | "manual") => api<AgentTask>(`/agent/tasks/${reply.task_id}/${what}`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["request", requestId] });
      void queryClient.invalidateQueries({ queryKey: ["agent"] });
    }
  });
  const state = REPLY_STATE[reply.status] ?? { text: reply.status, tone: "bg-sky-deep text-ink-soft" };
  const stuck = reply.status === "needs_human" || reply.status === "failed";
  const closed = ["done", "manual", "cancelled"].includes(reply.status);
  return (
    <section className="border-b border-line px-6 py-5" aria-labelledby="portal">
      <h3 id="portal" className="flex items-center gap-2">
        <Bot className="h-5 w-5 text-violet" aria-hidden /> Report sur {source}
      </h3>
      <p className={`mt-3 rounded-xl px-3 py-2 text-[15px] font-bold ${state.tone}`} role="status">
        {state.text}
      </p>
      <p className="mt-2 text-[13px] text-ink-faint">
        Mis à jour le {fmtDateTime(reply.updated_at)}
        {reply.engine_used ? `, moteur : ${reply.engine_used}` : ""}
      </p>
      {reply.error && stuck && <p className="mt-2 text-[14px] text-ink-soft">{reply.error}</p>}
      {canWrite && !closed && (
        <div className="mt-3 flex flex-wrap gap-2">
          {stuck && (
            <button className="btn-quiet" disabled={act.isPending} onClick={() => act.mutate("retry")}>
              <RotateCcw className="h-4 w-4" aria-hidden /> Relancer l'agent
            </button>
          )}
          <button className="btn-quiet" disabled={act.isPending} onClick={() => act.mutate("manual")}>
            <Check className="h-4 w-4" aria-hidden /> Je l'ai saisie à la main
          </button>
        </div>
      )}
      {act.error && (
        <div className="mt-3">
          <ErrorNote error={act.error} />
        </div>
      )}
    </section>
  );
}
