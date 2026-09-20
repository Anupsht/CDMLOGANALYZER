import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import type { Health } from "../types";

const NAV = [
  { to: "/", label: "Dashboard", icon: "◧" },
  { to: "/logs", label: "Logs", icon: "▤" },
  { to: "/models", label: "Models", icon: "⛭" },
  { to: "/machines", label: "Machines", icon: "🏧" },
];

export default function Layout() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .health()
        .then((h) => !cancelled && setHealth(h))
        .catch(() => !cancelled && setHealth(null));
    load();
    const timer = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-800 bg-slate-900/60">
        <div className="flex items-center gap-3 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-indigo-600 text-lg font-bold text-white">
            C
          </div>
          <div>
            <div className="text-sm font-semibold text-white">CDM Log Analyzer</div>
            <div className="text-[11px] text-slate-400">Universal GRG · Phase 1</div>
          </div>
        </div>
        <nav className="mt-2 flex-1 space-y-1 px-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                  isActive
                    ? "bg-indigo-600/20 font-medium text-indigo-300"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                }`
              }
            >
              <span className="w-4 text-center opacity-70">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-800 px-5 py-4 text-[11px] text-slate-500">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                health?.status === "ok" ? "bg-emerald-500" : "bg-rose-500"
              }`}
            />
            <span className="text-slate-400">
              {health ? `${health.status} · db ${health.database ? "up" : "down"} · ${health.queue}` : "backend unreachable"}
            </span>
          </div>
          {health && <div className="mt-1 text-slate-600">{health.version} · {health.environment}</div>}
        </div>
      </aside>

      {/* Content */}
      <main className="flex-1 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  );
}
