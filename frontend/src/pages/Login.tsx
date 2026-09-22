import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth";
import { Badge, Card, ErrorBox } from "../components/ui";

const DEMO = [
  ["admin", "Admin#12345", "full access"],
  ["technician", "Tech#12345", "upload · analyze · cases · reports"],
  ["supervisor", "Super#12345", "review · approve · analytics"],
  ["analyst", "Analyst#12345", "analysis · history"],
  ["viewer", "Viewer#12345", "read-only"],
];

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const out = await api.login(username.trim(), password);
      login(out.token, out.user as never);
      navigate((location.state as { from?: string } | null)?.from ?? "/", { replace: true });
    } catch (err) {
      setError((err as Error).message || "Login failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-slate-950 px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-indigo-600 text-xl font-bold text-white">
            C
          </div>
          <div>
            <div className="text-lg font-semibold text-white">CDM Log Analyzer</div>
            <div className="text-xs text-slate-500">Universal GRG · secure technician console</div>
          </div>
        </div>
        <Card title="Sign in" subtitle="your session expires automatically; failed logins lock the account">
          <form onSubmit={submit} className="space-y-3">
            {error && <ErrorBox message={error} />}
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Username</label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500"
              />
            </div>
            <button
              type="submit"
              disabled={busy || !username || !password}
              className="w-full rounded bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </Card>
        <div className="mt-4 rounded-lg border border-slate-800 bg-slate-900/40 p-3">
          <div className="mb-2 text-[11px] uppercase tracking-wide text-slate-500">
            Demo accounts (development seeding)
          </div>
          <div className="space-y-1 text-xs">
            {DEMO.map(([u, p, desc]) => (
              <button
                key={u}
                onClick={() => {
                  setUsername(u);
                  setPassword(p);
                }}
                className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left hover:bg-slate-800/60"
              >
                <Badge tone="slate">{u}</Badge>
                <span className="font-mono text-[11px] text-slate-400">{p}</span>
                <span className="ml-auto text-[11px] text-slate-600">{desc}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
