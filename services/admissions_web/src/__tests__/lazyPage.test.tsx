import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";

import { isChunkError, PageBoundary } from "../components/PageBoundary";
import { lazyPage } from "../lib/lazyPage";

function Hello() {
  return <p>Écran chargé</p>;
}

describe("lazyPage", () => {
  it("downloads the page once, however often it is preloaded, and renders it", async () => {
    const load = vi.fn(async () => ({ Hello }));
    const Page = lazyPage(load, "Hello");
    await Promise.all([Page.preload(), Page.preload()]);
    render(
      <Suspense fallback={<p>…</p>}>
        <Page />
      </Suspense>
    );
    expect(await screen.findByText("Écran chargé")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("tries again after a failed download (a Wi-Fi drop), instead of keeping the failure", async () => {
    const load = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch dynamically imported module")).mockResolvedValue({ Hello });
    const Page = lazyPage(load, "Hello");
    await expect(Page.preload()).rejects.toThrow();
    await expect(Page.preload()).resolves.toEqual({ Hello });
    expect(load).toHaveBeenCalledTimes(2);
  });
});

describe("PageBoundary", () => {
  function Broken({ error }: { error: Error }): never {
    throw error;
  }

  it("offers to reload when a page file is gone (new version deployed while the screen was open)", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <PageBoundary resetKey="/lits">
        <Broken error={new TypeError("Failed to fetch dynamically imported module: /assets/BedsPage-abc.js")} />
      </PageBoundary>
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Une nouvelle version d'HospitalOS est disponible");
    expect(screen.getByRole("button", { name: /Recharger/ })).toBeInTheDocument();
  });

  it("forgets the error when another screen is opened", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { rerender } = render(
      <PageBoundary resetKey="/lits">
        <Broken error={new Error("boom")} />
      </PageBoundary>
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Cet écran n'a pas pu s'afficher");
    rerender(
      <PageBoundary resetKey="/urgences">
        <p>Urgences</p>
      </PageBoundary>
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Urgences")).toBeInTheDocument();
  });

  it("tells a missing page file from another error", () => {
    expect(isChunkError(new TypeError("Importing a module script failed."))).toBe(true);
    expect(isChunkError(new Error("Cannot read properties of undefined"))).toBe(false);
  });
});
