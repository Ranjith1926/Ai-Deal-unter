import type { Metadata } from "next";
import Link from "next/link";
import { CategoryManager, ListingToggle, ProductActiveToggle } from "@/components/AdminCatalog";
import { one, type Params } from "@/components/FilterPanel";
import { Pagination } from "@/components/Pagination";
import { EmptyState, ErrorState } from "@/components/States";
import { tryApi } from "@/lib/api";
import { formatINR, platformName } from "@/lib/format";
import type { AdminCategory, AdminProduct } from "@/lib/types";

export const metadata: Metadata = { title: "Catalogue" };

export default async function CatalogAdminPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const page = Math.max(1, Number(one(params.page)) || 1);
  const q = one(params.q);
  const active = one(params.active);
  const [cats, products] = await Promise.all([
    tryApi<AdminCategory[]>("/api/admin/categories", { auth: true }),
    tryApi<AdminProduct[]>("/api/admin/products", { auth: true, query: { q, active, category_id: one(params.category_id), page, page_size: 20 } }),
  ]);

  return (
    <div className="space-y-10">
      <section aria-labelledby="cats" className="space-y-3">
        <h1 id="cats" className="text-3xl font-bold md:text-4xl">Catalogue</h1>
        <h2 className="text-xl font-bold">Categories</h2>
        {cats ? <CategoryManager categories={cats.data} /> : <ErrorState />}
      </section>

      <section aria-labelledby="prods" className="space-y-3">
        <h2 id="prods" className="text-xl font-bold">Products</h2>
        <form method="get" className="card flex flex-wrap items-end gap-3 p-4">
          <div className="min-w-48 flex-1"><label htmlFor="p-q" className="label">Search name or brand</label><input id="p-q" name="q" defaultValue={q} className="input" /></div>
          <div>
            <label htmlFor="p-cat" className="label">Category</label>
            <select id="p-cat" name="category_id" defaultValue={one(params.category_id) ?? ""} className="input"><option value="">All</option>{cats?.data.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          </div>
          <div>
            <label htmlFor="p-active" className="label">Visibility</label>
            <select id="p-active" name="active" defaultValue={active ?? ""} className="input"><option value="">All</option><option value="true">Visible</option><option value="false">Hidden</option></select>
          </div>
          <button className="btn btn-primary" type="submit">Filter</button>
          <Link href="/admin/catalog" className="btn btn-outline">Reset</Link>
        </form>

        {!products ? <ErrorState /> : products.data.length === 0 ? <EmptyState title="No products match" /> : (
          <>
            <ul className="space-y-3">
              {products.data.map((p) => (
                <li key={p.id} className={`card p-4 ${p.is_active ? "" : "opacity-75"}`}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-bold uppercase tracking-wide text-muted">{p.brand}{p.category ? ` · ${p.category}` : ""}</p>
                      <p className="font-bold wrap-anywhere"><Link href={`/deals/${p.id}`} className="underline-offset-4 hover:underline">{p.name}</Link> <span className="font-normal text-muted">#{p.id}</span></p>
                      {!p.is_active && <p className="badge mt-1 bg-surface-2">Hidden from the site</p>}
                    </div>
                    <ProductActiveToggle product={p} />
                  </div>
                  <ul className="mt-3 flex flex-wrap gap-2" aria-label={`Listings for ${p.name}`}>
                    {p.listings.map((l) => (
                      <li key={l.id} className="flex items-center gap-2 text-sm">
                        <ListingToggle listingId={l.id} active={l.is_active} label={platformName(l.platform)} />
                        <span className="tabular text-muted">{formatINR(l.price)}{l.match_method ? ` · ${l.match_method}${l.match_confidence != null ? ` ${Math.round(l.match_confidence)}%` : ""}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
            {products.meta && <Pagination meta={products.meta} base="/admin/catalog" params={params} />}
          </>
        )}
      </section>
    </div>
  );
}
