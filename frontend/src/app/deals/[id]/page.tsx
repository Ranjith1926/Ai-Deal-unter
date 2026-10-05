import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AlertTriangle, Bot, Check, ExternalLink, Info, TrendingDown } from "lucide-react";
import { AlertForm } from "@/components/AlertForm";
import { CompareToggle } from "@/components/Compare";
import { DealBadge, ScoreRing } from "@/components/DealBadge";
import { FavoriteButton } from "@/components/FavoriteButton";
import { Freshness } from "@/components/Freshness";
import { PlatformTable } from "@/components/PlatformTable";
import { PriceChart } from "@/components/PriceChart";
import { ProductImage } from "@/components/ProductImage";
import { ErrorState, Notice } from "@/components/States";
import { ApiError, api, tryApi } from "@/lib/api";
import { categoryTitle, formatINR, formatPct, platformName } from "@/lib/format";
import { getFavoriteIds, getUser } from "@/lib/session";
import type { Comparison, Factor, PriceHistory, ProductDetail } from "@/lib/types";

type Props = { params: Promise<{ id: string }> };

async function loadProduct(id: string) {
  if (!/^\d+$/.test(id)) notFound();
  try {
    return (await api<ProductDetail>(`/api/products/${id}`, { revalidate: 30 })).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    return null;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const p = await loadProduct((await params).id);
  if (!p) return { title: "Product" };
  const price = p.current_price != null ? ` from ${formatINR(p.current_price)}` : "";
  return { title: p.name, description: `${p.name}${price}. ${p.deal_label_text}. Price history and Amazon vs Flipkart comparison.` };
}

const FACTOR_LABELS: Record<string, string> = {
  historical_advantage: "Price vs typical price", recent_drop: "Recent price drop", distance_from_low: "Closeness to lowest price",
  product_quality: "Ratings & reviews", seller_reliability: "Seller reliability", available_offers: "Extra offers", price_stability: "Price stability",
  spec_value: "Performance per rupee", quality: "Ratings & reviews", historical_pricing: "Price vs its history",
};

function FactorBars({ title, factors }: { title: string; factors: Factor[] }) {
  return (
    <div>
      <h3 className="mb-2 font-bold">{title}</h3>
      <ul className="space-y-2">
        {factors.map((f) => (
          <li key={f.key}>
            <div className="flex justify-between gap-2 text-sm">
              <span>{FACTOR_LABELS[f.key] ?? f.key} <span className="text-muted">({Math.round(f.weight * 100)}% of score)</span></span>
              <span className="font-bold tabular">{f.score == null ? "Not available" : `${Math.round(f.score)}/100`}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
              <div className="h-full rounded-full bg-primary" style={{ width: `${f.score ?? 0}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default async function ProductPage({ params }: Props) {
  const { id } = await params;
  const p = await loadProduct(id);
  if (!p) return <ErrorState title="We couldn't load this product" />;

  const [history, comparison, favorites, user] = await Promise.all([
    tryApi<PriceHistory>(`/api/products/${id}/prices`, { query: { days: 90 }, revalidate: 60 }),
    tryApi<Comparison>(`/api/products/${id}/compare`, { revalidate: 30 }),
    getFavoriteIds(),
    getUser(),
  ]);

  const scored = p.deal_score != null;
  const good = (p.deal_score ?? 0) >= 70;
  const live = p.platforms.filter((x) => x.price != null);
  const d = p.discount;
  const dealFactors = p.score_breakdown?.deal?.factors ?? [];
  const valueFactors = p.score_breakdown?.value?.factors ?? [];

  return (
    <article className="space-y-8">
      <nav aria-label="Breadcrumb" className="text-sm text-muted">
        <ol className="flex flex-wrap gap-2">
          <li><Link href="/" className="underline-offset-4 hover:underline">Home</Link></li><li aria-hidden="true">/</li>
          {p.category && <><li><Link href={`/category/${p.category}`} className="underline-offset-4 hover:underline">{categoryTitle(p.category).replace(/ deals$/, "")}</Link></li><li aria-hidden="true">/</li></>}
          <li aria-current="page" className="wrap-anywhere">{p.name}</li>
        </ol>
      </nav>

      <div className="grid gap-8 lg:grid-cols-[1fr_24rem]">
        {/* min-w-0: a grid item won't shrink below its content (the comparison table) otherwise */}
        <div className="min-w-0 space-y-8">
          <header className="grid gap-5 md:grid-cols-[14rem_1fr]">
            <ProductImage src={p.image_url} name={p.name} brand={p.brand} category={p.category} className="h-28 md:h-52" />
            <div>
              <p className="text-sm font-bold uppercase tracking-wide text-muted">{p.brand}</p>
              <h1 className="mt-1 text-2xl font-bold wrap-anywhere md:text-4xl">{p.name}</h1>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <DealBadge label={p.deal_label} score={p.deal_score} />
                {p.rating != null && <span className="text-sm text-muted"><strong className="text-fg">{p.rating.toFixed(1)}</strong>/5 · {p.review_count?.toLocaleString("en-IN")} reviews</span>}
              </div>
              <div className="mt-4 flex items-center gap-4">
                <ScoreRing score={p.deal_score} label={p.deal_label} size={72} />
                <div>
                  {scored ? (
                    <>
                      <p className="text-lg font-bold">Deal score {Math.round(p.deal_score!)}/100</p>
                      {p.value_score != null && <p className="text-muted">Value score {Math.round(p.value_score)}/100</p>}
                    </>
                  ) : <p className="max-w-sm font-semibold">{p.note ?? "Not enough historical data yet"}</p>}
                </div>
              </div>
            </div>
          </header>

          {/* Honest discount: what the seller shows vs what the history supports. */}
          {d && d.advertised_pct != null && (
            <section aria-labelledby="disc" className={`rounded-2xl p-4 ${d.is_misleading ? "bg-warn-soft text-warn-fg" : "bg-surface-2"}`}>
              <h2 id="disc" className="flex items-center gap-2 font-bold">
                {d.is_misleading ? <AlertTriangle size={20} aria-hidden="true" /> : <Info size={20} aria-hidden="true" />}
                Advertised discount vs real saving
              </h2>
              <dl className="mt-2 grid gap-3 sm:grid-cols-3">
                <div><dt className="text-sm opacity-80">Seller shows</dt><dd className="text-xl font-bold tabular">{formatPct(d.advertised_pct)} off</dd></div>
                <div><dt className="text-sm opacity-80">Typical selling price</dt><dd className="text-xl font-bold tabular">{formatINR(d.typical_price)}</dd></div>
                <div><dt className="text-sm opacity-80">Real saving vs typical</dt><dd className="text-xl font-bold tabular">{d.real_saving != null ? `${formatINR(d.real_saving)} (${formatPct(d.real_saving_pct)})` : "Not enough history"}</dd></div>
              </dl>
              {d.is_misleading && <p className="mt-2 text-sm font-semibold">The advertised discount is measured from the MRP, which overstates the real saving.</p>}
            </section>
          )}

          <section aria-labelledby="why">
            <h2 id="why" className="mb-3 text-2xl font-bold">{good ? "Why this is a good deal" : scored ? "What the price history says" : "Price history"}</h2>
            {p.explanation.length > 0 ? (
              <ul className="space-y-2">
                {p.explanation.map((e) => (
                  <li key={e.code} className="flex items-start gap-2">
                    {e.positive ? <Check size={20} className="mt-0.5 shrink-0 text-primary" aria-label="Positive" /> : <AlertTriangle size={20} className="mt-0.5 shrink-0 text-warn-fg" aria-label="Caution" />}
                    <span>{e.text}</span>
                  </li>
                ))}
              </ul>
            ) : <Notice>{p.note ?? "Not enough historical data yet"}. Reasons appear here once there is enough price history.</Notice>}
          </section>

          <section aria-labelledby="chart">
            <h2 id="chart" className="mb-3 text-2xl font-bold">Price history</h2>
            {history ? <PriceChart productId={p.id} initial={history.data} /> : <ErrorState title="Price history is unavailable right now" />}
          </section>

          {comparison && comparison.data.platforms.length > 0 && (
            <section aria-labelledby="cmp">
              <h2 id="cmp" className="mb-1 text-2xl font-bold">Amazon vs Flipkart</h2>
              <p className="mb-3 text-muted">{comparison.data.summary}</p>
              <PlatformTable comparison={comparison.data} />
            </section>
          )}

          {Object.keys(p.specifications).length > 0 && (
            <section aria-labelledby="specs">
              <h2 id="specs" className="mb-3 text-2xl font-bold">Specifications</h2>
              <dl className="card grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0">
                {Object.entries(p.specifications).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4 border-line px-4 py-3 sm:border-b">
                    <dt className="font-semibold capitalize text-muted">{k.replace(/_/g, " ")}</dt><dd className="text-right font-semibold wrap-anywhere">{v}</dd>
                  </div>
                ))}
                {p.model_number && <div className="flex justify-between gap-4 px-4 py-3"><dt className="font-semibold text-muted">Model</dt><dd className="font-semibold">{p.model_number}</dd></div>}
              </dl>
            </section>
          )}

          {(dealFactors.length > 0 || valueFactors.length > 0) && (
            <section aria-labelledby="how">
              <details className="card p-4">
                <summary className="flex min-h-11 cursor-pointer items-center text-xl font-bold" id="how">How these scores are calculated</summary>
                <div className="mt-4 grid gap-6 md:grid-cols-2">
                  {dealFactors.length > 0 && <FactorBars title="Deal score" factors={dealFactors} />}
                  {valueFactors.length > 0 && <FactorBars title="Value score" factors={valueFactors} />}
                </div>
                <p className="mt-4 text-sm text-muted">Factors we can&apos;t measure are left out and the rest re-weighted, never guessed. The seller&apos;s advertised discount is not part of the deal score.</p>
              </details>
            </section>
          )}
        </div>

        {/* Purchase panel */}
        <aside aria-label="Buy and alerts" className="lg:sticky lg:top-24 lg:self-start">
          <div className="card space-y-4 p-5">
            <div>
              <p className="text-sm text-muted">Best price</p>
              <p className="font-display text-4xl font-bold tabular">{formatINR(p.current_price)}</p>
              {p.previous_price != null && p.current_price != null && p.previous_price > p.current_price && (
                <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
                  <span className="line-through tabular"><span className="sr-only">Previous price </span>{formatINR(p.previous_price)}</span>
                  <span className="badge bg-primary-soft text-fg"><TrendingDown size={14} aria-hidden="true" /> {formatPct(p.price_drop_pct)} drop</span>
                </p>
              )}
              <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                <div><dt className="text-muted">Typical price</dt><dd className="font-bold tabular">{formatINR(p.typical_price)}</dd></div>
                <div><dt className="text-muted">Lowest tracked</dt><dd className="font-bold tabular">{formatINR(p.historical_low)}</dd></div>
              </dl>
              <Freshness updatedAt={p.price_updated_at} isStale={p.is_stale} className="mt-3" />
            </div>

            <div className="space-y-2">
              {live.length === 0 && <p className="rounded-xl bg-surface-2 p-3 text-center font-semibold">Currently unavailable on tracked stores</p>}
              {live.map((pl) => (
                <a key={pl.platform} href={pl.buy_url ?? "#"} target="_blank" rel="sponsored noopener noreferrer"
                  className={`btn w-full justify-between ${pl.platform === p.best_platform ? "btn-accent" : "btn-outline"}`}>
                  <span>BUY NOW on {platformName(pl.platform)}</span>
                  <span className="flex items-center gap-2 tabular">{formatINR(pl.price)}<ExternalLink size={16} aria-hidden="true" /><span className="sr-only">(opens in a new tab)</span></span>
                </a>
              ))}
              {live.some((x) => x.is_affiliate_link) ? (
                <p className="text-xs text-muted">Buy links marked for {live.filter((x) => x.is_affiliate_link).map((x) => platformName(x.platform)).join(" and ")} are affiliate links: we may earn a commission at no extra cost to you.</p>
              ) : live.length > 0 ? <p className="text-xs text-muted">These are direct product links.</p> : null}
            </div>

            <div className="flex items-center gap-2 border-t border-line pt-4">
              <FavoriteButton productId={p.id} initial={favorites.has(p.id)} signedIn={!!user} name={p.name} />
              <span className="text-sm font-semibold">Save</span>
              <span className="ml-auto"><CompareToggle productId={p.id} name={p.name} /></span>
            </div>
          </div>

          <Link
            href={`/assistant?product=${p.id}&q=${encodeURIComponent("Is this actually a good deal, and should I buy now or wait?")}`}
            className="btn btn-outline mt-4 w-full"
          >
            <Bot size={18} aria-hidden="true" /> Ask the assistant about this
          </Link>

          <div className="card mt-4 p-5">
            <h2 className="mb-3 text-lg font-bold">Set a price alert</h2>
            <AlertForm productId={p.id} productName={p.name} currentPrice={p.current_price} historicalLow={p.historical_low}
              platforms={p.platforms.map((x) => x.platform)} signedIn={!!user} />
          </div>
        </aside>
      </div>
      {/* Phones: keep the main action in reach without scrolling to the bottom. */}
      {live.length > 0 && p.buy_url && p.best_platform && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 p-3 backdrop-blur lg:hidden">
          <div className="container-page flex items-center gap-3 !px-0">
            <div className="min-w-0">
              <p className="font-display text-xl font-bold leading-none tabular">{formatINR(p.current_price)}</p>
              <p className="mt-1 truncate text-xs text-muted">Lowest on {platformName(p.best_platform)}</p>
            </div>
            <a href={p.buy_url} target="_blank" rel="sponsored noopener noreferrer" className="btn btn-accent ml-auto whitespace-nowrap">
              BUY NOW <ExternalLink size={16} aria-hidden="true" /><span className="sr-only"> on {platformName(p.best_platform)} (opens in a new tab)</span>
            </a>
          </div>
        </div>
      )}
    </article>
  );
}
