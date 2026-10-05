"use client";

import { Loader2, RotateCcw, Save } from "lucide-react";
import { useMemo, useState } from "react";
import { adminCall, errorText, StatusLine } from "./AdminControls";
import { flashAndReload } from "./Flash";
import type { ScoringState } from "@/lib/types";

const DEAL_LABELS: Record<string, string> = {
  historical_advantage: "Price vs typical price", recent_drop: "Recent price drop", distance_from_low: "Closeness to lowest price",
  product_quality: "Ratings & reviews", seller_reliability: "Seller reliability", available_offers: "Available offers", price_stability: "Price stability",
};
const VALUE_LABELS: Record<string, string> = { spec_value: "Performance per rupee", quality: "Ratings & reviews", historical_pricing: "Price vs its history" };
const THRESHOLDS: [string, string][] = [["exceptional", "Exceptional deal from"], ["great", "Great deal from"], ["good", "Good deal from"], ["average", "Average from"]];

const pct = (v: number) => Math.round(v * 10000) / 100;

function NumberField({ id, label, value, onChange, suffix, step = 1 }: { id: string; label: string; value: string; onChange: (v: string) => void; suffix: string; step?: number }) {
  return (
    <div>
      <label htmlFor={id} className="label">{label}</label>
      <div className="flex items-center gap-2">
        <input id={id} type="number" inputMode="decimal" min={0} max={100} step={step} value={value} onChange={(e) => onChange(e.target.value)} className="input max-w-32 tabular" />
        <span className="text-muted" aria-hidden="true">{suffix}</span>
      </div>
    </div>
  );
}

export function ScoringEditor({ state }: { state: ScoringState }) {
  const eff = state.effective;
  const [deal, setDeal] = useState(() => Object.fromEntries(Object.entries(eff.deal.weights).map(([k, v]) => [k, String(pct(v))])));
  const [value, setValue] = useState(() => Object.fromEntries(Object.entries(eff.value.weights).map(([k, v]) => [k, String(pct(v))])));
  const [thr, setThr] = useState(() => Object.fromEntries(Object.entries(eff.deal.thresholds).map(([k, v]) => [k, String(v)])));
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  const sum = (m: Record<string, string>) => Math.round(Object.values(m).reduce((a, b) => a + (Number(b) || 0), 0) * 100) / 100;
  const dealSum = useMemo(() => sum(deal), [deal]);
  const valueSum = useMemo(() => sum(value), [value]);
  const t = (k: string) => Number(thr[k]);
  const thresholdsOk = t("average") >= 0 && t("average") < t("good") && t("good") < t("great") && t("great") < t("exceptional") && t("exceptional") <= 100;
  const valid = dealSum === 100 && valueSum === 100 && thresholdsOk;

  function overrides() {
    const frac = (m: Record<string, string>) => Object.fromEntries(Object.entries(m).map(([k, v]) => [k, Math.round(Number(v) * 100) / 10000]));
    const existing = state.overrides as { deal?: Record<string, unknown>; value?: Record<string, unknown> };
    return {
      ...state.overrides,
      deal: { ...existing.deal, weights: frac(deal), thresholds: Object.fromEntries(Object.entries(thr).map(([k, v]) => [k, Number(v)])) },
      value: { ...existing.value, weights: frac(value) },
    };
  }

  async function save(recalculate: boolean) {
    setBusy(recalculate ? "both" : "save"); setStatus(null);
    const r = await adminCall("PUT", "scoring", { overrides: overrides() });
    if (!r.ok) { setBusy(null); setStatus({ ok: false, text: errorText(r) }); return; }
    if (recalculate) {
      const j = await adminCall("POST", "jobs/trigger", { job: "recalculate_scores" });
      flashAndReload(j.ok ? "Saved. Scores are being recalculated in the background." : `Saved, but could not start the recalculation: ${errorText(j)}`);
    } else {
      flashAndReload("Saved. Scores use these settings the next time they are calculated (within 30 minutes), or run a recalculation now.");
    }
  }

  async function reset() {
    setBusy("reset"); setStatus(null);
    const r = await adminCall("DELETE", "scoring");
    if (r.ok) { flashAndReload("Reset to the defaults."); return; }
    setBusy(null);
    setStatus({ ok: false, text: errorText(r) });
  }

  const SumNote = ({ total, id }: { total: number; id: string }) => (
    <p id={id} className={`text-sm font-bold ${total === 100 ? "text-fg" : "text-danger"}`} role="status">
      Total: {total}% {total === 100 ? "✓" : `— must equal 100% (${total > 100 ? "reduce" : "add"} ${Math.abs(Math.round((100 - total) * 100) / 100)}%)`}
    </p>
  );

  return (
    <div className="space-y-8">
      <p className={`rounded-xl px-4 py-2 text-sm font-semibold ${state.customised ? "bg-warn-soft text-warn-fg" : "bg-surface-2"}`}>
        {state.customised ? "Custom settings are active." : "Using the default settings."}
      </p>

      <fieldset className="card space-y-4 p-5">
        <legend className="px-1 text-xl font-bold">Deal score weights</legend>
        <p className="text-muted">How much each signal counts toward the 0–100 deal score. The seller&apos;s advertised discount is never part of it.</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Object.keys(deal).map((k) => <NumberField key={k} id={`dw-${k}`} label={DEAL_LABELS[k] ?? k} value={deal[k]} suffix="%" step={0.5} onChange={(v) => setDeal((s) => ({ ...s, [k]: v }))} />)}
        </div>
        <SumNote total={dealSum} id="deal-sum" />
      </fieldset>

      <fieldset className="card space-y-4 p-5">
        <legend className="px-1 text-xl font-bold">Deal rating thresholds</legend>
        <p className="text-muted">The score needed for each label. Each must be higher than the one below it.</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {THRESHOLDS.map(([k, label]) => <NumberField key={k} id={`th-${k}`} label={label} value={thr[k]} suffix="/ 100" onChange={(v) => setThr((s) => ({ ...s, [k]: v }))} />)}
        </div>
        {!thresholdsOk && <p className="text-sm font-bold text-danger" role="alert">Thresholds must run exceptional &gt; great &gt; good &gt; average, between 0 and 100.</p>}
      </fieldset>

      <fieldset className="card space-y-4 p-5">
        <legend className="px-1 text-xl font-bold">Value score weights</legend>
        <div className="grid gap-4 sm:grid-cols-3">
          {Object.keys(value).map((k) => <NumberField key={k} id={`vw-${k}`} label={VALUE_LABELS[k] ?? k} value={value[k]} suffix="%" step={0.5} onChange={(v) => setValue((s) => ({ ...s, [k]: v }))} />)}
        </div>
        <SumNote total={valueSum} id="value-sum" />
      </fieldset>

      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={!valid || busy !== null} className="btn btn-primary" onClick={() => save(false)}>
          {busy === "save" ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Save size={16} aria-hidden="true" />} Save
        </button>
        <button type="button" disabled={!valid || busy !== null} className="btn btn-accent" onClick={() => save(true)}>
          {busy === "both" ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Save size={16} aria-hidden="true" />} Save &amp; recalculate scores
        </button>
        <button type="button" disabled={!state.customised || busy !== null} className="btn btn-outline" onClick={reset}>
          {busy === "reset" ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <RotateCcw size={16} aria-hidden="true" />} Reset to defaults
        </button>
      </div>
      <StatusLine state={status} />
    </div>
  );
}
