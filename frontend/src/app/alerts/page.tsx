import type { Metadata } from "next";
import { AlertsList } from "@/components/AlertsList";
import { EmptyState, ErrorState } from "@/components/States";
import { tryApi } from "@/lib/api";
import { requireUser } from "@/lib/session";
import type { Alert } from "@/lib/types";

export const metadata: Metadata = { title: "Price alerts", robots: { index: false } };

export default async function AlertsPage() {
  await requireUser("/alerts");
  const res = await tryApi<Alert[]>("/api/alerts", { auth: true });
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-3xl font-bold md:text-4xl">Price alerts</h1>
        <p className="mt-1 text-muted">We check prices every 30 minutes and notify you once when a price reaches your target. Create alerts from any product page.</p>
      </div>
      {!res ? <ErrorState /> : res.data.length === 0 ? (
        <EmptyState title="No alerts yet" action={{ href: "/deals", label: "Find a product to watch" }}>
          Open a product and choose “Set a price alert” to be told when it gets cheap enough.
        </EmptyState>
      ) : <AlertsList alerts={res.data} />}
    </div>
  );
}
