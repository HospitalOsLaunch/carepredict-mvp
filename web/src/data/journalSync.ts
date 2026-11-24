import { HttpError } from "../api/http";
import { journalApi } from "../auth/api";
import { type DecisionRecord, type Person, journal } from "./journal";

/**
 * Binds the decision journal to the signed-in account: loads the server copy, then saves every change
 * (debounced) with the revision it was based on. If another tab or device saved in between, the server copy
 * is adopted and the person's last change is lost rather than silently overwriting theirs.
 */
export async function bindJournal(person: Person, debounceMs = 400): Promise<() => Promise<void>> {
  const initial = await journalApi.get();
  let revision = initial.revision;
  let pending: DecisionRecord[] | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let flushing = false;

  const flush = async () => {
    timer = null;
    if (flushing || !pending) return;
    flushing = true;
    const records = pending;
    pending = null;
    try {
      revision = (await journalApi.put(revision, records)).revision;
      journal.setSyncOk(true);
    } catch (error) {
      if (error instanceof HttpError && error.status === 409) {
        const detail = (error.body as { detail?: { revision?: number; records?: DecisionRecord[] } } | null)?.detail;
        revision = detail?.revision ?? revision;
        journal.adoptServer(detail?.records ?? []);
      } else {
        journal.setSyncOk(false);
        pending = pending ?? records; // retried with the next change
      }
    } finally {
      flushing = false;
      if (pending && !timer) timer = setTimeout(() => void flush(), debounceMs);
    }
  };

  journal.bindAccount(person, initial.records as DecisionRecord[], (records) => {
    pending = records;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void flush(), debounceMs);
  });
  return async () => {
    if (timer) clearTimeout(timer);
    timer = null;
    await flush();
    journal.unbind();
  };
}
