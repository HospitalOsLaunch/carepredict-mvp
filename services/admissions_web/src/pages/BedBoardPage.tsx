import { Ban, CalendarClock, Check, ShieldPlus, Sparkles, User, type LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";

import type { Availability, Bed, BedAction, BedStatus, BoardUnit } from "../api/types_liscop";
import { useAuth } from "../auth";
import { Empty, ErrorNote, Modal, PageHeader, Spinner } from "../components/ui";
import { fmtDateTime, fmtNum } from "../lib/format";
import { useBedAction, useBedBoard } from "../lib/liscop";
import { TensionChip } from "./RorPage";

const STATUS: Record<BedStatus, { label: string; tile: string; icon: LucideIcon }> = {
  libre: { label: "Libre", tile: "border-lagoon bg-lagoon-soft text-lagoon-dark", icon: Check },
  occupe: { label: "Occupé", tile: "border-violet/30 bg-violet-soft text-violet-dark", icon: User },
  a_nettoyer: { label: "À nettoyer", tile: "border-sun bg-sun-soft text-ink", icon: Sparkles },
  bloque: { label: "Bloqué", tile: "border-coral bg-coral-soft text-coral-dark", icon: Ban },
  reserve: { label: "Réservé", tile: "border-dashed border-ink-faint bg-sky text-ink-soft", icon: CalendarClock }
};
const STATUS_ORDER: BedStatus[] = ["libre", "a_nettoyer", "reserve", "occupe", "bloque"];
const SEX_LABEL = { F: "femme", M: "homme" } as const;

function accepts(bed: Bed): string {
  if (bed.status === "occupe") return "";
  if (bed.accepts.length === 2) return "femme ou homme";
  if (bed.accepts.length === 0) return "personne (chambre mixte à régulariser)";
  return `${SEX_LABEL[bed.accepts[0]]} seulement`;
}

function bedTitle(bed: Bed): string {
  const parts = [`Lit ${bed.label}`, STATUS[bed.status].label];
  if (bed.status_reason) parts.push(bed.status_reason);
  if (bed.status === "occupe" && bed.occupant_sex && bed.occupant_sex !== "U")
    parts.push(`occupé par ${SEX_LABEL[bed.occupant_sex]}`);
  const who = accepts(bed);
  if (who) parts.push(`peut accueillir : ${who}`);
  if (bed.isolation) parts.push("chambre d'isolement");
  return parts.join(" · ");
}

function sum(units: BoardUnit[], key: keyof Omit<Availability, "tension">): number {
  return units.reduce((acc, u) => acc + u.availability[key], 0);
}

export function BedBoardPage() {
  const board = useBedBoard();
  const { canWrite } = useAuth();
  const [siteId, setSiteId] = useState<number | "all">("all");
  const [poolId, setPoolId] = useState<number | "all">("all");
  const [statuses, setStatuses] = useState<Set<BedStatus>>(new Set());
  const [selected, setSelected] = useState<Bed | null>(null);

  const sites = board.data?.sites ?? [];
  const visibleSites = sites.filter((s) => siteId === "all" || s.site_id === siteId);
  const units = useMemo(
    () => visibleSites.flatMap((s) => s.units).filter((u) => poolId === "all" || u.pool_id === poolId),
    [visibleSites, poolId]
  );

  if (board.isLoading) return <Spinner />;
  if (board.error) return <ErrorNote error={board.error} />;

  const toggle = (status: BedStatus) =>
    setStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });

  return (
    <>
      <PageHeader
        title="Plan des lits"
        lead={
          <>
            Chaque lit, tel que le reçoivent les mouvements patients : libre, occupé, à nettoyer, bloqué ou réservé. Les
            disponibilités par genre et en isolement suivent les définitions du ROR.
          </>
        }
      />

      {sites.length === 0 ? (
        <Empty title="Aucun lit décrit pour l'instant">
          Les chambres et les lits arrivent avec le flux de mouvements (HL7) ou l'import de la structure.
        </Empty>
      ) : (
        <>
          <dl className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Disponibilités">
            <Kpi value={sum(units, "usable")} label="lits utilisables maintenant" tone="lagoon" />
            <div className="panel flex flex-col-reverse justify-end px-5 py-4">
              <dt className="mt-1 text-[14px] text-ink-soft">dont femme · homme · indifférencié</dt>
              <dd className="num flex items-baseline gap-3 font-display text-3xl font-bold">
                <span aria-label={`${sum(units, "female")} pour une femme`}>{fmtNum(sum(units, "female"))}</span>
                <span className="text-ink-faint" aria-hidden>·</span>
                <span aria-label={`${sum(units, "male")} pour un homme`}>{fmtNum(sum(units, "male"))}</span>
                <span className="text-ink-faint" aria-hidden>·</span>
                <span aria-label={`${sum(units, "either")} indifférenciés`}>{fmtNum(sum(units, "either"))}</span>
              </dd>
            </div>
            <Kpi value={sum(units, "isolation")} label="utilisables en chambre d'isolement" tone="violet" />
            <Kpi value={sum(units, "cleaning")} label="à nettoyer : bientôt disponibles" tone="sun" />
          </dl>

          <section className="panel mb-6 flex flex-wrap items-end gap-4 px-5 py-4" aria-label="Filtres">
            {sites.length > 1 && (
              <label className="field min-w-[12rem]">
                Site
                <select
                  className="input"
                  value={siteId}
                  onChange={(e) => {
                    setSiteId(e.target.value === "all" ? "all" : Number(e.target.value));
                    setPoolId("all");
                  }}
                >
                  <option value="all">Tous les sites</option>
                  {sites.map((s) => (
                    <option key={s.site_id} value={s.site_id}>
                      {s.site_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="field min-w-[14rem]">
              Unité
              <select
                className="input"
                value={poolId}
                onChange={(e) => setPoolId(e.target.value === "all" ? "all" : Number(e.target.value))}
              >
                <option value="all">Toutes les unités</option>
                {visibleSites.flatMap((s) =>
                  s.units.map((u) => (
                    <option key={u.pool_id} value={u.pool_id}>
                      {u.label}
                    </option>
                  ))
                )}
              </select>
            </label>
            <fieldset className="flex flex-wrap items-center gap-2">
              <legend className="field mb-1">Statut</legend>
              {STATUS_ORDER.map((s) => {
                const Icon = STATUS[s].icon;
                const on = statuses.has(s);
                return (
                  <button
                    key={s}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggle(s)}
                    className={`chip border-2 px-3 py-1 ${on ? STATUS[s].tile : "border-line bg-paper text-ink-soft"}`}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden /> {STATUS[s].label}
                  </button>
                );
              })}
            </fieldset>
            <p className="ml-auto text-[13px] text-ink-faint">Mis à jour le {fmtDateTime(board.data?.generated_at)}</p>
          </section>

          <div className="grid gap-6 2xl:grid-cols-2">
            {units.map((u) => (
              <UnitPanel
                key={u.pool_id}
                unit={u}
                site={visibleSites.length > 1 ? visibleSites.find((s) => s.units.includes(u))?.site_name : undefined}
                statuses={statuses}
                onSelect={canWrite ? setSelected : undefined}
              />
            ))}
          </div>
          <Legend />
        </>
      )}
      {selected && <BedDialog bed={selected} onClose={() => setSelected(null)} />}
    </>
  );
}

function Kpi({ value, label, tone }: { value: number; label: string; tone: "lagoon" | "violet" | "sun" }) {
  const bar = { lagoon: "before:bg-lagoon", violet: "before:bg-violet", sun: "before:bg-sun" }[tone];
  return (
    <div
      className={`panel relative flex flex-col-reverse justify-end overflow-hidden px-5 py-4 before:absolute before:inset-x-0 before:top-0 before:h-1 ${bar}`}
    >
      <dt className="mt-1 text-[14px] text-ink-soft">{label}</dt>
      <dd className="num font-display text-3xl font-bold">{fmtNum(value)}</dd>
    </div>
  );
}

function UnitPanel({
  unit,
  site,
  statuses,
  onSelect
}: {
  unit: BoardUnit;
  site?: string;
  statuses: Set<BedStatus>;
  onSelect?: (bed: Bed) => void;
}) {
  const a = unit.availability;
  const rooms = unit.rooms
    .map((r) => ({ ...r, beds: r.beds.filter((b) => statuses.size === 0 || statuses.has(b.status)) }))
    .filter((r) => r.beds.length > 0);
  const headingId = `unit-${unit.pool_id}`;
  return (
    <section className="panel px-5 py-4" aria-labelledby={headingId}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={headingId}>{unit.label}</h2>
          {site && <p className="text-[13px] text-ink-faint">{site}</p>}
        </div>
        <TensionChip level={a.tension.level} rate={a.tension.availability_rate} />
      </header>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[14px] text-ink-soft">
        <span>
          <strong className="num text-ink">{a.usable}</strong> utilisables sur {a.installed}
        </span>
        <span>
          F {a.female} · H {a.male} · indiff. {a.either}
        </span>
        <span>isolement {a.isolation}</span>
        {a.closed > 0 && <span>fermés {a.closed}</span>}
        {a.sex_conflict > 0 && <span className="text-coral-dark">{a.sex_conflict} lit(s) en chambre mixte</span>}
      </p>
      {rooms.length === 0 ? (
        <p className="mt-4 text-[14px] text-ink-faint">Aucun lit avec ce statut.</p>
      ) : (
        <ul className="mt-4 grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2" aria-label={`Chambres, ${unit.label}`}>
          {rooms.map((r) => (
            <li key={r.room} className="rounded-xl border border-line bg-sky/60 p-1.5">
              <p className="px-1 pb-1 text-[12px] font-bold text-ink-faint">Ch. {r.room}</p>
              <div className="flex gap-1.5">
                {r.beds.map((b) => (
                  <BedTile key={b.id} bed={b} onSelect={onSelect} />
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function BedTile({ bed, onSelect }: { bed: Bed; onSelect?: (bed: Bed) => void }) {
  const s = STATUS[bed.status];
  const Icon = s.icon;
  const sex = bed.status !== "occupe" && bed.accepts.length === 1 ? (bed.accepts[0] === "F" ? "F" : "H") : null;
  const content = (
    <>
      <span className="flex items-center justify-between gap-1">
        <Icon className="h-4 w-4 shrink-0" aria-hidden />
        <span className="flex items-center gap-0.5">
          {sex && <span className="rounded bg-paper/80 px-1 text-[11px] font-bold leading-4">{sex}</span>}
          {bed.isolation && <ShieldPlus className="h-3.5 w-3.5" aria-hidden />}
        </span>
      </span>
      <span className="num mt-1 block truncate text-[13px] font-bold">{bed.label}</span>
      <span className="sr-only">{bedTitle(bed)}</span>
    </>
  );
  const cls = `block min-h-[3.5rem] flex-1 rounded-lg border-2 px-1.5 py-1 text-left ${s.tile}`;
  if (!onSelect)
    return (
      <span className={cls} title={bedTitle(bed)}>
        {content}
      </span>
    );
  return (
    <button type="button" className={`${cls} transition-transform hover:-translate-y-0.5`} title={bedTitle(bed)} onClick={() => onSelect(bed)}>
      {content}
    </button>
  );
}

function Legend() {
  return (
    <p className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-ink-soft">
      {STATUS_ORDER.map((s) => {
        const Icon = STATUS[s].icon;
        return (
          <span key={s} className="inline-flex items-center gap-1">
            <span className={`inline-grid h-5 w-5 place-items-center rounded border-2 ${STATUS[s].tile}`}>
              <Icon className="h-3 w-3" aria-hidden />
            </span>
            {STATUS[s].label}
          </span>
        );
      })}
      <span className="inline-flex items-center gap-1">
        <ShieldPlus className="h-4 w-4" aria-hidden /> isolement
      </span>
      <span>F / H : lit qui n'accueille qu'une femme ou qu'un homme (chambre partagée ou lit réservé).</span>
    </p>
  );
}

const ACTIONS: Record<BedStatus, { action: BedAction; label: string; danger?: boolean }[]> = {
  libre: [
    { action: "reserver", label: "Réserver pour une entrée" },
    { action: "bloquer", label: "Bloquer", danger: true }
  ],
  a_nettoyer: [
    { action: "nettoye", label: "Marquer nettoyé" },
    { action: "bloquer", label: "Bloquer", danger: true }
  ],
  bloque: [{ action: "debloquer", label: "Débloquer" }],
  reserve: [{ action: "annuler_reservation", label: "Annuler la réservation" }],
  occupe: []
};

function BedDialog({ bed, onClose }: { bed: Bed; onClose: () => void }) {
  const mutation = useBedAction();
  const [reason, setReason] = useState("");
  const [blocking, setBlocking] = useState(false);
  const run = (action: BedAction) =>
    mutation.mutate(
      { id: bed.id, action, reason: action === "bloquer" || action === "reserver" ? reason.trim() || undefined : undefined },
      { onSuccess: onClose }
    );
  const actions = ACTIONS[bed.status];
  return (
    <Modal title={`Lit ${bed.label}`} onClose={onClose}>
      <p className="text-ink-soft">
        Chambre {bed.room} · <strong className="text-ink">{STATUS[bed.status].label}</strong>
        {bed.status_reason && <> · {bed.status_reason}</>}
        {bed.isolation && <> · chambre d'isolement</>}
      </p>
      {accepts(bed) && <p className="mt-1 text-ink-soft">Peut accueillir : {accepts(bed)}.</p>}
      {bed.status === "occupe" ? (
        <p className="mt-4 rounded-xl bg-violet-soft px-3 py-2 text-[15px] text-violet-dark">
          Lit occupé : il se libère à la sortie ou à la mutation du patient, reçue du dossier patient.
        </p>
      ) : blocking ? (
        <form
          className="mt-4"
          onSubmit={(e) => {
            e.preventDefault();
            run("bloquer");
          }}
        >
          <label className="field" htmlFor="block-reason">
            Motif du blocage
          </label>
          <input
            id="block-reason"
            className="input"
            required
            minLength={3}
            maxLength={200}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Ex. : fuite d'eau, matériel en panne"
          />
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="submit" className="btn-danger" disabled={mutation.isPending || reason.trim().length < 3}>
              Confirmer le blocage
            </button>
            <button type="button" className="btn-quiet" onClick={() => setBlocking(false)}>
              Retour
            </button>
          </div>
        </form>
      ) : (
        <div className="mt-5 flex flex-wrap gap-2">
          {actions.map((a) => (
            <button
              key={a.action}
              type="button"
              className={a.danger ? "btn-danger" : "btn-primary"}
              disabled={mutation.isPending}
              onClick={() => (a.action === "bloquer" ? setBlocking(true) : run(a.action))}
            >
              {a.label}
            </button>
          ))}
          <button type="button" className="btn-quiet" onClick={onClose}>
            Annuler
          </button>
        </div>
      )}
      {mutation.error && (
        <div className="mt-4">
          <ErrorNote error={mutation.error} />
        </div>
      )}
    </Modal>
  );
}
