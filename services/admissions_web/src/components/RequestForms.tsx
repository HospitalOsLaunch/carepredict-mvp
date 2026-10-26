import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { RequestDetail } from "../api/types";
import { useSites, useVocabulary } from "../lib/queries";
import { ErrorNote, Modal } from "./ui";

export function ReasonModal({
  title,
  confirm,
  reasons,
  busy,
  error,
  onClose,
  onSubmit
}: {
  title: string;
  confirm: string;
  reasons: Record<string, string>;
  busy: boolean;
  error: unknown;
  onClose: () => void;
  onSubmit: (reason: string, comment: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (reason) onSubmit(reason, comment.trim());
        }}
      >
        <fieldset>
          <legend className="field">Motif</legend>
          <div className="mt-2 space-y-1.5">
            {Object.entries(reasons).map(([code, text]) => (
              <label key={code} className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2 hover:bg-sky">
                <input
                  type="radio"
                  name="reason"
                  value={code}
                  checked={reason === code}
                  onChange={() => setReason(code)}
                  className="h-4 w-4 accent-violet"
                />
                {text}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="field mt-4" htmlFor="comment">
          Précision (facultatif)
        </label>
        <textarea id="comment" className="input" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
        {error !== null && error !== undefined && (
          <div className="mt-3">
            <ErrorNote error={error} />
          </div>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn-primary" disabled={!reason || busy}>
            {confirm}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function AdmitModal({
  today,
  proposed,
  busy,
  error,
  onClose,
  onSubmit
}: {
  today: string;
  proposed: string | null;
  busy: boolean;
  error: unknown;
  onClose: () => void;
  onSubmit: (admission: string, planned: string) => void;
}) {
  const [admission, setAdmission] = useState(proposed && proposed <= today ? proposed : today);
  const [planned, setPlanned] = useState("");
  return (
    <Modal title="Admettre le patient" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(admission, planned);
        }}
      >
        <p className="text-ink-soft">Le séjour est créé dans le site attribué ; le lit n'est plus compté comme libre.</p>
        <label className="field mt-4" htmlFor="admission">
          Date d'entrée
        </label>
        <input
          id="admission"
          type="date"
          className="input"
          max={today}
          required
          value={admission}
          onChange={(e) => setAdmission(e.target.value)}
        />
        <label className="field mt-4" htmlFor="planned">
          Sortie prévue (facultatif)
        </label>
        <input id="planned" type="date" className="input" min={admission} value={planned} onChange={(e) => setPlanned(e.target.value)} />
        {error !== null && error !== undefined && (
          <div className="mt-3">
            <ErrorNote error={error} />
          </div>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn-primary" disabled={busy}>
            Admettre le patient
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function NewRequestModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const vocab = useVocabulary();
  const sites = useSites();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    source: "viatrajectoire",
    external_ref: "",
    referrer_facility: "",
    referrer_unit: "",
    patient_ref: "",
    patient_age: "",
    patient_sex: "",
    mention_requested: "",
    clinical_category: "",
    care_level: "2",
    isolation_required: false,
    special_needs: [] as string[],
    desired_date: "",
    site_id: ""
  });
  const create = useMutation({
    mutationFn: () =>
      api<RequestDetail>("/requests", {
        method: "POST",
        json: {
          source: form.source,
          external_ref: form.external_ref.trim() || null,
          referrer_facility: form.referrer_facility.trim(),
          referrer_unit: form.referrer_unit.trim() || null,
          patient_ref: form.patient_ref.trim(),
          patient_age: form.patient_age ? Number(form.patient_age) : null,
          patient_sex: form.patient_sex || null,
          mention_requested: form.mention_requested,
          clinical_category: form.clinical_category.trim() || null,
          care_level: Number(form.care_level),
          isolation_required: form.isolation_required,
          special_needs: form.special_needs,
          desired_date: form.desired_date || null,
          site_id: form.site_id ? Number(form.site_id) : null
        }
      }),
    onSuccess: (detail) => {
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
      queryClient.setQueryData(["request", detail.id], detail);
      onCreated(detail.id);
    }
  });
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }));

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <Modal title="Saisir une demande" onClose={onClose} wide>
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="field" htmlFor="n-source">
            Reçue par
          </label>
          <select id="n-source" className="input" value={form.source} onChange={(e) => set("source", e.target.value)}>
            {Object.entries(vocab.data?.sources ?? {}).map(([code, text]) => (
              <option key={code} value={code}>
                {text}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field" htmlFor="n-ref">
            Référence de la demande
          </label>
          <input id="n-ref" className="input" placeholder="Numéro ViaTrajectoire" value={form.external_ref} onChange={(e) => set("external_ref", e.target.value)} />
        </div>
        <div>
          <label className="field" htmlFor="n-facility">
            Établissement adresseur
          </label>
          <input id="n-facility" required className="input" value={form.referrer_facility} onChange={(e) => set("referrer_facility", e.target.value)} />
        </div>
        <div>
          <label className="field" htmlFor="n-unit">
            Service adresseur
          </label>
          <input id="n-unit" className="input" value={form.referrer_unit} onChange={(e) => set("referrer_unit", e.target.value)} />
        </div>
        <div>
          <label className="field" htmlFor="n-patient">
            Référence patient
          </label>
          <input
            id="n-patient"
            required
            pattern="[A-Za-z0-9_\-.]{3,64}"
            title="Référence pseudonymisée : lettres, chiffres, tirets. Jamais de nom ni de NIR."
            className="input"
            placeholder="Ex. le numéro de dossier ViaTrajectoire"
            value={form.patient_ref}
            onChange={(e) => set("patient_ref", e.target.value)}
          />
          <p className="mt-1 text-[13px] text-ink-faint">Pas de nom ni de numéro de sécurité sociale.</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="field" htmlFor="n-age">
              Âge
            </label>
            <input id="n-age" type="number" min={0} max={120} className="input" value={form.patient_age} onChange={(e) => set("patient_age", e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="n-sex">
              Sexe
            </label>
            <select id="n-sex" className="input" value={form.patient_sex} onChange={(e) => set("patient_sex", e.target.value)}>
              <option value="">Non précisé</option>
              <option value="F">Femme</option>
              <option value="M">Homme</option>
              <option value="I">Autre</option>
            </select>
          </div>
        </div>
        <div>
          <label className="field" htmlFor="n-mention">
            Mention SMR demandée
          </label>
          <select id="n-mention" required className="input" value={form.mention_requested} onChange={(e) => set("mention_requested", e.target.value)}>
            <option value="" disabled>
              Choisir
            </option>
            {Object.entries(vocab.data?.mentions ?? {}).map(([code, text]) => (
              <option key={code} value={code}>
                {text}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field" htmlFor="n-cat">
            Motif de prise en charge
          </label>
          <input id="n-cat" className="input" placeholder="Ex. prothèse totale de hanche" value={form.clinical_category} onChange={(e) => set("clinical_category", e.target.value)} />
        </div>
        <div>
          <label className="field" htmlFor="n-care">
            Charge en soins
          </label>
          <select id="n-care" className="input" value={form.care_level} onChange={(e) => set("care_level", e.target.value)}>
            <option value="1">1, autonome</option>
            <option value="2">2, aide partielle</option>
            <option value="3">3, aide importante</option>
            <option value="4">4, dépendance totale</option>
          </select>
        </div>
        <div>
          <label className="field" htmlFor="n-date">
            Entrée souhaitée
          </label>
          <input id="n-date" type="date" className="input" value={form.desired_date} onChange={(e) => set("desired_date", e.target.value)} />
        </div>
        <fieldset className="sm:col-span-2">
          <legend className="field">Besoins particuliers</legend>
          <div className="mt-2 flex flex-wrap gap-2">
            <Toggle checked={form.isolation_required} onChange={(v) => set("isolation_required", v)} label="Isolement" />
            {Object.entries(vocab.data?.special_needs ?? {}).map(([code, text]) => (
              <Toggle
                key={code}
                label={text}
                checked={form.special_needs.includes(code)}
                onChange={(v) =>
                  set("special_needs", v ? [...form.special_needs, code] : form.special_needs.filter((c) => c !== code))
                }
              />
            ))}
          </div>
        </fieldset>
        <div className="sm:col-span-2">
          <label className="field" htmlFor="n-site">
            Adressée à un site précis
          </label>
          <select id="n-site" className="input" value={form.site_id} onChange={(e) => set("site_id", e.target.value)}>
            <option value="">Au groupe (site à choisir)</option>
            {sites.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        {create.error && (
          <div className="sm:col-span-2">
            <ErrorNote error={create.error} />
          </div>
        )}
        <div className="flex justify-end gap-2 sm:col-span-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn-primary" disabled={create.isPending}>
            Enregistrer la demande
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label
      className={`cursor-pointer select-none rounded-chip border-2 px-3 py-1 text-[14px] font-bold has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-violet ${
        checked ? "border-violet bg-violet-soft text-violet-dark" : "border-line text-ink-soft hover:border-ink-faint"
      }`}
    >
      <input type="checkbox" className="sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
