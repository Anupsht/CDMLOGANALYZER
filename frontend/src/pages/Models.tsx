import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { MachineModel } from "../types";

export default function Models() {
  const [models, setModels] = useState<MachineModel[]>([]);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .listModels()
      .then(setModels)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load models"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = async (model: MachineModel) => {
    setBusy(model.code);
    try {
      await api.toggleModel(model.code, !model.is_active);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-8 py-8">
      <header>
        <h1 className="text-2xl font-semibold text-white">Models</h1>
        <p className="mt-1 text-sm text-slate-400">
          Machine model registry. Adapters register dynamically — new models plug in without core changes.
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {models.map((model) => (
          <div
            key={model.code}
            className={`flex flex-col rounded-xl border p-5 ${
              model.is_active ? "border-slate-800 bg-slate-900/60" : "border-slate-800/60 bg-slate-900/30"
            }`}
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="font-mono text-lg font-semibold text-white">{model.code}</div>
                <div className="text-sm text-slate-400">{model.name}</div>
              </div>
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset ${
                  model.is_placeholder
                    ? "bg-slate-500/15 text-slate-400 ring-slate-500/40"
                    : model.is_active
                      ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40"
                      : "bg-amber-500/15 text-amber-300 ring-amber-500/40"
                }`}
              >
                {model.is_placeholder ? "placeholder" : model.is_active ? "active" : "disabled"}
              </span>
            </div>

            <p className="mt-3 flex-1 text-xs leading-relaxed text-slate-500">{model.description}</p>

            {model.supported_sources && model.supported_sources.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {model.supported_sources.map((src) => (
                  <span key={src} className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                    {src}
                  </span>
                ))}
              </div>
            )}

            <div className="mt-4 flex items-center justify-between border-t border-slate-800 pt-3">
              <span className="text-[11px] text-slate-500">
                {model.parser_code ? `parser: ${model.parser_code}` : "parser: pending (Phase 2)"}
              </span>
              <button
                disabled={busy === model.code}
                onClick={() => toggle(model)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:opacity-50 ${
                  model.is_active
                    ? "bg-slate-800 text-slate-300 hover:bg-slate-700"
                    : "bg-indigo-600 text-white hover:bg-indigo-500"
                }`}
              >
                {busy === model.code ? "…" : model.is_active ? "Disable" : "Enable"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
