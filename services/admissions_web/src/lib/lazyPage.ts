import { lazy, type ComponentType, type LazyExoticComponent } from "react";

export type LazyPage = LazyExoticComponent<ComponentType<object>> & { preload: () => Promise<unknown> };

/**
 * A page loaded with its own JavaScript file, the first time it is opened (or earlier, with
 * `preload()`: on hover of its link, or when the browser is idle). A failed download is not
 * remembered, so the next attempt tries again (a Wi-Fi drop in a corridor).
 */
export function lazyPage<M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M): LazyPage {
  let pending: Promise<M> | null = null;
  const preload = () =>
    (pending ??= load().catch((e: unknown) => {
      pending = null;
      throw e;
    }));
  const Page = lazy(() => preload().then((m) => ({ default: m[name] as ComponentType<object> })));
  return Object.assign(Page, { preload });
}

/** Runs `work` when the browser has nothing else to do (soon after, where idle callbacks are missing). */
export function whenIdle(work: () => void): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const id = window.requestIdleCallback(work, { timeout: 4000 });
    return () => window.cancelIdleCallback(id);
  }
  const id = window.setTimeout(work, 1500);
  return () => window.clearTimeout(id);
}
