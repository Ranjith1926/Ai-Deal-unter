import Link from "next/link";
import { Info } from "lucide-react";

export function Footer() {
  return (
    <footer className="mt-12 border-t border-line bg-surface">
      <div className="container-page grid gap-8 py-10 md:grid-cols-3">
        <div>
          <p className="font-display text-lg font-bold">Deal<span className="text-primary">Hunter</span></p>
          <p className="mt-2 max-w-xs text-sm text-muted">
            We track Amazon India and Flipkart prices over time, so you can tell a genuine deal from a marked-up discount.
          </p>
        </div>
        <nav aria-label="Footer" className="text-sm">
          <p className="font-bold">Explore</p>
          <ul className="mt-2 space-y-1">
            {[["/deals", "All deals"], ["/compare", "Compare products"], ["/alerts", "Price alerts"], ["/favorites", "Favourites"]].map(([href, label]) => (
              <li key={href}><Link href={href} className="inline-flex min-h-8 items-center underline-offset-4 hover:underline">{label}</Link></li>
            ))}
          </ul>
        </nav>
        <div className="text-sm">
          <p className="flex items-center gap-1.5 font-bold"><Info size={16} aria-hidden="true" /> How we work</p>
          <ul className="mt-2 space-y-2 text-muted">
            <li>Scores come from stored price history, not the seller&apos;s stated discount.</li>
            <li>Where history is too short we say so instead of guessing.</li>
            <li>Some buy links may earn us a commission at no extra cost to you. Links that do are marked as affiliate links on the product page.</li>
          </ul>
        </div>
      </div>
      <p className="border-t border-line py-4 text-center text-xs text-muted">
        Prices and availability change quickly; always confirm on the store before you buy.
      </p>
    </footer>
  );
}
