import type { Metadata } from "next";
import Link from "next/link";
import { one, type Params } from "@/components/FilterPanel";
import { Pagination } from "@/components/Pagination";
import { EmptyState, ErrorState } from "@/components/States";
import { tryApi } from "@/lib/api";
import { formatDate, platformName } from "@/lib/format";
import type { AdminJob } from "@/lib/types";

export const metadata: Metadata = { title: "Jobs" };

const STATUS_STYLE: Record<string, string> = {
  success: "bg-primary-soft text-fg", running: "bg-surface-2 text-fg", partial: "bg-warn-soft text-warn-fg", failed: "bg-danger-soft text-fg",
};

export default async function JobsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const page = Math.max(1, Number(one(params.page)) || 1);
  const q = { provider: one(params.provider), status: one(params.status), job: one(params.job), failed_only: one(params.failed_only), page, page_size: 25 };
  const res = await tryApi<AdminJob[]>("/api/admin/jobs", { auth: true, query: q });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl font-bold md:text-4xl">Jobs</h1>
        <p className="mt-1 text-muted">Every background run: what it processed, how long it took, and why it failed.</p>
      </div>

      <form method="get" className="card flex flex-wrap items-end gap-3 p-4">
        <div>
          <label htmlFor="j-provider" className="label">Provider</label>
          <select id="j-provider" name="provider" defaultValue={q.provider ?? ""} className="input"><option value="">All</option><option value="amazon">Amazon</option><option value="flipkart">Flipkart</option><option value="all">System</option></select>
        </div>
        <div>
          <label htmlFor="j-status" className="label">Status</label>
          <select id="j-status" name="status" defaultValue={q.status ?? ""} className="input"><option value="">Any</option><option value="success">Success</option><option value="partial">Partial</option><option value="failed">Failed</option><option value="running">Running</option></select>
        </div>
        <label className="flex min-h-11 items-center gap-2 font-semibold"><input type="checkbox" name="failed_only" value="true" defaultChecked={q.failed_only === "true"} className="size-5 accent-[var(--primary)]" /> Problems only</label>
        <button className="btn btn-primary" type="submit">Filter</button>
        <Link href="/admin/jobs" className="btn btn-outline">Reset</Link>
      </form>

      {!res ? <ErrorState /> : res.data.length === 0 ? <EmptyState title="No jobs match">Jobs appear here as soon as the background workers run.</EmptyState> : (
        <>
          <div className="relative overflow-x-auto rounded-2xl border border-line bg-surface">
            <table className="w-full min-w-[44rem] text-left text-sm">
              <caption className="sr-only">Background job runs, newest first</caption>
              <thead className="bg-surface-2"><tr>
                {["Started", "Provider", "Job", "Status", "Records", "Duration", "Error"].map((h) => <th key={h} scope="col" className="px-3 py-2">{h}</th>)}
              </tr></thead>
              <tbody>
                {res.data.map((j) => (
                  <tr key={j.id} className="border-t border-line align-top">
                    <td className="px-3 py-2 whitespace-nowrap tabular">{formatDate(j.started_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</td>
                    <td className="px-3 py-2">{j.provider === "all" ? "System" : platformName(j.provider)}</td>
                    <td className="px-3 py-2">{j.job.replace(/_/g, " ")}</td>
                    <td className="px-3 py-2"><span className={`badge ${STATUS_STYLE[j.status] ?? ""}`}>{j.status}</span></td>
                    <td className="px-3 py-2 tabular">{j.records_processed}</td>
                    <td className="px-3 py-2 tabular">{j.duration_seconds != null ? `${j.duration_seconds}s` : "—"}</td>
                    <td className="px-3 py-2 max-w-xs wrap-anywhere text-muted">{j.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {res.meta && <Pagination meta={res.meta} base="/admin/jobs" params={params} />}
        </>
      )}
    </div>
  );
}
