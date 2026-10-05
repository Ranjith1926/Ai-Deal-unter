import type { Metadata } from "next";
import { ProductGrid } from "@/components/ProductGrid";
import { EmptyState, ErrorState } from "@/components/States";
import { tryApi } from "@/lib/api";
import { requireUser } from "@/lib/session";
import type { ProductCard } from "@/lib/types";

export const metadata: Metadata = { title: "Favourites", robots: { index: false } };

export default async function FavoritesPage() {
  await requireUser("/favorites");
  const res = await tryApi<ProductCard[]>("/api/me/favorites/products", { auth: true });
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl font-bold md:text-4xl">Your favourites</h1>
        <p className="mt-1 text-muted">Products you&apos;re keeping an eye on, with their latest prices.</p>
      </div>
      {!res ? <ErrorState /> : res.data.length === 0 ? (
        <EmptyState title="Nothing saved yet" action={{ href: "/deals", label: "Browse deals" }}>
          Tap the heart on any product to keep it here.
        </EmptyState>
      ) : <ProductGrid products={res.data} favorites={new Set(res.data.map((p) => p.id))} signedIn />}
    </div>
  );
}
