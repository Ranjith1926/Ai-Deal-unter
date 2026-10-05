import type { Metadata } from "next";
import { Browse } from "@/components/Browse";
import type { Params } from "@/components/FilterPanel";

export const metadata: Metadata = { title: "All deals", description: "Every tracked product, ranked by how good the price really is." };

export default async function DealsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  return (
    <Browse
      basePath="/deals" params={params}
      heading={<div><h1 className="text-3xl font-bold md:text-4xl">All deals</h1><p className="mt-1 max-w-2xl text-muted">Ranked by deal score, which compares today&apos;s price with each product&apos;s own price history. Products without enough history are listed after scored ones.</p></div>}
    />
  );
}
