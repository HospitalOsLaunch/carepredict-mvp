import { useEffect, useRef, useState } from "react";
import { COMPARISON_OBJECTIVES, type ComparisonObjective, type WmSession } from "../api/worldModel";
import { plansApi, type PlanEvaluation, type PlanMenu } from "../api/worldPlans";
import { remembered, remember, worldError } from "./worldModel";

interface Draft { objective: ComparisonObjective; ids: string[]; version: string | null | undefined }
function storedDraft(session: WmSession): Draft | null {
  try {
    const raw: unknown = JSON.parse(remembered("plan-draft." + session.id) ?? "null");
    if (typeof raw !== "object" || !raw || !("version" in raw) || raw.version !== session.plan_version ||
        !("objective" in raw) || !COMPARISON_OBJECTIVES.some(x => x === raw.objective) ||
        !("ids" in raw) || !Array.isArray(raw.ids) || !raw.ids.every(id => typeof id === "string") ||
        new Set(raw.ids).size !== raw.ids.length) return null;
    return { objective: raw.objective as ComparisonObjective, ids: raw.ids, version: session.plan_version };
  } catch { return null; }
}
type Result = { value: PlanMenu; key: string } | { error: string; key: string };
export function useComposedPlans(session: WmSession) {
  const [draft, setDraft] = useState<Draft | null>(() => session.phase === "planning" ? storedDraft(session) : null);
  const [criterion, setCriterion] = useState<ComparisonObjective>(draft?.objective ?? "transfer_queue");
  const objective = session.decision_objective ?? criterion;
  const [menuState, setMenu] = useState<Result | null>(null);
  const [retry, setRetry] = useState(0);
  const [pick, setPick] = useState<string | null>(null);
  const [preview, setPreview] = useState<PlanEvaluation | null>(null);
  const [subsets, setSubsets] = useState<PlanMenu | null>(null);
  const [subsetId, setSubset] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState<"preview" | "optimize" | null>(null);
  const job = useRef<AbortController | null>(null);
  const key = JSON.stringify([session.id, session.plan_version, objective, retry]);
  const snapshot = session.plan_snapshot;
  const current = menuState?.key === key ? menuState : null;
  const menu = snapshot ?? (current && "value" in current ? current.value : null);

  useEffect(() => {
    if (snapshot) return;
    const ctrl = new AbortController();
    plansApi.menu(session.id, objective, ctrl.signal).then((value) => {
      if (!ctrl.signal.aborted) setMenu({ value, key });
    }).catch((e: unknown) => { if (!ctrl.signal.aborted) setMenu({ error: worldError(e), key }); });
    return () => ctrl.abort();
  }, [session.id, objective, snapshot, key]);
  useEffect(() => () => job.current?.abort(), []);

  function cancelJob() {
    job.current?.abort();
    job.current = null;
    setWorking(null);
    setError(null);
  }
  function discardCalculations() {
    cancelJob();
    setPreview(null);
    setSubsets(null);
    setSubset(null);
  }
  function store(next: Draft | null) {
    setDraft(next);
    remember("plan-draft." + session.id, JSON.stringify(next));
  }
  function setIds(ids: string[]) {
    if (session.phase !== "planning") return;
    discardCalculations();
    store({ ids, objective, version: session.plan_version });
  }
  function chooseObjective(next: ComparisonObjective) {
    if (session.phase !== "planning" || next === objective) return;
    discardCalculations();
    setPick(null);
    setCriterion(next);
    if (draft) store({ ...draft, objective: next });
  }
  function selectPlan(id: string) {
    discardCalculations();
    setPick(id);
    store(null);
  }
  async function calculate(kind: "preview" | "optimize", ids = draft?.ids) {
    if (!ids || !menu || session.phase !== "planning" || job.current) return;
    const ctrl = new AbortController();
    job.current = ctrl;
    setWorking(kind);
    setError(null);
    setSubset(null);
    if (kind === "preview") setPreview(null);
    else setSubsets(null);
    try {
      if (kind === "preview") {
        const result = await plansApi.preview(session.id, ids, objective, ctrl.signal);
        if (!ctrl.signal.aborted) setPreview(result);
      } else {
        const result = await plansApi.optimize(session.id, ids, objective, ctrl.signal);
        if (!ctrl.signal.aborted) setSubsets(result);
      }
    } catch (e) {
      if (!ctrl.signal.aborted) setError(worldError(e));
    } finally {
      if (job.current === ctrl) { job.current = null; setWorking(null); }
    }
  }
  function tryExample() {
    const ids = menu?.example_action_ids;
    if (!ids?.length || session.phase !== "planning" || job.current) return;
    setIds(ids);
    void calculate("preview", ids);
  }
  return {
    objective, chooseObjective, menu,
    menuError: !snapshot && current && "error" in current ? current.error : null,
    retry: () => setRetry(n => n + 1), draft, setIds, pick, selectPlan, preview, subsets, subsetId, setSubset,
    calculate, tryExample, working, error,
  };
}
