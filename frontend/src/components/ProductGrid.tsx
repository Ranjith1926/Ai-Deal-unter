import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { ProductCard } from "./ProductCard";
import type { ProductCard as Card } from "@/lib/types";

export function ProductGrid({ products, favorites, signedIn }: { products: Card[]; favorites: Set<number>; signedIn: boolean }) {
  return (
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(16.5rem,1fr))] gap-4">
      {products.map((p) => (
        <li key={p.id}><ProductCard product={p} favorite={favorites.has(p.id)} signedIn={signedIn} /></li>
      ))}
    </ul>
  );
}

export function Section({ id, title, subtitle, href, linkLabel = "View all", children }: {
  id: string; title: string; subtitle?: string; href?: string; linkLabel?: string; children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="py-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id={id} className="text-2xl font-bold md:text-3xl">{title}</h2>
          {subtitle && <p className="mt-1 text-muted">{subtitle}</p>}
        </div>
        {href && (
          <Link href={href} className="inline-flex min-h-11 items-center gap-1 font-bold text-primary underline-offset-4 hover:underline">
            {linkLabel} <ArrowRight size={18} aria-hidden="true" />
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}
