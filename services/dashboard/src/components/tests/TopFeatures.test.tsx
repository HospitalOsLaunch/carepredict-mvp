import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TopFeatures } from "../TopFeatures";

describe("TopFeatures", () => {
  it("renders the three most influential features", () => {
    render(<TopFeatures features={["admissions_j0", "effectif_nuit", "sorties_programmees"]} />);

    expect(screen.getByText("admissions_j0")).toBeInTheDocument();
    expect(screen.getByText("effectif_nuit")).toBeInTheDocument();
    expect(screen.getByText("sorties_programmees")).toBeInTheDocument();
  });
});
