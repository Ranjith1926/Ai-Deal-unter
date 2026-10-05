"use client";

import { GitCompareArrows, X } from "lucide-react";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

const KEY = "dh_compare";
const MAX = 3;

interface CompareCtx { ids: number[]; toggle: (id: number) => void; clear: () => void; has: (id: number) => boolean; full: boolean }
const Ctx = createContext<CompareCtx | null>(null);

export function CompareProvider({ children }: { children: ReactNode }) {
  const [ids, setIds] = useState<number[]>([]);

  useEffect(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]");
      if (Array.isArray(raw)) setIds(raw.filter((n) => Number.isInteger(n)).slice(0, MAX));
    } catch { /* storage unavailable or corrupt: start empty */ }
  }, []);

  const persist = useCallback((next: number[]) => {
    setIds(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* ignore */ }
  }, []);

  const value = useMemo<CompareCtx>(() => ({
    ids,
    has: (id) => ids.includes(id),
    full: ids.length >= MAX,
    toggle: (id) => persist(ids.includes(id) ? ids.filter((x) => x !== id) : ids.length >= MAX ? ids : [...ids, id]),
    clear: () => persist([]),
  }), [ids, persist]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

function useCompare(): CompareCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("CompareProvider missing");
  return ctx;
}

export function CompareToggle({ productId, name }: { productId: number; name: string }) {
  const { has, toggle, full } = useCompare();
  const selected = has(productId);
  const disabled = !selected && full;
  return (
    <button
      type="button" className="chip" aria-pressed={selected} disabled={disabled}
      title={disabled ? `You can compare up to ${MAX} products` : undefined}
      onClick={() => toggle(productId)}
    >
      <GitCompareArrows size={16} aria-hidden="true" />
      {selected ? "Added" : "Compare"}
      <span className="sr-only"> {name}</span>
    </button>
  );
}

/** Floating tray that appears once something is selected. */
export function CompareTray() {
  const { ids, clear } = useCompare();
  if (ids.length === 0) return null;
  return (
    <div role="region" aria-label="Product comparison" className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface p-3 shadow-pop">
      <div className="container-page flex flex-wrap items-center justify-between gap-3">
        <p className="font-bold" aria-live="polite">{ids.length} of {MAX} selected to compare</p>
        <div className="flex gap-2">
          <button type="button" className="btn btn-ghost btn-sm" onClick={clear}><X size={16} aria-hidden="true" /> Clear</button>
          <Link href={`/compare?ids=${ids.join(",")}`} className="btn btn-primary btn-sm" aria-disabled={ids.length < 2} tabIndex={ids.length < 2 ? -1 : 0}>
            {ids.length < 2 ? "Add one more to compare" : "Compare now"}
          </Link>
        </div>
      </div>
    </div>
  );
}
