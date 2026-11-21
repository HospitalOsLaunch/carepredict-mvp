import { createContext, useContext, type AnchorHTMLAttributes, type MouseEvent } from "react";

type PatientView = "unite" | "action" | "journal" | "donnees";
export type { PatientView };

export const PatientNavigation = createContext<{
  view: PatientView;
  selectRecord: (id: string | null) => void;
} | null>(null);

const destinations: Record<string, string> = {
  "#/dossiers": "#/",
  "#/dossiers/donnees": "#/donnees",
  "#/dossiers/proposition": "#/action",
  "#/dossiers/journal": "#/journal",
};

/** Keep the selected patient source across workspace tabs and preserve portable record URLs. */
export function PatientLink({ href, onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const navigation = useContext(PatientNavigation);
  if (!navigation || !href) return <a href={href} onClick={onClick} {...props} />;
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (navigation.view === "journal" && href.startsWith("#/dossiers/journal/")) {
      event.preventDefault();
      navigation.selectRecord(decodeURIComponent(href.slice("#/dossiers/journal/".length)));
    } else if (navigation.view === "journal" && href === "#/dossiers/journal") {
      event.preventDefault();
      navigation.selectRecord(null);
    } else if (navigation.view === "action" && href === "#/dossiers/proposition") {
      const details = document.getElementById("patient-action-detail");
      if (details instanceof HTMLDetailsElement) {
        event.preventDefault();
        details.open = true;
        details.querySelector("summary")?.focus();
        details.scrollIntoView({ block: "start" });
      }
    }
  };
  return <a {...props} href={destinations[href] ?? href} onClick={follow} />;
}
