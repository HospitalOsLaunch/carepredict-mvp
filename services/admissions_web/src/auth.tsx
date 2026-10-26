import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, getToken, setToken, setUnauthorizedHandler } from "./api/client";
import type { LoginResponse, User } from "./api/types";

interface AuthState {
  user: User | null;
  groupName: string;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  /** Message from a failed identity-provider sign-in, shown on the login page. */
  oidcError: string | null;
  logout: () => void;
  canWrite: boolean;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [groupName, setGroupName] = useState("");
  const [ready, setReady] = useState(false);
  const [oidcError, setOidcError] = useState<string | null>(null);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      queryClient.clear();
    });
    // Back from the identity provider: the session token (or the error) is in the URL fragment,
    // which never reaches a server log. Take it and wipe it from the address bar at once.
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const fromProvider = fragment.get("oidc_token");
    const providerError = fragment.get("oidc_error");
    if (fromProvider || providerError) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      if (fromProvider) setToken(fromProvider);
      if (providerError) setOidcError(providerError);
    }
    if (!getToken()) {
      setReady(true);
      return;
    }
    api<LoginResponse>("/auth/me")
      .then((me) => {
        setUser(me.user);
        setGroupName(me.group_name);
      })
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, [queryClient]);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api<LoginResponse>("/auth/login", { method: "POST", json: { email, password } });
    setToken(result.token);
    setUser(result.user);
    setGroupName(result.group_name);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      groupName,
      ready,
      login,
      oidcError,
      logout,
      canWrite: user?.role === "admin_groupe" || user?.role === "coordination",
      isAdmin: user?.role === "admin_groupe"
    }),
    [user, groupName, ready, login, oidcError, logout]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
