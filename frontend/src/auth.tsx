// Phase 10 — client-side authentication context.
// The BACKEND is the enforcement point; this mirrors the RBAC matrix from
// app/core/rbac.py purely for navigation/UI hints (hiding what a role
// cannot do — never a security boundary).

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

const TOKEN_KEY = "cdm_token";
const USER_KEY = "cdm_user";

export type Role =
  | "ADMIN"
  | "TECHNICIAN"
  | "SUPERVISOR"
  | "ANALYST"
  | "VIEWER";

export interface AuthUser {
  id: string;
  username: string;
  full_name?: string | null;
  role: Role;
  is_active: boolean;
}

// permission → roles (mirror of backend app/core/rbac.py)
const PERMISSIONS: Record<string, Role[]> = {
  "logs:upload": ["ADMIN", "TECHNICIAN"],
  "analysis:run": ["ADMIN", "TECHNICIAN", "ANALYST"],
  "reports:generate": ["ADMIN", "TECHNICIAN", "SUPERVISOR"],
  "cases:create": ["ADMIN", "TECHNICIAN"],
  "cases:update": ["ADMIN", "TECHNICIAN", "SUPERVISOR"],
  "machines:write": ["ADMIN", "TECHNICIAN"],
  "analytics:read": ["ADMIN", "SUPERVISOR", "ANALYST"],
  "rules:suggest": ["ADMIN", "SUPERVISOR", "ANALYST"],
  "rules:review": ["ADMIN", "SUPERVISOR"],
  "audit:read": ["ADMIN", "SUPERVISOR"],
  "models:write": ["ADMIN"],
  "users:manage": ["ADMIN"],
};

export function can(role: Role | undefined, permission: string): boolean {
  if (!role) return false;
  return PERMISSIONS[permission]?.includes(role) ?? true; // unknown perms = read surfaces (all roles)
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  login: (token: string, user: AuthUser) => void;
  logout: () => void;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState>({
  token: null,
  user: null,
  login: () => undefined,
  logout: () => undefined,
  can: () => false,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<AuthUser | null>(() => {
    try {
      const raw = localStorage.getItem(USER_KEY);
      return raw ? (JSON.parse(raw) as AuthUser) : null;
    } catch {
      return null;
    }
  });

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  }, []);

  const login = useCallback((newToken: string, newUser: AuthUser) => {
    localStorage.setItem(TOKEN_KEY, newToken);
    localStorage.setItem(USER_KEY, JSON.stringify(newUser));
    setToken(newToken);
    setUser(newUser);
  }, []);

  // tokens have a server-side TTL — drop stale state on boot
  useEffect(() => {
    if (!token) return;
    void fetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } }).then((r) => {
      if (r.status === 401) logout();
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const value = useMemo<AuthState>(
    () => ({
      token,
      user,
      login,
      logout,
      can: (permission: string) => can(user?.role, permission),
    }),
    [token, user, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
