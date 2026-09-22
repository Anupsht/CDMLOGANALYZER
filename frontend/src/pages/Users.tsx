// Phase 10 — ADMIN user administration.

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Role, UserAccount } from "../types";
import { Badge, Card, ErrorBox, Spinner, fmtTime } from "../components/ui";
import { useAuth } from "../auth";

const ROLES: Role[] = ["ADMIN", "TECHNICIAN", "SUPERVISOR", "ANALYST", "VIEWER"];
const ROLE_TONE: Record<Role, string> = {
  ADMIN: "rose",
  SUPERVISOR: "amber",
  TECHNICIAN: "sky",
  ANALYST: "violet",
  VIEWER: "slate",
};

export default function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("VIEWER");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setUsers(await api.listUsers());
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setNote("");
    try {
      await api.createUser({ username: username.trim(), password, role });
      setUsername("");
      setPassword("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const act = async (fn: () => Promise<unknown>, okMessage?: string) => {
    setNote("");
    try {
      await fn();
      if (okMessage) setNote(okMessage);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const resetPassword = (u: UserAccount) => {
    const newPassword = window.prompt(`New password for ${u.username} (policy: ≥10 chars, mixed case + digit):`);
    if (!newPassword) return;
    void act(() => api.resetUserPassword(u.id, newPassword), `Password reset for ${u.username}.`);
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-white">User administration</h1>
        <p className="mt-1 text-xs text-slate-500">
          ADMIN only. Passwords are stored as salted PBKDF2 hashes — never in plaintext.
        </p>
      </header>
      {error && <div className="mb-4"><ErrorBox message={error} /></div>}
      {note && <div className="mb-4 rounded border border-emerald-900 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-300">{note}</div>}

      <Card title="Create user" subtitle="role decides permissions (least privilege)">
        <form onSubmit={create} className="grid gap-2 md:grid-cols-[1fr_1fr_auto_auto]">
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="username"
            autoComplete="off"
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="initial password"
            autoComplete="new-password"
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-200"
          >
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
          <button
            type="submit"
            disabled={!username.trim() || !password}
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
          >
            Create
          </button>
        </form>
      </Card>

      <div className="mt-4">
        {loading ? <Spinner /> : (
          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-xs">
              <thead className="bg-slate-900/60">
                <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">User</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Last login</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-t border-slate-800/60">
                    <td className="px-3 py-2">
                      <span className="font-mono text-slate-200">{u.username}</span>
                      {u.full_name && <div className="text-[10px] text-slate-600">{u.full_name}</div>}
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={u.role}
                        disabled={u.username === me?.username}
                        onChange={(e) => void act(() => api.updateUser(u.id, { role: e.target.value }))}
                        className="rounded border border-slate-700 bg-slate-950 px-1 py-0.5 text-[11px] text-slate-300 disabled:opacity-50"
                      >
                        {ROLES.map((r) => <option key={r}>{r}</option>)}
                      </select>{" "}
                      <Badge tone={ROLE_TONE[u.role]}>{u.role}</Badge>
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={u.is_active ? "emerald" : "rose"}>{u.is_active ? "active" : "disabled"}</Badge>
                    </td>
                    <td className="px-3 py-2 text-slate-500">{u.last_login_at ? fmtTime(u.last_login_at) : "never"}</td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-1">
                        <button
                          onClick={() => resetPassword(u)}
                          className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800"
                        >
                          Reset password
                        </button>
                        {u.username !== me?.username && (
                          <button
                            onClick={() => void act(() => api.updateUser(u.id, { is_active: !u.is_active }))}
                            className={`rounded border px-2 py-0.5 text-[11px] hover:bg-slate-800 ${
                              u.is_active ? "border-rose-900 text-rose-300" : "border-emerald-800 text-emerald-300"
                            }`}
                          >
                            {u.is_active ? "Disable" : "Enable"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
