import { FlaskConical } from "lucide-react";
import { tryApi } from "@/lib/api";
import type { SiteMeta } from "@/lib/types";

/** Shown whenever the site is running on sample (mock) marketplace data. */
export async function DemoBanner() {
  const meta = await tryApi<SiteMeta>("/api/meta", { revalidate: 300 });
  if (meta?.data.data_mode !== "demo") return null;
  return (
    <div role="note" className="border-b border-line bg-warn-soft text-warn-fg">
      <p className="container-page flex items-center gap-2 py-2 text-sm font-semibold">
        <FlaskConical size={16} className="shrink-0" aria-hidden="true" />
        Demo mode: these are sample products and prices, not live Amazon or Flipkart data.
      </p>
    </div>
  );
}
