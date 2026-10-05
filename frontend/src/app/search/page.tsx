import type { Metadata } from "next";
import { Search } from "lucide-react";
import { Browse } from "@/components/Browse";
import { one, type Params } from "@/components/FilterPanel";

export async function generateMetadata({ searchParams }: { searchParams: Promise<Params> }): Promise<Metadata> {
  const q = one((await searchParams).q);
  return { title: q ? `Search: ${q}` : "Search", robots: { index: false } };
}

export default async function SearchPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const q = one(params.q)?.trim();
  if (!q) {
    return (
      <div className="mx-auto max-w-xl py-10 text-center">
        <Search size={36} className="mx-auto text-muted" aria-hidden="true" />
        <h1 className="mt-3 text-3xl font-bold">Search products</h1>
        <form action="/search" role="search" className="mt-5 flex gap-2">
          <label htmlFor="q" className="sr-only">Search products</label>
          <input id="q" name="q" type="search" required className="input" placeholder="Try “Samsung TV” or “laptop under 50000”" autoComplete="off" />
          <button className="btn btn-primary" type="submit">Search</button>
        </form>
      </div>
    );
  }
  return (
    <Browse
      basePath="/search" params={params}
      heading={<h1 className="text-3xl font-bold md:text-4xl">Results for “<span className="wrap-anywhere">{q}</span>”</h1>}
    />
  );
}
