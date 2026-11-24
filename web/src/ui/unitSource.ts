import type { LiveSnapshot, Plan } from "../api/types";

/** JSON Pointer into the exact plan returned by /hybrid/plan (or its stored replay). */
export function source(plan: Plan | LiveSnapshot, pointer: string) {
  const path = pointer.slice(1).split("/");
  let value: unknown = plan;
  for (const key of path) value = (value as Record<string, unknown>)?.[key];
  return {
    "data-src": `${"plan_id" in plan ? plan.plan_id : plan.semantic_fingerprint}#${pointer}`,
    "data-raw": JSON.stringify(value),
  };
}
