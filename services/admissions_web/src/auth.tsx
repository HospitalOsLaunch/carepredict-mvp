import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, getToken, setToken, setUnauthorizedHandler } from "./api/client";
import type { LoginResponse, User } from "./api/types";

interface AuthState {
  user: User | null;
  groupName: string;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
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
      logout,
      canWrite: user?.role === "admin_groupe" || user?.role === "coordination",
      isAdmin: user?.role === "admin_groupe"
    }),
    [user, groupName, ready, login, logout]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
