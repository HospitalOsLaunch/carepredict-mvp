import { Navigate, useLocation } from "react-router-dom";

/** « Computer use » is now « Agents »: former addresses (bookmarks, shared replay links) still lead there. */
export function LegacyAgentsRedirect() {
  const { pathname, search } = useLocation();
  return <Navigate to={pathname.replace(/^\/computer-use/, "/agents") + search} replace />;
}
