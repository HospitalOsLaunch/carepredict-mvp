import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { LegacyAgentsRedirect } from "../components/LegacyAgentsRedirect";

function Where() {
  const { pathname, search } = useLocation();
  return <p>{pathname + search}</p>;
}

function at(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/computer-use/*" element={<LegacyAgentsRedirect />} />
        <Route path="/agents/*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("former « Computer use » addresses", () => {
  it("lead to the Agents screen, a shared replay link included", () => {
    at("/computer-use");
    expect(screen.getByText("/agents")).toBeInTheDocument();
  });

  it("keep the replay of the passage they pointed to", () => {
    at("/computer-use/passages/82?x=1");
    expect(screen.getByText("/agents/passages/82?x=1")).toBeInTheDocument();
  });
});
