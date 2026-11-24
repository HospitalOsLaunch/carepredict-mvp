import type { Plan } from "../api/types";

/** JSON Pointer into the exact plan returned by /hybrid/plan (or its stored replay). */
export function source(plan: Plan, pointer: string) {
  const path = pointer.slice(1).split("/");
  let value: unknown = plan;
  for (const key of path) value = (value as Record<string, unknown>)?.[key];
  return { "data-src": `${plan.plan_id}#${pointer}`, "data-raw": JSON.stringify(value) };
}
