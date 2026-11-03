import { ACTIVE_POLL_MS, connectionsPollMs } from "../lib/agent";
import type { ConnectionOut } from "../api/types_agent";

const idle = { pending_tasks: 0, running_task_id: null } as ConnectionOut;

describe("connections polling", () => {
  it("asks every 15 s when nothing is queued or running", () => {
    expect(connectionsPollMs(undefined)).toBe(15_000);
    expect(connectionsPollMs([idle, idle])).toBe(15_000);
  });

  it("asks every 2 s while a task waits or runs, so « Regarder en direct » shows in time", () => {
    // A demo bed sync lasts about 5 s: at 15 s the live button would almost never appear.
    expect(connectionsPollMs([idle, { ...idle, pending_tasks: 1 }])).toBe(ACTIVE_POLL_MS);
    expect(connectionsPollMs([{ ...idle, running_task_id: 7 }])).toBe(ACTIVE_POLL_MS);
    expect(ACTIVE_POLL_MS).toBeLessThanOrEqual(2_000);
  });
});
