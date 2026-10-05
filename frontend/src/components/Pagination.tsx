import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { Meta } from "@/lib/types";
import { one, type Params } from "./FilterPanel";

function href(base: string, params: Params, page: number): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    const val = one(v);
    if (val && k !== "page") sp.set(k, val);
  }
  if (page > 1) sp.set("page", String(page));
  const qs = sp.toString();
  return qs ? `${base}?${qs}` : base;
}

export function Pagination({ meta, base, params }: { meta: Meta; base: string; params: Params }) {
  if (meta.pages <= 1) return null;
  const { page, pages } = meta;
  const window = new Set([1, pages, page - 1, page, page + 1]);
  const nums = [...window].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  return (
    <nav aria-label="Pagination" className="mt-8 flex flex-wrap items-center justify-center gap-2">
      {page > 1 && <Link href={href(base, params, page - 1)} rel="prev" className="btn btn-outline btn-sm"><ChevronLeft size={16} aria-hidden="true" /> Previous</Link>}
      {nums.map((n, i) => (
        <span key={n} className="flex items-center gap-2">
          {i > 0 && n - nums[i - 1] > 1 && <span aria-hidden="true">…</span>}
          <Link href={href(base, params, n)} aria-current={n === page ? "page" : undefined}
            className={`btn btn-sm ${n === page ? "btn-primary" : "btn-outline"}`}><span className="sr-only">Page </span>{n}</Link>
        </span>
      ))}
      {page < pages && <Link href={href(base, params, page + 1)} rel="next" className="btn btn-outline btn-sm">Next <ChevronRight size={16} aria-hidden="true" /></Link>}
    </nav>
  );
}
