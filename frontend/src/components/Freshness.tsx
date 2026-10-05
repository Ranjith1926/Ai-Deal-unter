import { AlertTriangle, Clock } from "lucide-react";
import { timeAgo } from "@/lib/format";

/** "Updated 12 minutes ago", or an explicit warning when the data is stale. */
export function Freshness({ updatedAt, isStale, className = "" }: { updatedAt: string | null; isStale: boolean; className?: string }) {
  if (!updatedAt) {
    return (
      <p className={`flex items-center gap-1.5 text-xs text-muted ${className}`}>
        <Clock size={14} aria-hidden="true" /> No price captured yet
      </p>
    );
  }
  return (
    <p className={`flex flex-wrap items-center gap-x-1.5 text-xs ${isStale ? "text-warn-fg" : "text-muted"} ${className}`}>
      {isStale ? <AlertTriangle size={14} aria-hidden="true" /> : <Clock size={14} aria-hidden="true" />}
      <time dateTime={updatedAt}>Updated {timeAgo(updatedAt)}</time>
      {isStale && <strong className="font-bold">· Price data may be outdated</strong>}
    </p>
  );
}
