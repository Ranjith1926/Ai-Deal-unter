"use client";

import { BellRing, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { flashAndReload } from "./Flash";
import { formatDate, formatINR, platformName } from "@/lib/format";
import type { Alert } from "@/lib/types";

export function AlertsList({ alerts }: { alerts: Alert[] }) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [message, setMessage] = useState("");

  async function remove(a: Alert) {
    setBusyId(a.id);
    const res = await fetch(`/bff/alerts/${a.id}`, { method: "DELETE" }).catch(() => null);
    if (res?.ok) { flashAndReload(`Alert for ${a.product_name} deleted.`); return; }
    setBusyId(null);
    setMessage("Couldn't delete that alert. Please try again.");
  }

  return (
    <>
      <ul className="grid gap-3">
        {alerts.map((a) => {
          const reached = a.triggered_at != null;
          return (
            <li key={a.id} className="card flex flex-wrap items-center gap-4 p-4">
              <div className="min-w-0 flex-1">
                <Link href={`/deals/${a.product_id}`} className="wrap-anywhere font-bold underline-offset-4 hover:underline">{a.product_name}</Link>
                <p className="mt-1 text-sm text-muted">
                  Target <strong className="text-fg tabular">{formatINR(a.target_price)}</strong>
                  {a.platform ? ` on ${platformName(a.platform)}` : " on any store"}
                  {a.current_price != null && <> · Now <strong className="text-fg tabular">{formatINR(a.current_price)}</strong></>}
                </p>
                {!reached && a.amount_above_target != null && a.amount_above_target > 0 && (
                  <p className="text-sm text-muted">{formatINR(a.amount_above_target)} to go</p>
                )}
              </div>
              <span className={`badge ${reached ? "bg-primary-soft text-fg" : "bg-surface-2 text-fg"}`}>
                <BellRing size={14} aria-hidden="true" />
                {reached ? `Reached ${formatDate(a.triggered_at!)}` : "Watching"}
              </span>
              <button type="button" onClick={() => remove(a)} disabled={busyId === a.id} className="btn btn-outline btn-sm">
                <Trash2 size={16} aria-hidden="true" /> Delete<span className="sr-only"> alert for {a.product_name}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <p role="status" className="sr-only">{message}</p>
    </>
  );
}
