import Link from "next/link";
import { SlidersHorizontal, X } from "lucide-react";
import { FilterShell } from "./FilterShell";
import { categoryTitle, formatINR, platformName } from "@/lib/format";
import type { Category } from "@/lib/types";

export interface Params { [key: string]: string | string[] | undefined }

export const SORT_OPTIONS: [string, string][] = [
  ["deal_score", "Best deal score"], ["value_score", "Best value"], ["price_drop", "Biggest price drop"],
  ["price_asc", "Price: low to high"], ["price_desc", "Price: high to low"], ["newest", "Newest"],
];
export const BUDGETS = [5000, 10000, 25000, 50000];

export function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

/** Build a URL for the same page with some params changed (undefined removes). */
export function withParams(base: string, params: Params, change: Record<string, string | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...params, ...change })) {
    const val = one(v as string | string[] | undefined);
    if (val) sp.set(k, val);
  }
  sp.delete("page"); // any filter change returns to page 1
  const qs = sp.toString();
  return qs ? `${base}?${qs}` : base;
}

/**
 * Filters are a plain GET form: shareable URLs, back-button friendly, and fully working
 * without JavaScript.
 */
export function FilterPanel({ action, params, categories, lockCategory }: {
  action: string; params: Params; categories: Category[]; lockCategory?: boolean;
}) {
  const v = (k: string) => one(params[k]) ?? "";
  const active: { label: string; href: string }[] = [];
  const add = (key: string, label: string) => v(key) && active.push({ label, href: withParams(action, params, { [key]: undefined }) });
  if (!lockCategory) add("category", `Category: ${categoryTitle(v("category")).replace(/ deals$/, "")}`);
  add("brand", `Brand: ${v("brand")}`);
  add("platform", `Store: ${platformName(v("platform"))}`);
  add("min_price", `From ${formatINR(Number(v("min_price")))}`);
  add("max_price", `Up to ${formatINR(Number(v("max_price")))}`);
  add("deal_score", `Deal score ${v("deal_score")}+`);

  return (
    <div className="space-y-3">
      <FilterShell>
        <summary className="btn btn-outline w-full list-none justify-between lg:hidden [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-2"><SlidersHorizontal size={18} aria-hidden="true" /> Filters &amp; sort</span>
          {active.length > 0 && <span className="badge bg-primary text-primary-fg">{active.length}</span>}
        </summary>
        <form action={action} method="get" className="card mt-3 space-y-4 p-4 lg:mt-0">
          {v("q") && <input type="hidden" name="q" value={v("q")} />}
          <div>
            <label htmlFor="f-sort" className="label">Sort by</label>
            <select id="f-sort" name="sort" defaultValue={v("sort") || "deal_score"} className="input">
              {SORT_OPTIONS.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
            </select>
          </div>
          {!lockCategory && (
            <div>
              <label htmlFor="f-category" className="label">Category</label>
              <select id="f-category" name="category" defaultValue={v("category")} className="input">
                <option value="">All categories</option>
                {categories.map((c) => <option key={c.slug} value={c.slug}>{c.name} ({c.product_count})</option>)}
              </select>
            </div>
          )}
          <div>
            <label htmlFor="f-brand" className="label">Brand</label>
            <input id="f-brand" name="brand" defaultValue={v("brand")} className="input" placeholder="e.g. Samsung" autoComplete="off" />
          </div>
          <div>
            <label htmlFor="f-platform" className="label">Store</label>
            <select id="f-platform" name="platform" defaultValue={v("platform")} className="input">
              <option value="">Amazon &amp; Flipkart</option><option value="amazon">Amazon</option><option value="flipkart">Flipkart</option>
            </select>
          </div>
          <fieldset>
            <legend className="label">Price (₹)</legend>
            <div className="flex items-center gap-2">
              <div className="flex-1"><label htmlFor="f-min" className="sr-only">Minimum price</label><input id="f-min" name="min_price" type="number" min="0" inputMode="numeric" defaultValue={v("min_price")} className="input" placeholder="Min" /></div>
              <span aria-hidden="true">–</span>
              <div className="flex-1"><label htmlFor="f-max" className="sr-only">Maximum price</label><input id="f-max" name="max_price" type="number" min="0" inputMode="numeric" defaultValue={v("max_price")} className="input" placeholder="Max" /></div>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {BUDGETS.map((b) => (
                <Link key={b} className="chip" aria-current={v("max_price") === String(b) && !v("min_price") ? "true" : undefined}
                  href={withParams(action, params, { max_price: String(b), min_price: undefined })}>Under {formatINR(b)}</Link>
              ))}
            </div>
          </fieldset>
          <div>
            <label htmlFor="f-score" className="label">Minimum deal score</label>
            <select id="f-score" name="deal_score" defaultValue={v("deal_score")} className="input">
              <option value="">Any</option><option value="60">60+ Average or better</option><option value="70">70+ Good deal</option>
              <option value="80">80+ Great deal</option><option value="90">90+ Exceptional</option>
            </select>
          </div>
          <div className="flex gap-2">
            <button type="submit" className="btn btn-primary flex-1">Apply filters</button>
            <Link href={v("q") ? `${action}?q=${encodeURIComponent(v("q"))}` : action} className="btn btn-outline">Reset</Link>
          </div>
        </form>
      </FilterShell>

      {active.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Active filters">
          {active.map((a) => (
            <li key={a.label}>
              <Link href={a.href} className="chip">{a.label}<X size={14} aria-hidden="true" /><span className="sr-only"> — remove filter</span></Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
