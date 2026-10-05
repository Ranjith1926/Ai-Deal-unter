import { ExternalLink } from "lucide-react";
import { Freshness } from "./Freshness";
import { formatINR, platformName } from "@/lib/format";
import type { Comparison, Offer } from "@/lib/types";

const NA = <span className="text-muted">Not provided</span>;

function offers(list: Offer[]) {
  if (list.length === 0) return <span className="text-muted">None listed</span>;
  return (
    <ul className="space-y-1">
      {list.map((o, i) => (
        <li key={i}>{o.description}{o.discount_amount != null && <strong className="tabular"> ({formatINR(o.discount_amount)})</strong>}</li>
      ))}
    </ul>
  );
}

/** Store-by-store comparison. Fields the data sources don't give are labelled, never invented. */
export function PlatformTable({ comparison: c }: { comparison: Comparison }) {
  return (
    <div className="relative overflow-x-auto rounded-2xl border border-line bg-surface">
      <table className="w-full min-w-[34rem] text-left">
        <caption className="sr-only">Comparison of {c.product_name} across stores</caption>
        <thead>
          <tr className="bg-surface-2">
            <td className="px-4 py-3"><span className="sr-only">Feature</span></td>
            {c.platforms.map((p) => (
              <th key={p.platform} scope="col" className="px-4 py-3 font-display text-lg">
                {platformName(p.platform)}
                {p.platform === c.best_platform && c.platforms.length > 1 && <span className="badge ml-2 bg-primary-soft align-middle text-fg">Lowest price</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&_td]:px-4 [&_td]:py-3 [&_th]:px-4 [&_th]:py-3 [&_tr]:border-t [&_tr]:border-line align-top">
          <tr><th scope="row" className="font-semibold text-muted">Price</th>{c.platforms.map((p) => <td key={p.platform} className="font-display text-xl font-bold tabular">{p.price != null ? formatINR(p.price) : <span className="text-base font-semibold text-muted">Unavailable</span>}</td>)}</tr>
          <tr><th scope="row" className="font-semibold text-muted">MRP</th>{c.platforms.map((p) => <td key={p.platform} className="tabular">{p.mrp != null ? formatINR(p.mrp) : NA}</td>)}</tr>
          <tr><th scope="row" className="font-semibold text-muted">Difference</th>{c.platforms.map((p) => <td key={p.platform} className="tabular">{p.difference_vs_cheapest == null ? "—" : p.difference_vs_cheapest === 0 ? <strong>Cheapest</strong> : `+${formatINR(p.difference_vs_cheapest)}`}</td>)}</tr>
          <tr><th scope="row" className="font-semibold text-muted">Seller</th>{c.platforms.map((p) => <td key={p.platform}>{p.seller ?? NA}</td>)}</tr>
          <tr><th scope="row" className="font-semibold text-muted">Bank offers</th>{c.platforms.map((p) => <td key={p.platform}>{offers(p.bank_offers)}</td>)}</tr>
          <tr><th scope="row" className="font-semibold text-muted">Exchange offers</th>{c.platforms.map((p) => <td key={p.platform}>{offers(p.exchange_offers)}</td>)}</tr>
          <tr>
            <th scope="row" className="font-semibold text-muted">Price after offers <span className="block text-xs font-normal">Estimate</span></th>
            {c.platforms.map((p) => <td key={p.platform} className="tabular">{p.price_after_offers != null ? <>{formatINR(p.price_after_offers)}<span className="block text-xs text-muted">Estimated; offers may need a specific card</span></> : "—"}</td>)}
          </tr>
          <tr><th scope="row" className="font-semibold text-muted">Shipping</th>{c.platforms.map((p) => <td key={p.platform}>{p.shipping ?? NA}</td>)}</tr>
          <tr><th scope="row" className="font-semibold text-muted">Warranty</th>{c.platforms.map((p) => <td key={p.platform}>{p.warranty ?? NA}</td>)}</tr>
          <tr><th scope="row" className="font-semibold text-muted">Data freshness</th>{c.platforms.map((p) => <td key={p.platform}><Freshness updatedAt={p.updated_at} isStale={p.is_stale} /></td>)}</tr>
          <tr>
            <th scope="row" className="font-semibold text-muted"><span className="sr-only">Buy</span></th>
            {c.platforms.map((p) => (
              <td key={p.platform}>
                {p.price != null && p.buy_url ? (
                  <a href={p.buy_url} target="_blank" rel="sponsored noopener noreferrer" className={`btn btn-sm ${p.platform === c.best_platform ? "btn-accent" : "btn-outline"}`}>
                    BUY ON {platformName(p.platform).toUpperCase()} <ExternalLink size={14} aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span>
                  </a>
                ) : <span className="text-muted">Unavailable</span>}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
