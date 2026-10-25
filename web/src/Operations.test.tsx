import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useOperations } from "./data/useOperations";
import { operationsApi, type Workplace } from "./api/operations";
const state: Workplace = {
  schema_version: "WORKPLACE_1",
  hospital_id: "H1",
  now: "2026-10-25T10:00:00Z",
  revision: 4,
  tokens: { geriatrie: "v4" },
  staff: [],
  patients: [],
  discharges: [],
  admissions: [],
  constraints: [],
  tasks: [],
  events: [],
  forecasts: [],
};
function Harness() {
  const ops = useOperations(true, () => undefined);
  return (
    <>
      <span>{ops.data?.revision}</span>
      <p>{ops.error}</p>
      <button
        onClick={() =>
          ops.submit({
            kind: "documents",
            unit_id: "geriatrie",
            patient_id: "P1",
          })
        }
      >
        Demander
      </button>
      <button onClick={ops.refresh}>Actualiser</button>
      {ops.retry ? <button onClick={ops.retry}>Réessayer</button> : null}
    </>
  );
}
afterEach(() => vi.restoreAllMocks());
it("keeps an ambiguous command retryable after successful polling and reuses its identity", async () => {
  vi.spyOn(operationsApi, "read").mockResolvedValue(state);
  const submit = vi
    .spyOn(operationsApi, "submit")
    .mockRejectedValueOnce(new Error("network lost"))
    .mockResolvedValue({ ...state, revision: 5 });
  render(<Harness />);
  await screen.findByText("4");
  fireEvent.click(screen.getByText("Demander"));
  await screen.findByText("Réessayer");
  fireEvent.click(screen.getByText("Actualiser"));
  await waitFor(() => expect(operationsApi.read).toHaveBeenCalledTimes(2));
  expect(screen.getByText(/Réponse non reçue/)).toBeTruthy();
  fireEvent.click(screen.getByText("Demander"));
  expect(submit).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByText("Réessayer"));
  await screen.findByText("5");
  expect(submit.mock.calls[1]?.[0]).toEqual(submit.mock.calls[0]?.[0]);
  expect(screen.queryByText("Réessayer")).toBeNull();
});
it("ignores a read started before a successful mutation", async () => {
  let release: (value: Workplace) => void = () => undefined;
  vi.spyOn(operationsApi, "read")
    .mockResolvedValueOnce(state)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
  vi.spyOn(operationsApi, "submit").mockResolvedValue({
    ...state,
    revision: 5,
  });
  render(<Harness />);
  await screen.findByText("4");
  fireEvent.click(screen.getByText("Actualiser"));
  fireEvent.click(screen.getByText("Demander"));
  await screen.findByText("5");
  await act(async () => release(state));
  expect(screen.queryByText("4")).toBeNull();
  expect(screen.getByText("5")).toBeTruthy();
});
