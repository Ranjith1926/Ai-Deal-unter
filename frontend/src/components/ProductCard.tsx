import Link from "next/link";
import { ExternalLink, Star, TrendingDown } from "lucide-react";
import { CompareToggle } from "./Compare";
import { DealBadge, ScoreRing } from "./DealBadge";
import { FavoriteButton } from "./FavoriteButton";
import { Freshness } from "./Freshness";
import { ProductImage } from "./ProductImage";
import { formatINR, formatPct, platformName } from "@/lib/format";
import type { ProductCard as Card } from "@/lib/types";

interface Props { product: Card; favorite?: boolean; signedIn?: boolean; priority?: boolean }

/**
 * One deal. Shows the live price against the product's own history, never just the seller's
 * claimed discount, and says plainly when there isn't enough history to score it.
 */
export function ProductCard({ product: p, favorite = false, signedIn = false }: Props) {
  const scored = p.deal_score != null;
  const hasDrop = p.previous_price != null && p.current_price != null && p.previous_price > p.current_price;
  const live = p.platforms.filter((x) => x.price != null);

  return (
    <article className="card card-link relative flex h-full flex-col overflow-hidden p-3">
      <div className="relative">
        <ProductImage src={p.image_url} name={p.name} brand={p.brand} category={p.category} />
        <div className="absolute right-2 top-2 z-10">
          <FavoriteButton productId={p.id} initial={favorite} signedIn={signedIn} name={p.name} />
        </div>
        <div className="absolute left-2 top-2">
          <DealBadge label={p.deal_label} score={p.deal_score} className="shadow-card" />
        </div>
      </div>

      <div className="mt-3 flex flex-1 flex-col gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-muted">{p.brand}</p>
          <h3 className="text-base font-bold leading-snug">
            {/* Stretched link: the whole card opens the product, while Buy/Favourite stay separate. */}
            <Link href={`/deals/${p.id}`} className="line-clamp-2 wrap-anywhere after:absolute after:inset-0 after:content-[''] focus-visible:after:rounded-2xl">
              {p.name}
            </Link>
          </h3>
        </div>

        <div>
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-display text-2xl font-bold tabular">{formatINR(p.current_price)}</span>
            {hasDrop && <span className="text-sm text-muted line-through tabular"><span className="sr-only">Previous price </span>{formatINR(p.previous_price)}</span>}
            {hasDrop && p.price_drop_pct != null && (
              <span className="badge bg-primary-soft text-fg"><TrendingDown size={14} aria-hidden="true" />{formatPct(p.price_drop_pct)} drop</span>
            )}
          </div>
          {p.current_price == null && <p className="text-sm text-muted">Currently unavailable</p>}
        </div>

        {(p.typical_price != null || p.historical_low != null) && (
          <dl className="grid grid-cols-2 gap-2 rounded-xl bg-surface-2 px-3 py-2 text-sm">
            <div><dt className="text-xs text-muted">Typical price</dt><dd className="font-bold tabular">{formatINR(p.typical_price)}</dd></div>
            <div><dt className="text-xs text-muted">Lowest tracked</dt><dd className="font-bold tabular">{formatINR(p.historical_low)}</dd></div>
          </dl>
        )}

        {p.advertised_discount_pct != null && p.typical_price != null && p.current_price != null && (
          <p className="text-xs text-muted">
            Seller shows {formatPct(p.advertised_discount_pct)} off; vs its usual price it is{" "}
            <strong className="text-fg">{p.current_price < p.typical_price ? `${formatINR(p.typical_price - p.current_price)} cheaper` : "not cheaper"}</strong>.
          </p>
        )}

        {live.length > 0 && (
          <ul className="space-y-1 text-sm" aria-label="Price by store">
            {live.map((pl) => (
              <li key={pl.platform} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5">
                  {platformName(pl.platform)}
                  {pl.platform === p.best_platform && live.length > 1 && <span className="badge bg-primary-soft text-fg">Lowest</span>}
                </span>
                <span className="font-bold tabular">{formatINR(pl.price)}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-3">
          <ScoreRing score={p.deal_score} label={p.deal_label} />
          <div className="min-w-0 text-sm">
            {scored ? (
              <>
                <p className="font-bold">Deal score {Math.round(p.deal_score!)}/100</p>
                {p.value_score != null && <p className="text-muted">Value score {Math.round(p.value_score)}/100</p>}
              </>
            ) : (
              <p className="text-muted">{p.note ?? "Not enough historical data yet"}</p>
            )}
          </div>
        </div>

        {p.rating != null && (
          <p className="flex items-center gap-1 text-sm text-muted">
            <Star size={16} className="text-warn-fg" fill="currentColor" aria-hidden="true" />
            <span className="font-bold text-fg">{p.rating.toFixed(1)}</span>
            {p.review_count != null && <span>({p.review_count.toLocaleString("en-IN")} reviews)</span>}
          </p>
        )}
      </div>

      <div className="relative z-10 mt-3 space-y-2 border-t border-line pt-3">
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
          <Freshness updatedAt={p.price_updated_at} isStale={p.is_stale} className="min-w-0 flex-1" />
          <CompareToggle productId={p.id} name={p.name} />
        </div>
        {p.buy_url && p.best_platform ? (
          <a href={p.buy_url} target="_blank" rel="sponsored noopener noreferrer" className="btn btn-accent w-full whitespace-nowrap">
            BUY NOW <span className="font-sans text-xs font-semibold">on {platformName(p.best_platform)}</span>
            <ExternalLink size={16} aria-hidden="true" /><span className="sr-only"> (opens {platformName(p.best_platform)} in a new tab)</span>
          </a>
        ) : (
          <span className="btn btn-outline w-full" aria-disabled="true">Unavailable</span>
        )}
      </div>
    </article>
  );
}
