import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, clearToken, getToken } from "../lib/api";

export interface Profile {
  id: number;
  name: string;
  email: string;
  experience_level: string;
  current_role: string;
  target_role: string;
  learning_goals: string;
  skills: Record<string, number>;
  voice: string;
  xp: number;
  streak: number;
}

interface AuthCtx {
  user: Profile | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx>({ user: null, loading: true, refresh: async () => {}, logout: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api<Profile>("/api/auth/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const logout = () => {
    clearToken();
    setUser(null);
    window.location.href = "/login";
  };

  return <Ctx.Provider value={{ user, loading, refresh, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
