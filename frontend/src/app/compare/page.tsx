import type { Metadata } from "next";
import Link from "next/link";
import { GitCompareArrows } from "lucide-react";
import { DealBadge } from "@/components/DealBadge";
import { one, type Params } from "@/components/FilterPanel";
import { ProductImage } from "@/components/ProductImage";
import { EmptyState } from "@/components/States";
import { tryApi } from "@/lib/api";
import { formatINR, platformName } from "@/lib/format";
import type { ProductComparison, ProductDetail } from "@/lib/types";

export const metadata: Metadata = { title: "Compare products", robots: { index: false } };

export default async function ComparePage({ searchParams }: { searchParams: Promise<Params> }) {
  const raw = one((await searchParams).ids) ?? "";
  const ids = [...new Set(raw.split(",").map((s) => s.trim()).filter((s) => /^\d+$/.test(s)))].slice(0, 3);

  if (ids.length < 2) {
    return (
      <div className="mx-auto max-w-xl py-8">
        <EmptyState title="Pick two or three products to compare">
          Use the <strong>Compare</strong> button on any product card. We&apos;ll line up price, scores, ratings and specifications side by side.
          {ids.length === 1 && " You have one selected — add at least one more."}
          <span className="mt-3 block"><GitCompareArrows className="mx-auto" size={28} aria-hidden="true" /></span>
        </EmptyState>
        <p className="mt-4 text-center"><Link href="/deals" className="btn btn-primary">Browse deals</Link></p>
      </div>
    );
  }

  // The backend does the comparing and picks the winners; this page only presents the result.
  const result = await tryApi<ProductComparison>("/api/compare", { query: { ids: ids.join(",") }, revalidate: 30 });
  if (!result) return <EmptyState title="Some of these products couldn't be loaded" action={{ href: "/deals", label: "Browse deals" }}>They may have been removed. Choose different products to compare.</EmptyState>;
  const { products, spec_keys: specKeys, summary } = result.data;
  const mark = (p: ProductDetail, winnerId: number | null) => (winnerId === p.id ? <span className="badge ml-2 bg-primary-soft text-fg">Best</span> : null);
  const cheapest = result.data.cheapest_id, topValue = result.data.best_value_id, topDeal = result.data.best_deal_id;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold md:text-4xl">Compare products</h1>
        <p className="mt-1 text-muted">Prices are the lowest across stores. Scores come from each product&apos;s own price history.</p>
      </div>

      <div className="relative overflow-x-auto rounded-2xl border border-line bg-surface">
        <table className="w-full min-w-[40rem] text-left">
          <caption className="sr-only">Side-by-side comparison of {products.map((p) => p.name).join(", ")}</caption>
          <thead>
            <tr className="align-top">
              <td className="w-40 px-4 py-4"><span className="sr-only">Feature</span></td>
              {products.map((p) => (
                <th key={p.id} scope="col" className="min-w-52 px-4 py-4 font-normal">
                  <ProductImage src={p.image_url} name={p.name} brand={p.brand} category={p.category} className="mb-3 h-28" />
                  <Link href={`/deals/${p.id}`} className="font-display text-base font-bold underline-offset-4 hover:underline wrap-anywhere">{p.name}</Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="[&_td]:px-4 [&_td]:py-3 [&_th]:px-4 [&_th]:py-3 [&_tr]:border-t [&_tr]:border-line">
            <tr><th scope="row" className="font-semibold text-muted">Best price</th>{products.map((p) => <td key={p.id} className="font-display text-xl font-bold tabular">{formatINR(p.current_price)}{mark(p, cheapest)}</td>)}</tr>
            <tr><th scope="row" className="font-semibold text-muted">Cheapest at</th>{products.map((p) => <td key={p.id}>{platformName(p.best_platform)}</td>)}</tr>
            <tr><th scope="row" className="font-semibold text-muted">Deal</th>{products.map((p) => <td key={p.id}><DealBadge label={p.deal_label} score={p.deal_score} />{p.deal_score != null && <span className="ml-2 font-bold tabular">{Math.round(p.deal_score)}/100</span>}{mark(p, topDeal)}</td>)}</tr>
            <tr><th scope="row" className="font-semibold text-muted">Value score</th>{products.map((p) => <td key={p.id} className="tabular">{p.value_score != null ? <><strong>{Math.round(p.value_score)}</strong>/100{mark(p, topValue)}</> : <span className="text-muted">Not enough comparable data</span>}</td>)}</tr>
            <tr><th scope="row" className="font-semibold text-muted">Typical price</th>{products.map((p) => <td key={p.id} className="tabular">{formatINR(p.typical_price)}</td>)}</tr>
            <tr><th scope="row" className="font-semibold text-muted">Lowest tracked</th>{products.map((p) => <td key={p.id} className="tabular">{formatINR(p.historical_low)}</td>)}</tr>
            <tr><th scope="row" className="font-semibold text-muted">Rating</th>{products.map((p) => <td key={p.id}>{p.rating != null ? <>{p.rating.toFixed(1)}/5 <span className="text-muted">({p.review_count?.toLocaleString("en-IN")})</span></> : "—"}</td>)}</tr>
            {specKeys.map((k) => (
              <tr key={k}><th scope="row" className="font-semibold capitalize text-muted">{k.replace(/_/g, " ")}</th>{products.map((p) => <td key={p.id}>{p.specifications[k] ?? "—"}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>

      <section aria-labelledby="verdict" className="card p-5">
        <h2 id="verdict" className="text-xl font-bold">At a glance</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {summary.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>
    </div>
  );
}
