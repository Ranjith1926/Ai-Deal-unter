import { FilterPanel, one, type Params } from "./FilterPanel";
import { Pagination } from "./Pagination";
import { ProductGrid } from "./ProductGrid";
import { EmptyState, ErrorState } from "./States";
import { tryApi } from "@/lib/api";
import { getFavoriteIds, getUser } from "@/lib/session";
import type { Category, ProductCard } from "@/lib/types";

const PASS = ["q", "category", "brand", "min_price", "max_price", "platform", "deal_score", "value_score", "sort"] as const;

/** Server-rendered product listing with filters, sorting and pagination, driven by the URL. */
export async function Browse({ basePath, params, fixed = {}, lockCategory = false, defaultSort = "deal_score", heading, scoredOnly = false }: {
  basePath: string; params: Params; fixed?: Record<string, string>; lockCategory?: boolean;
  defaultSort?: string; heading: React.ReactNode; scoredOnly?: boolean;
}) {
  const page = Math.max(1, Number(one(params.page)) || 1);
  const query: Record<string, string | number> = { sort: one(params.sort) ?? defaultSort, page, page_size: 12, ...fixed };
  for (const key of PASS) { const v = one(params[key]); if (v && !(key in fixed)) query[key] = v; }

  const [list, cats, favorites, user] = await Promise.all([
    tryApi<ProductCard[]>(scoredOnly ? "/api/deals" : "/api/products", { query }),
    tryApi<Category[]>("/api/categories", { revalidate: 300 }),
    getFavoriteIds(),
    getUser(),
  ]);

  return (
    <>
      {heading}
      <div className="mt-6 grid gap-6 lg:grid-cols-[17rem_1fr]">
        <aside aria-label="Filters" className="lg:sticky lg:top-24 lg:self-start">
          <FilterPanel action={basePath} params={params} categories={cats?.data ?? []} lockCategory={lockCategory} />
        </aside>
        <div className="min-w-0">
          {!list ? (
            <ErrorState />
          ) : list.data.length === 0 ? (
            <EmptyState title="No products match these filters" action={{ href: basePath, label: "Clear filters" }}>
              Try widening the price range, removing a filter, or searching for a different product.
            </EmptyState>
          ) : (
            <>
              <p className="mb-3 text-sm text-muted" role="status">
                Showing {list.data.length} of {list.meta?.total ?? list.data.length} product{(list.meta?.total ?? 0) === 1 ? "" : "s"}
              </p>
              <ProductGrid products={list.data} favorites={favorites} signedIn={!!user} />
              {list.meta && <Pagination meta={list.meta} base={basePath} params={params} />}
            </>
          )}
        </div>
      </div>
    </>
  );
}
