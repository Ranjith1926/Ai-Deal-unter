import Link from "next/link";
import { ArrowRight, BarChart3, ListChecks, Scale, Search, ShieldCheck } from "lucide-react";
import { DealBadge, ScoreRing } from "@/components/DealBadge";
import { BUDGETS } from "@/components/FilterPanel";
import { ProductGrid, Section } from "@/components/ProductGrid";
import { EmptyState } from "@/components/States";
import { tryApi } from "@/lib/api";
import { categoryTitle, formatINR } from "@/lib/format";
import { getFavoriteIds, getUser } from "@/lib/session";
import type { Category, DealWithEvent, ProductCard } from "@/lib/types";

const FEATURED = ["mobiles", "laptops", "tv", "electronics", "home-appliances"];

const TRUST = [
  { icon: BarChart3, title: "Judged on price history", body: "We compare today's price with weeks of recorded prices, not the discount the seller advertises." },
  { icon: Scale, title: "Amazon vs Flipkart", body: "See both stores side by side and which one is cheaper right now." },
  { icon: ShieldCheck, title: "Honest by design", body: "If there isn't enough history we say so. We never invent prices or reasons." },
];

export default async function HomePage() {
  const [best, drops, value, cats, favorites, user, ...budgets] = await Promise.all([
    tryApi<ProductCard[]>("/api/deals/best", { query: { limit: 4 } }),
    tryApi<DealWithEvent[]>("/api/deals/price-drops", { query: { hours: 24, limit: 4 } }),
    tryApi<ProductCard[]>("/api/products", { query: { sort: "value_score", value_score: 1, page_size: 4 } }),
    tryApi<Category[]>("/api/categories", { revalidate: 300 }),
    getFavoriteIds(),
    getUser(),
    ...BUDGETS.map((b) => tryApi<ProductCard[]>("/api/products", { query: { max_price: b, sort: "deal_score", page_size: 1 } })),
  ]);

  const signedIn = !!user;
  const top = best?.data[0] ?? null;
  const featured = (cats?.data ?? []).filter((c) => FEATURED.includes(c.slug) && c.product_count > 0);
  const categoryRows = await Promise.all(
    featured.map(async (c) => ({ c, res: await tryApi<ProductCard[]>("/api/products", { query: { category: c.slug, sort: "deal_score", page_size: 4 } }) })),
  );

  return (
    <>
      <section aria-labelledby="hero" className="relative overflow-hidden rounded-3xl bg-primary px-5 py-10 text-primary-fg md:px-12 md:py-16">
        <div aria-hidden="true" className="pointer-events-none absolute -right-16 -top-16 size-72 rounded-full bg-white/10" />
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-24 right-24 size-56 rounded-full bg-white/5" />
        <div className="relative grid items-center gap-8 md:grid-cols-[1.25fr_1fr]">
        <div className="max-w-2xl">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-surface px-3 py-1 text-sm font-bold text-fg"><ListChecks size={16} aria-hidden="true" /> Real price history · Amazon India &amp; Flipkart</p>
          <h1 id="hero" className="text-4xl font-bold md:text-6xl">Real deals, not fake discounts.</h1>
          <p className="mt-4 max-w-xl text-lg">
            A “70% off” sticker means nothing if the price was inflated first. We track every price, so you can see if a deal is genuine before you buy.
          </p>
          <form action="/search" role="search" className="mt-6 flex max-w-xl flex-col gap-2 sm:flex-row">
            <label htmlFor="hero-search" className="sr-only">Search for a product</label>
            <input id="hero-search" name="q" type="search" required placeholder="Search “Samsung TV”, “iPhone 16”…" autoComplete="off"
              className="input !border-transparent !text-[#0b2f26] placeholder:!text-[#4b5b66]" style={{ background: "#fff" }} />
            <button type="submit" className="btn btn-accent shrink-0"><Search size={18} aria-hidden="true" /> Find deals</button>
          </form>
        </div>
        {top && (
          <Link href={`/deals/${top.id}`} className="hidden rounded-2xl bg-surface p-5 text-fg shadow-pop transition hover:-translate-y-0.5 md:block">
            <p className="text-sm font-bold text-muted">Top deal right now</p>
            <p className="mt-1 line-clamp-2 font-display text-lg font-bold">{top.name}</p>
            <div className="mt-3 flex items-center gap-4">
              <ScoreRing score={top.deal_score} label={top.deal_label} size={64} />
              <div>
                <p className="font-display text-3xl font-bold tabular">{formatINR(top.current_price)}</p>
                {top.typical_price != null && top.current_price != null && top.typical_price > top.current_price && (
                  <p className="text-sm text-muted">{formatINR(top.typical_price - top.current_price)} below its usual {formatINR(top.typical_price)}</p>
                )}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <DealBadge label={top.deal_label} score={top.deal_score} />
              <span className="inline-flex items-center gap-1 text-sm font-bold text-primary">See why <ArrowRight size={16} aria-hidden="true" /></span>
            </div>
          </Link>
        )}
        </div>
      </section>

      <ul className="mt-6 grid gap-4 md:grid-cols-3">
        {TRUST.map(({ icon: Icon, title, body }) => (
          <li key={title} className="card flex gap-3 p-4">
            <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><Icon size={22} aria-hidden="true" /></span>
            <div><h2 className="text-base font-bold">{title}</h2><p className="text-sm text-muted">{body}</p></div>
          </li>
        ))}
      </ul>

      <Section id="best" title="Today's best deals" subtitle="Products priced well below their own recent history." href="/deals?deal_score=70">
        {best && best.data.length > 0 ? <ProductGrid products={best.data} favorites={favorites} signedIn={signedIn} /> : (
          <EmptyState title="No standout deals right now">No tracked product currently scores as a good deal. This updates every 30 minutes as new prices arrive.</EmptyState>
        )}
      </Section>

      <Section id="drops" title="Biggest price drops" subtitle="Products whose price fell in the last 24 hours." href="/deals?sort=price_drop" >
        {drops && drops.data.length > 0 ? <ProductGrid products={drops.data.map((d) => d.product)} favorites={favorites} signedIn={signedIn} /> : (
          <EmptyState title="No price drops in the last 24 hours">When a tracked price falls, it appears here.</EmptyState>
        )}
      </Section>

      <Section id="value" title="Best value products" subtitle="Most performance for the money, compared with similar products." href="/deals?sort=value_score">
        {value && value.data.length > 0 ? <ProductGrid products={value.data} favorites={favorites} signedIn={signedIn} /> : (
          <EmptyState title="Value scores are still being calculated">They need several comparable products with specifications to rank fairly.</EmptyState>
        )}
      </Section>

      <section aria-labelledby="budget" className="py-6">
        <h2 id="budget" className="mb-4 text-2xl font-bold md:text-3xl">Shop by budget</h2>
        <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {BUDGETS.map((b, i) => {
            const res = budgets[i];
            const total = res?.meta?.total ?? 0;
            return (
              <li key={b}>
                <Link href={`/deals?max_price=${b}`} className="card card-link flex h-full flex-col justify-between gap-2 p-4">
                  <span className="font-display text-xl font-bold">Under {formatINR(b)}</span>
                  <span className="text-sm text-muted">{total > 0 ? `${total} product${total === 1 ? "" : "s"}` : "No products yet"}{res?.data[0] ? <> · top: <span className="font-semibold text-fg">{res.data[0].name.split(" ").slice(0, 3).join(" ")}</span></> : null}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </section>

      {categoryRows.filter((r) => r.res && r.res.data.length > 0).map(({ c, res }) => (
        <Section key={c.slug} id={`cat-${c.slug}`} title={categoryTitle(c.slug)} href={`/category/${c.slug}`} linkLabel={`All ${c.product_count}`}>
          <ProductGrid products={res!.data} favorites={favorites} signedIn={signedIn} />
        </Section>
      ))}
    </>
  );
}
