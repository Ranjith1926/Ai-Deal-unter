"use client";

import { Loader2, Play, Power, RefreshCw } from "lucide-react";
import { useState } from "react";
import { flashAndReload } from "./Flash";

export type Say = (ok: boolean, text: string) => void;

/** POST/PUT/PATCH/DELETE to the admin API through the same-origin proxy; returns the parsed envelope. */
export async function adminCall(method: string, path: string, body?: unknown) {
  const res = await fetch(`/bff/admin/${path}`, {
    method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).catch(() => null);
  const json = await res?.json().catch(() => null);
  return { ok: !!res?.ok, status: res?.status ?? 0, json };
}

export function errorText(r: { json: { message?: string; errors?: string[] } | null }, fallback = "That didn't work. Please try again."): string {
  return r.json?.errors?.length ? `${r.json.message ?? "Error"}: ${r.json.errors.join("; ")}` : r.json?.message ?? fallback;
}

export function StatusLine({ state }: { state: { ok: boolean; text: string } | null }) {
  return <p role="status" aria-live="polite" className={`min-h-6 text-sm font-semibold ${state?.ok ? "text-fg" : "text-danger"}`}>{state?.text}</p>;
}

/** Enable/disable switch plus manual sync buttons for one provider. */
export function ProviderControls({ name, enabled }: { name: string; enabled: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);
  const title = name.charAt(0).toUpperCase() + name.slice(1);

  async function run(key: string, fn: () => Promise<{ ok: boolean; json: any; status: number }>, success: string) {
    setBusy(key); setState(null);
    const r = await fn();
    if (r.ok) { flashAndReload(success); return; }
    setBusy(null);
    setState({ ok: false, text: errorText(r) });
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button type="button" role="switch" aria-checked={enabled} disabled={busy !== null} className={`btn btn-sm ${enabled ? "btn-outline" : "btn-primary"}`}
          onClick={() => run("toggle", () => adminCall("PUT", `providers/${name}`, { enabled: !enabled }), `${title} ${enabled ? "disabled" : "enabled"}.`)}>
          {busy === "toggle" ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Power size={16} aria-hidden="true" />}
          {enabled ? "Disable" : "Enable"}<span className="sr-only"> {title}</span>
        </button>
        <button type="button" disabled={busy !== null || !enabled} className="btn btn-outline btn-sm"
          onClick={() => run("sync", () => adminCall("POST", "jobs/trigger", { job: "sync_catalog", provider: name }), "Catalogue sync queued.")}>
          {busy === "sync" ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={16} aria-hidden="true" />} Sync catalogue<span className="sr-only"> for {title}</span>
        </button>
        <button type="button" disabled={busy !== null || !enabled} className="btn btn-outline btn-sm"
          onClick={() => run("prices", () => adminCall("POST", "jobs/trigger", { job: "collect_prices", provider: name }), "Price collection queued.")}>
          {busy === "prices" ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Play size={16} aria-hidden="true" />} Collect prices<span className="sr-only"> for {title}</span>
        </button>
      </div>
      <StatusLine state={state} />
    </div>
  );
}

const JOBS: { job: string; label: string; hint: string }[] = [
  { job: "recalculate_scores", label: "Recalculate scores", hint: "Recompute every deal and value score now." },
  { job: "update_rankings", label: "Refresh rankings", hint: "Rebuild the cached best-deal lists." },
  { job: "process_alerts", label: "Check price alerts", hint: "Look for alerts that have reached their target." },
  { job: "send_notifications", label: "Send notifications", hint: "Deliver queued email, push and Telegram messages now." },
  { job: "run_pipeline", label: "Run full pipeline", hint: "Collect prices from every provider, then score and rank." },
];

export function JobButtons() {
  const [busy, setBusy] = useState<string | null>(null);
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);

  async function trigger(job: string, label: string) {
    setBusy(job); setState(null);
    const r = await adminCall("POST", "jobs/trigger", { job });
    setBusy(null);
    setState({ ok: r.ok, text: r.ok ? `${label} queued. It runs in the background; check Jobs for the result.` : errorText(r) });
  }

  return (
    <div className="space-y-3">
      <ul className="grid gap-3 sm:grid-cols-2">
        {JOBS.map((j) => (
          <li key={j.job} className="flex items-start justify-between gap-3 rounded-xl border border-line p-3">
            <div className="min-w-0"><p className="font-bold">{j.label}</p><p className="text-sm text-muted">{j.hint}</p></div>
            <button type="button" className="btn btn-outline btn-sm shrink-0" disabled={busy !== null} onClick={() => trigger(j.job, j.label)}>
              {busy === j.job ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Play size={16} aria-hidden="true" />} Run<span className="sr-only"> {j.label}</span>
            </button>
          </li>
        ))}
      </ul>
      <StatusLine state={state} />
    </div>
  );
}
