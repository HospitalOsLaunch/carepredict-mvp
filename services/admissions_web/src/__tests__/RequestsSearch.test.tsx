import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { RequestsPage } from "../pages/RequestsPage";

vi.mock("../api/client", () => ({ api: vi.fn() }));
vi.mock("../auth", () => ({ useAuth: () => ({ canWrite: false, isAdmin: false }) }));
import { api } from "../api/client";

const searches = () =>
  vi
    .mocked(api)
    .mock.calls.map(([path]) => String(path))
    .filter((p) => p.startsWith("/requests?") && p.includes("q="));

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(((path: string) => Promise.resolve(path.startsWith("/requests") ? [] : path === "/vocabulary" ? { mentions: {} } : [])) as never);
});
afterEach(() => vi.useRealTimers());

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RequestsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("search of the requests", () => {
  it("asks the server once, after the typing pauses, not at every letter", async () => {
    renderPage();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const box = screen.getByPlaceholderText("Patient, adresseur ou référence");
    await user.type(box, "Martin");
    expect(box).toHaveValue("Martin"); // the field follows the keyboard at once
    expect(searches()).toEqual([]);
    await act(async () => {
      vi.advanceTimersByTime(350);
    });
    expect(searches()).toEqual(["/requests?scope=a_traiter&q=Martin"]);
  });

  it("clears the search at once when the field is emptied", async () => {
    renderPage();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const box = screen.getByPlaceholderText("Patient, adresseur ou référence");
    await user.type(box, "Dupont");
    await act(async () => {
      vi.advanceTimersByTime(350);
    });
    vi.mocked(api).mockClear();
    await user.clear(box);
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    expect(vi.mocked(api).mock.calls.map(([p]) => String(p))).toContain("/requests?scope=a_traiter");
  });
});
