import type { Metadata } from "next";
import { ScoringEditor } from "@/components/ScoringEditor";
import { ErrorState } from "@/components/States";
import { tryApi } from "@/lib/api";
import type { ScoringState } from "@/lib/types";

export const metadata: Metadata = { title: "Scoring" };

export default async function ScoringPage() {
  const res = await tryApi<ScoringState>("/api/admin/scoring", { auth: true });
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl font-bold md:text-4xl">Scoring</h1>
        <p className="mt-1 max-w-2xl text-muted">Tune how deals and value are scored. Changes are checked before they are saved, apply to the next calculation, and are recorded in the audit log.</p>
      </div>
      {res ? <ScoringEditor state={res.data} key={res.data.updated_at ?? "default"} /> : <ErrorState />}
    </div>
  );
}
