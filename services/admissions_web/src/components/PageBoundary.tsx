import { RefreshCw } from "lucide-react";
import { Component, type ReactNode } from "react";

/** A page file that no longer exists (a new version was deployed) or could not be downloaded. */
export function isChunkError(error: unknown): boolean {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /dynamically imported module|Importing a module script failed|Failed to fetch|ChunkLoadError|error loading dynamically/i.test(text);
}

/**
 * Catches what goes wrong while a page renders, so the menu stays usable. The usual case, with
 * pages in their own files: the screen stayed open all day and a new version was deployed in
 * the meantime; reloading picks it up. `resetKey` (the address) clears the error on navigation.
 */
export class PageBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: unknown; key: string }> {
  state = { error: null as unknown, key: this.props.resetKey };

  static getDerivedStateFromError(error: unknown) {
    return { error };
  }

  static getDerivedStateFromProps(props: { resetKey: string }, state: { error: unknown; key: string }) {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }

  render() {
    if (!this.state.error) return this.props.children;
    const chunk = isChunkError(this.state.error);
    return (
      <div role="alert" className="panel mx-auto mt-6 max-w-lg p-6">
        <h2 className="text-[20px]">{chunk ? "Une nouvelle version d'HospitalOS est disponible" : "Cet écran n'a pas pu s'afficher"}</h2>
        <p className="mt-2 text-ink-soft">
          {chunk
            ? "Rechargez la page pour l'utiliser. Si le réseau vient de couper, rechargez quand il revient."
            : "Rechargez la page. Si cela se reproduit, signalez-le à l'administrateur du groupe."}
        </p>
        <button type="button" className="btn-primary mt-4" onClick={() => window.location.reload()}>
          <RefreshCw className="h-4 w-4" aria-hidden /> Recharger
        </button>
      </div>
    );
  }
}
