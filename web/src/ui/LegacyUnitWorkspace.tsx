import { useCallback, useEffect, useState } from "react";
import { demoHistory, journal, useJournal } from "../data/journal";
import { useAssessment } from "../data/useAssessment";
import { clock } from "../domain/view";
import { DataQuality } from "./DataQuality";
import { Journal } from "./Journal";
import { PatientNavigation, type PatientView } from "./PatientNavigation";
import { InProgress, Proposal } from "./Proposal";
import { ProposalDetail } from "./ProposalDetail";
import { UnitPage } from "./UnitPage";
import { UnitSwitcher } from "./UnitSwitcher";
import { Toast, type ToastState, useNow } from "./common";

export function LegacyUnitWorkspace({ view }: { view: PatientView }) {
  const store = useAssessment();
  const { records, me } = useJournal();
  const [toast, setToast] = useState<ToastState | null>(null);
  const [record, setRecord] = useState<string | null>(null);
  const clearToast = useCallback(() => setToast(null), []);
  const notify = useCallback((message: string, undo?: () => void) => setToast({ message, undo }), []);
  const a = store.assessment;
  const now = useNow(a, store.loadedAt);
  const stateAt = a?.state.at;
  useEffect(() => {
    if (stateAt && (store.connection === "fixture" || store.connection === "api-plan")) {
      journal.setSamples(demoHistory(stateAt, store.units));
    } else journal.setSamples([]);
  }, [store.connection, stateAt, store.units]);

  const controls = <>
    <div className="unit-context-bar unit-ward-bar">
      <UnitSwitcher summaries={store.summaries} unitId={store.unitId} onSelect={store.setUnit} openSignal={0} />
      {store.situations.length > 1 && <label>Situation
        <select className="select" value={store.situationId} onChange={e => store.setSituation(e.target.value)}>
          {store.situations.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select></label>}
      {a && <span>État à <strong>{clock(a.state.at)}</strong></span>}
    </div>
    {store.error && <p role="alert" className="notice notice--error">{store.error}</p>}
  </>;
  if (a && a.state.hospital_id !== "ch-fictif") return <p role="alert">Les dossiers reçus concernent un autre établissement.</p>;
  const current = a && (a.scenarioId === store.situationId || (a.scenarioId === "live" && store.situationId.startsWith("live")));
  if (!a || !now || !current) return <>{controls}<p role="status">Chargement des dossiers de l’unité…</p></>;
  const props = {
    a, now, busy: store.busy, awaitingEvaluation: store.awaitingEvaluation, onEvaluate: store.evaluate,
    unit: { id: store.unitId, name: store.unitName }, onToast: notify,
  };
  return <PatientNavigation.Provider value={{ view, selectRecord: setRecord }}>
    {controls}
    {view === "unite" ? <UnitPage key={store.unitId} {...props} integrated /> :
      view === "action" ? <>
        <Proposal {...props} />
        <InProgress unitId={store.unitId} excludePlan={a.plan?.plan_id ?? null} now={now} onToast={notify} />
        <details className="jp-disclosure" id="patient-action-detail">
          <summary>Options comparées et détail du calcul</summary><ProposalDetail a={a} />
        </details>
      </> : view === "journal" ?
        <Journal records={records} me={me} now={now} openId={record} units={store.units} unitId={store.unitId} onToast={notify} /> :
        <DataQuality a={a} quality={store.quality} summary={store.shadowSummary} />}
    <Toast toast={toast} onDone={clearToast} />
  </PatientNavigation.Provider>;
}
