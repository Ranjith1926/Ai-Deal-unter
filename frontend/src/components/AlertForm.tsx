"use client";

import { Bell, Loader2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { formatINR, platformName } from "@/lib/format";

interface Props {
  productId: number; productName: string; currentPrice: number | null; historicalLow: number | null;
  platforms: string[]; signedIn: boolean;
}

export function AlertForm({ productId, productName, currentPrice, historicalLow, platforms, signedIn }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [target, setTarget] = useState("");
  const [platform, setPlatform] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  if (!signedIn) {
    return (
      <p className="text-sm">
        <Link href={`/login?next=${encodeURIComponent(pathname)}`} className="font-bold text-primary underline underline-offset-4">Sign in</Link>{" "}
        to get an alert when {productName} drops to your price.
      </p>
    );
  }

  const suggestions = [
    currentPrice != null && { label: "5% below today", value: Math.floor(currentPrice * 0.95) },
    historicalLow != null && { label: "Lowest tracked", value: Math.floor(historicalLow) },
  ].filter(Boolean) as { label: string; value: number }[];

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const price = Number(target);
    if (!Number.isFinite(price) || price <= 0) { setMessage({ ok: false, text: "Enter a target price above ₹0." }); return; }
    setBusy(true); setMessage(null);
    try {
      const res = await fetch("/bff/alerts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: productId, target_price: price, platform: platform || null }),
      });
      const body = await res.json().catch(() => null);
      if (res.status === 401) { router.push(`/login?next=${encodeURIComponent(pathname)}`); return; }
      if (!res.ok) { setMessage({ ok: false, text: body?.errors?.[0] ?? body?.message ?? "Couldn't create the alert." }); return; }
      setMessage({ ok: true, text: `Alert set. We'll notify you when the price is ${formatINR(price)} or less.` });
      setTarget("");
      router.refresh();
    } catch {
      setMessage({ ok: false, text: "We couldn't reach the server. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3" noValidate>
      <div>
        <label htmlFor="alert-target" className="label">Alert me at or below (₹)</label>
        <input id="alert-target" inputMode="numeric" type="number" min="1" step="1" required value={target} onChange={(e) => setTarget(e.target.value)}
          className="input" placeholder={currentPrice ? `Currently ${formatINR(currentPrice)}` : "Target price"} aria-describedby="alert-hint" />
        <p id="alert-hint" className="hint">We check prices every 30 minutes and tell you once, when it is reached.</p>
        {suggestions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Suggested targets">
            {suggestions.map((s) => <button key={s.label} type="button" className="chip" onClick={() => setTarget(String(s.value))}>{s.label}: {formatINR(s.value)}</button>)}
          </div>
        )}
      </div>
      {platforms.length > 1 && (
        <div>
          <label htmlFor="alert-platform" className="label">Store</label>
          <select id="alert-platform" value={platform} onChange={(e) => setPlatform(e.target.value)} className="input">
            <option value="">Any store</option>
            {platforms.map((p) => <option key={p} value={p}>{platformName(p)}</option>)}
          </select>
        </div>
      )}
      <button type="submit" disabled={busy} className="btn btn-primary w-full">
        {busy ? <Loader2 size={18} className="animate-spin" aria-hidden="true" /> : <Bell size={18} aria-hidden="true" />} Set price alert
      </button>
      <p role="status" className={`text-sm font-semibold ${message?.ok ? "text-fg" : "text-danger"}`}>{message?.text}</p>
    </form>
  );
}
