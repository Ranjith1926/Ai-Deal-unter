import Link from "next/link";
import { AlertTriangle, CheckCircle2, CircleSlash } from "lucide-react";
import { JobButtons, ProviderControls } from "@/components/AdminControls";
import { ErrorState } from "@/components/States";
import { tryApi } from "@/lib/api";
import { formatDate, platformName, timeAgo } from "@/lib/format";
import type { AdminJob, AdminProvider, AdminStats } from "@/lib/types";

const HEALTH = {
  healthy: { icon: CheckCircle2, text: "Healthy", cls: "bg-primary-soft text-fg" },
  attention: { icon: AlertTriangle, text: "Needs attention", cls: "bg-warn-soft text-warn-fg" },
  disabled: { icon: CircleSlash, text: "Disabled", cls: "bg-surface-2 text-fg" },
} as const;

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="card p-4">
      <dt className="text-sm font-semibold text-muted">{label}</dt>
      <dd className="mt-1 font-display text-3xl font-bold tabular">{value}</dd>
      {hint && <dd className="text-xs text-muted">{hint}</dd>}
    </div>
  );
}

function ProviderCard({ p }: { p: AdminProvider }) {
  const h = HEALTH[p.health];
  return (
    <li className="card space-y-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-xl font-bold">{platformName(p.name)}</h3>
        <span className={`badge ${h.cls}`}><h.icon size={14} aria-hidden="true" /> {h.text}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div><dt className="text-muted">Data source</dt><dd className="font-semibold">{p.mode === "demo" ? "Sample (mock) data" : p.mode === "live" ? "Live API" : "Not available"}</dd></div>
        <div><dt className="text-muted">Tracked listings</dt><dd className="font-semibold tabular">{p.listings}</dd></div>
        <div><dt className="text-muted">Last successful run</dt><dd className="font-semibold">{p.last_success_at ? timeAgo(p.last_success_at) : "Never"}</dd></div>
        <div><dt className="text-muted">Failures (24h)</dt><dd className="font-semibold tabular">{p.failures_24h}</dd></div>
        <div><dt className="text-muted">Average run time</dt><dd className="font-semibold tabular">{p.avg_sync_seconds != null ? `${p.avg_sync_seconds}s` : "—"}</dd></div>
        <div><dt className="text-muted">Last run</dt><dd className="font-semibold">{p.last_status ?? "—"}{p.last_job ? ` (${p.last_job.replace(/_/g, " ")})` : ""}</dd></div>
      </dl>
      {p.last_error && <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm wrap-anywhere"><strong>Last error:</strong> {p.last_error}</p>}
      <ProviderControls name={p.name} enabled={p.enabled} />
    </li>
  );
}

export default async function AdminOverview() {
  const [stats, failed] = await Promise.all([
    tryApi<AdminStats>("/api/admin/stats", { auth: true }),
    tryApi<AdminJob[]>("/api/admin/jobs", { auth: true, query: { failed_only: true, page_size: 5 } }),
  ]);
  if (!stats) return <ErrorState title="Couldn't load the dashboard" />;
  const s = stats.data;

  return (
    <div className="space-y-8">
      <h1 className="text-3xl font-bold md:text-4xl">Overview</h1>

      <section aria-labelledby="catalogue">
        <h2 id="catalogue" className="mb-3 text-xl font-bold">Catalogue</h2>
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Total products" value={s.products.total} />
          <Stat label="Active products" value={s.products.active} hint="Visible on the site" />
          <Stat label="Amazon listings" value={s.products.amazon} />
          <Stat label="Flipkart listings" value={s.products.flipkart} />
        </dl>
      </section>

      <section aria-labelledby="activity">
        <h2 id="activity" className="mb-3 text-xl font-bold">Last 24 hours</h2>
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="New deals" value={s.last_24h.deals} />
          <Stat label="Price drops" value={s.last_24h.price_drops} />
          <Stat label="Historical lows" value={s.last_24h.historical_lows} />
          <Stat label="Failed jobs" value={s.last_24h.failed_jobs} hint={s.last_24h.failed_jobs ? "See the Jobs tab" : "All clear"} />
        </dl>
      </section>

      <section aria-labelledby="people">
        <h2 id="people" className="mb-3 text-xl font-bold">Users &amp; system</h2>
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Users" value={s.users} />
          <Stat label="Active price alerts" value={s.alerts.active} hint={`${s.alerts.total} created in total`} />
          <Stat label="Last successful sync" value={<span className="text-xl">{s.last_successful_sync_at ? timeAgo(s.last_successful_sync_at) : "Never"}</span>} />
          <Stat label="Average sync time" value={s.average_sync_seconds != null ? `${s.average_sync_seconds}s` : "—"} hint="Last 7 days" />
        </dl>
      </section>

      <section aria-labelledby="providers">
        <h2 id="providers" className="mb-3 text-xl font-bold">Providers</h2>
        <ul className="grid gap-4 lg:grid-cols-2">{s.providers.map((p) => <ProviderCard key={p.name} p={p} />)}</ul>
      </section>

      <section aria-labelledby="actions">
        <h2 id="actions" className="mb-3 text-xl font-bold">Run a job now</h2>
        <JobButtons />
      </section>

      <section aria-labelledby="failed">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 id="failed" className="text-xl font-bold">Recent failed jobs</h2>
          <Link href="/admin/jobs?failed_only=true" className="font-bold text-primary underline-offset-4 hover:underline">View all</Link>
        </div>
        {!failed || failed.data.length === 0 ? (
          <p className="card px-4 py-6 text-center text-muted">No failed jobs. 🎉 Nothing needs attention.</p>
        ) : (
          <ul className="space-y-2">
            {failed.data.map((j) => (
              <li key={j.id} className="card p-3 text-sm">
                <p className="font-bold">{platformName(j.provider)} · {j.job.replace(/_/g, " ")} <span className="badge bg-danger-soft ml-1">{j.status}</span></p>
                <p className="text-muted">{formatDate(j.started_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</p>
                {j.error && <p className="mt-1 wrap-anywhere">{j.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
