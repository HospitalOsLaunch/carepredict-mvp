import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CurrentVsPredicted } from "../CurrentVsPredicted";

describe("CurrentVsPredicted", () => {
  it("shows current and predicted charges", () => {
    render(<CurrentVsPredicted current={42} predicted={51} />);

    expect(screen.getByText("Charge actuelle")).toBeInTheDocument();
    expect(screen.getByText("Prédiction J+12h")).toBeInTheDocument();
    expect(screen.getByText("+9.0 pts · hausse")).toBeInTheDocument();
  });
});
