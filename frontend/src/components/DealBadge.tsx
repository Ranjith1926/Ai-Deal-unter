import { Clock, Flame, Minus, ThumbsDown, ThumbsUp, TrendingDown } from "lucide-react";
import { TIER } from "@/lib/format";
import type { DealLabel } from "@/lib/types";

const ICONS = {
  exceptional: Flame, great: TrendingDown, good: ThumbsUp, average: Minus, poor: ThumbsDown, insufficient_data: Clock,
} as const;

/** Circular 0-100 score. Decorative: the number and the tier name are always also in text. */
export function ScoreRing({ score, label, size = 48 }: { score: number | null; label: DealLabel; size?: number }) {
  const r = 18;
  const c = 2 * Math.PI * r;
  const pct = score == null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  return (
    <svg width={size} height={size} viewBox="0 0 44 44" aria-hidden="true" className="shrink-0">
      <circle cx="22" cy="22" r={r} fill="none" stroke="var(--border)" strokeWidth="4" />
      {score != null && (
        <circle
          cx="22" cy="22" r={r} fill="none" stroke={TIER[label].fg} strokeWidth="4" strokeLinecap="round"
          strokeDasharray={`${c * pct} ${c}`} transform="rotate(-90 22 22)"
        />
      )}
      <text x="22" y="26.5" textAnchor="middle" fontSize="13" fontWeight="700" fill="currentColor" className="tabular">
        {score == null ? "–" : Math.round(score)}
      </text>
    </svg>
  );
}

/** Tier pill: always icon + words, never colour alone. */
export function DealBadge({ label, score, className = "" }: { label: DealLabel; score?: number | null; className?: string }) {
  const tier = TIER[label];
  const Icon = ICONS[label];
  return (
    <span className={`badge ${className}`} style={{ background: tier.bg, color: tier.fg }}>
      <Icon size={14} aria-hidden="true" />
      <span>{tier.text}</span>
      {score != null && <span className="sr-only"> — score {Math.round(score)} out of 100</span>}
    </span>
  );
}
