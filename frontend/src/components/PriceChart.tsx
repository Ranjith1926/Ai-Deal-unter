"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { formatDate, formatINR, platformName } from "@/lib/format";
import type { Envelope, PriceHistory } from "@/lib/types";
import { EmptyState, Notice } from "./States";

const RANGES = [30, 90, 180, 365];
const STYLES = [
  { color: "var(--chart-a)", dash: undefined as string | undefined, marker: "circle" },
  { color: "var(--chart-b)", dash: "7 5", marker: "square" },
  { color: "var(--accent)", dash: "2 4", marker: "diamond" },
];

interface Pt { t: number; price: number | null; low: number | null; high: number | null }

function niceTicks(min: number, max: number, count = 5): number[] {
  const span = max - min || max || 1;
  const rough = span / (count - 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? rough;
  const start = Math.floor(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 0.999; v += step) out.push(Math.round(v * 100) / 100);
  return out;
}

const compactINR = (v: number) => (v >= 100000 ? `₹${(v / 100000).toFixed(v % 100000 ? 1 : 0)}L` : v >= 1000 ? `₹${(v / 1000).toFixed(v % 1000 ? 1 : 0)}k` : `₹${v}`);

export function PriceChart({ productId, initial }: { productId: number; initial: PriceHistory }) {
  const [data, setData] = useState(initial);
  const [days, setDays] = useState(initial.days);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [announce, setAnnounce] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const uid = useId();

  // Lay the chart out at its real pixel width, so text stays a readable 12px on phones
  // instead of shrinking with the drawing.
  const [width, setWidth] = useState(800);
  useEffect(() => {
    const el = measureRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const W = Math.max(260, width - 16);
  const narrow = W < 560;
  const H = narrow ? 250 : 320;
  const M = useMemo(() => (narrow ? { l: 50, r: 14, t: 12, b: 30 } : { l: 62, r: 92, t: 14, b: 34 }), [narrow]);

  const series = useMemo(
    () => Object.entries(data.series).sort(([a], [b]) => a.localeCompare(b)).map(([platform, pts]) => ({
      platform,
      pts: pts.map<Pt>((p) => ({ t: new Date(p.t).getTime(), price: p.price, low: p.low, high: p.high })),
    })),
    [data],
  );
  const plotted = series.filter((s) => s.pts.filter((p) => p.price != null).length >= 2);

  const stats = data.stats ?? {};
  const refLow = typeof stats.historical_low === "string" || typeof stats.historical_low === "number" ? Number(stats.historical_low) : null;
  const ref30 = typeof stats.avg_30d === "string" || typeof stats.avg_30d === "number" ? Number(stats.avg_30d) : null;

  const geo = useMemo(() => {
    const times = plotted.flatMap((s) => s.pts.map((p) => p.t));
    if (times.length === 0) return null;
    const values = plotted.flatMap((s) => s.pts.flatMap((p) => [p.price, p.low, p.high])).filter((v): v is number => v != null);
    for (const r of [refLow, ref30]) if (r != null) values.push(r);
    const lo = Math.min(...values), hi = Math.max(...values);
    const pad = (hi - lo || hi * 0.1 || 1) * 0.1;
    const ticks = niceTicks(Math.max(0, lo - pad), hi + pad);
    const yMin = ticks[0], yMax = ticks[ticks.length - 1];
    const tMin = Math.min(...times), tMax = Math.max(...times);
    const x = (t: number) => M.l + ((t - tMin) / (tMax - tMin || 1)) * (W - M.l - M.r);
    const y = (v: number) => M.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (H - M.t - M.b);
    const timeline = [...new Set(times)].sort((a, b) => a - b);
    return { ticks, x, y, tMin, tMax, timeline };
  }, [plotted, refLow, ref30, W, H, M]);

  const load = useCallback(async (d: number) => {
    setDays(d);
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/bff/products/${productId}/prices?days=${d}`);
      const body = (await res.json()) as Envelope<PriceHistory>;
      if (!res.ok || !body.data) throw new Error(body.message ?? "Failed");
      setData(body.data);
      setCursor(null);
    } catch {
      setError("Couldn't load that range. Showing the previous one.");
    } finally {
      setLoading(false);
    }
  }, [productId]);

  const valueAt = useCallback((pts: Pt[], t: number): Pt | null => {
    let found: Pt | null = null;
    for (const p of pts) { if (p.t <= t) found = p; else break; }
    return found;
  }, []);

  const describe = useCallback((idx: number) => {
    if (!geo) return "";
    const t = geo.timeline[idx];
    const parts = plotted.map((s) => {
      const p = valueAt(s.pts, t);
      return `${platformName(s.platform)} ${p?.price != null ? formatINR(p.price) : "unavailable"}`;
    });
    return `${formatDate(new Date(t).toISOString(), { day: "numeric", month: "short", year: "numeric" })}: ${parts.join(", ")}`;
  }, [geo, plotted, valueAt]);

  function move(idx: number, speak: boolean) {
    if (!geo) return;
    const clamped = Math.max(0, Math.min(geo.timeline.length - 1, idx));
    setCursor(clamped);
    if (speak) setAnnounce(describe(clamped));
  }

  function onPointerMove(e: PointerEvent<SVGSVGElement>) {
    if (!geo) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const t = geo.tMin + ((px - M.l) / (W - M.l - M.r)) * (geo.tMax - geo.tMin);
    let best = 0;
    geo.timeline.forEach((tt, i) => { if (Math.abs(tt - t) < Math.abs(geo.timeline[best] - t)) best = i; });
    move(best, false);
  }

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!geo) return;
    const cur = cursor ?? geo.timeline.length - 1;
    const step = e.shiftKey ? 7 : 1;
    const map: Record<string, number | undefined> = { ArrowLeft: cur - step, ArrowRight: cur + step, Home: 0, End: geo.timeline.length - 1 };
    if (e.key === "Escape") { setCursor(null); setAnnounce(""); return; }
    if (map[e.key] !== undefined) { e.preventDefault(); move(map[e.key]!, true); }
  }

  const summary = useMemo(() => {
    if (plotted.length === 0) return "";
    return plotted.map((s) => {
      const priced = s.pts.filter((p) => p.price != null);
      const first = priced[0], last = priced[priced.length - 1];
      const lows = priced.map((p) => p.low ?? p.price!), highs = priced.map((p) => p.high ?? p.price!);
      return `${platformName(s.platform)}: ${formatINR(first.price)} on ${formatDate(new Date(first.t).toISOString())} to ${formatINR(last.price)} on ${formatDate(new Date(last.t).toISOString())}, lowest ${formatINR(Math.min(...lows))}, highest ${formatINR(Math.max(...highs))}`;
    }).join(". ");
  }, [plotted]);

  const noChart = !geo;
  const tooltip = geo && cursor != null ? { t: geo.timeline[cursor], left: (geo.x(geo.timeline[cursor]) / W) * 100 } : null;

  return (
    <div ref={measureRef}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Date range" className="flex flex-wrap gap-2">
          {RANGES.map((d) => (
            <button key={d} type="button" className="chip" aria-pressed={days === d} disabled={loading} onClick={() => load(d)}>{d} days</button>
          ))}
        </div>
        {plotted.length > 0 && (
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Chart legend">
            {plotted.map((s, i) => (
              <li key={s.platform} className="flex items-center gap-2">
                <svg width="28" height="10" aria-hidden="true"><line x1="0" y1="5" x2="28" y2="5" strokeWidth="3" strokeDasharray={STYLES[i % 3].dash} style={{ stroke: STYLES[i % 3].color }} /></svg>
                {platformName(s.platform)}
              </li>
            ))}
          </ul>
        )}
      </div>

      {!data.has_sufficient_history && <div className="mb-3"><Notice>{data.message ?? "Not enough historical data yet"}. Prices below are real observations; averages and deal scores appear once there is enough history.</Notice></div>}
      {error && <div className="mb-3" role="alert"><Notice tone="warn">{error}</Notice></div>}

      {noChart ? (
        <EmptyState title="Not enough historical data yet">
          We only draw a chart from real price observations, and we need at least two for a store before we can show a trend. Check back soon.
        </EmptyState>
      ) : (
        <div
          ref={wrapRef} tabIndex={0} onKeyDown={onKey} onFocus={() => cursor == null && move(geo.timeline.length - 1, true)} onBlur={() => setCursor(null)}
          className={`card relative p-2 ${loading ? "opacity-60" : ""}`} aria-busy={loading}
          aria-label={`Price history chart. ${summary}. Use left and right arrow keys to read values; hold Shift to move a week at a time.`}
          role="group"
        >
          <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full touch-pan-y text-muted" role="img" aria-labelledby={`${uid}-t`} onPointerMove={onPointerMove} onPointerLeave={() => setCursor(null)}>
            <title id={`${uid}-t`}>{`Price history over ${days} days. ${summary}`}</title>
            {geo.ticks.map((v) => (
              <g key={v}>
                <line x1={M.l} x2={W - M.r} y1={geo.y(v)} y2={geo.y(v)} style={{ stroke: "var(--chart-grid)" }} strokeWidth="1" />
                <text x={M.l - 8} y={geo.y(v) + 4} textAnchor="end" fontSize="12" fill="currentColor" className="tabular">{compactINR(v)}</text>
              </g>
            ))}
            {(narrow ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1]).map((f) => {
              const t = geo.tMin + f * (geo.tMax - geo.tMin);
              return <text key={f} x={geo.x(t)} y={H - 10} textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} fontSize="12" fill="currentColor">{formatDate(new Date(t).toISOString())}</text>;
            })}

            {refLow != null && (
              <g>
                <line x1={M.l} x2={W - M.r} y1={geo.y(refLow)} y2={geo.y(refLow)} strokeWidth="1.5" strokeDasharray="1 4" strokeLinecap="round" style={{ stroke: "var(--primary)" }} />
                <text x={M.l + 4} y={geo.y(refLow) - 5} fontSize="12" fontWeight="700" style={{ fill: "var(--primary)" }}>{narrow ? "Lowest" : "Lowest tracked"} {formatINR(refLow)}</text>
              </g>
            )}
            {ref30 != null && (
              <g>
                <line x1={M.l} x2={W - M.r} y1={geo.y(ref30)} y2={geo.y(ref30)} strokeWidth="1.5" strokeDasharray="10 3 2 3" style={{ stroke: "var(--muted)" }} />
                <text x={M.l + 4} y={geo.y(ref30) - 5} fontSize="12" fill="currentColor">{narrow ? "30-day avg" : "30-day average"} {formatINR(ref30)}</text>
              </g>
            )}

            {plotted.map((s, i) => {
              const st = STYLES[i % 3];
              const segs: Pt[][] = [];
              let cur: Pt[] = [];
              for (const p of s.pts) { if (p.price == null) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p); }
              if (cur.length) segs.push(cur);
              const last = segs.flat().at(-1)!;
              return (
                <g key={s.platform}>
                  {segs.map((seg, k) => (
                    <path key={k} d={seg.map((p, j) => `${j ? "L" : "M"}${geo.x(p.t).toFixed(1)} ${geo.y(p.price!).toFixed(1)}`).join("")}
                      fill="none" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={st.dash} style={{ stroke: st.color }} />
                  ))}
                  <Marker kind={st.marker} x={geo.x(last.t)} y={geo.y(last.price!)} color={st.color} />
                  {!narrow && (
                    <>
                      <text x={W - M.r + 8} y={geo.y(last.price!) + (i % 2 ? 14 : -2)} fontSize="12" fontWeight="700" style={{ fill: st.color }}>{platformName(s.platform)}</text>
                      <text x={W - M.r + 8} y={geo.y(last.price!) + (i % 2 ? 28 : 12)} fontSize="12" fill="currentColor" className="tabular">{formatINR(last.price)}</text>
                    </>
                  )}
                </g>
              );
            })}

            {tooltip && (
              <g>
                <line x1={geo.x(tooltip.t)} x2={geo.x(tooltip.t)} y1={M.t} y2={H - M.b} strokeWidth="1" style={{ stroke: "var(--fg)" }} opacity="0.5" />
                {plotted.map((s, i) => { const p = valueAt(s.pts, tooltip.t); return p?.price != null ? <Marker key={s.platform} kind={STYLES[i % 3].marker} x={geo.x(p.t)} y={geo.y(p.price)} color={STYLES[i % 3].color} big /> : null; })}
              </g>
            )}
          </svg>

          {tooltip && (
            <div className="pointer-events-none absolute top-3 z-10 rounded-lg border border-line bg-surface px-3 py-2 text-sm shadow-pop"
              style={{ left: `${Math.min(Math.max(tooltip.left, 14), 66)}%` }}>
              <p className="font-bold">{formatDate(new Date(tooltip.t).toISOString(), { day: "numeric", month: "short", year: "numeric" })}</p>
              {plotted.map((s, i) => { const p = valueAt(s.pts, tooltip.t); return (
                <p key={s.platform} className="tabular"><span style={{ color: STYLES[i % 3].color }} className="font-bold">{platformName(s.platform)}</span> {p?.price != null ? formatINR(p.price) : "unavailable"}</p>
              ); })}
            </div>
          )}
        </div>
      )}

      <p role="status" aria-live="polite" className="sr-only">{announce}</p>

      {!noChart && (
        <details className="mt-3">
          <summary className="inline-flex min-h-11 cursor-pointer items-center font-bold text-primary underline-offset-4 hover:underline">View data as a table</summary>
          <div className="relative mt-2 max-h-80 overflow-auto rounded-xl border border-line">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Price history by date and store</caption>
              <thead className="sticky top-0 bg-surface-2"><tr><th scope="col" className="px-3 py-2">Date</th>{plotted.map((s) => <th scope="col" key={s.platform} className="px-3 py-2">{platformName(s.platform)}</th>)}</tr></thead>
              <tbody>
                {[...geo.timeline].reverse().slice(0, 90).map((t) => (
                  <tr key={t} className="border-t border-line">
                    <th scope="row" className="px-3 py-1.5 font-semibold">{formatDate(new Date(t).toISOString(), { day: "numeric", month: "short", year: "numeric" })}</th>
                    {plotted.map((s) => { const p = valueAt(s.pts, t); return <td key={s.platform} className="px-3 py-1.5 tabular">{p?.price != null ? (p.low != null && p.high != null && p.low !== p.high ? `${formatINR(p.low)} – ${formatINR(p.high)}` : formatINR(p.price)) : "Unavailable"}</td>; })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function Marker({ kind, x, y, color, big = false }: { kind: string; x: number; y: number; color: string; big?: boolean }) {
  const r = big ? 6 : 4.5;
  const common = { style: { fill: "var(--surface)", stroke: color }, strokeWidth: 2.5 };
  if (kind === "square") return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} rx="1.5" {...common} />;
  if (kind === "diamond") return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} transform={`rotate(45 ${x} ${y})`} {...common} />;
  return <circle cx={x} cy={y} r={r} {...common} />;
}
