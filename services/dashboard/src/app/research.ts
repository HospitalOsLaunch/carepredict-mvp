/**
 * Research mode is the safe default for the usability build. A live mode can
 * only be selected explicitly by setting VITE_RESEARCH_MODE=false.
 */
export function isResearchMode(): boolean {
  return import.meta.env.VITE_RESEARCH_MODE !== "false";
}
