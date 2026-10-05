import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Browse } from "@/components/Browse";
import type { Params } from "@/components/FilterPanel";
import { tryApi } from "@/lib/api";
import { categoryTitle } from "@/lib/format";
import type { Category } from "@/lib/types";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  return { title: categoryTitle(slug) };
}

export default async function CategoryPage({ params, searchParams }: { params: Promise<{ slug: string }>; searchParams: Promise<Params> }) {
  const { slug } = await params;
  const query = await searchParams;
  const cats = await tryApi<Category[]>("/api/categories", { revalidate: 300 });
  if (cats && !cats.data.some((c) => c.slug === slug)) notFound();
  return (
    <Browse
      basePath={`/category/${slug}`} params={query} fixed={{ category: slug }} lockCategory
      heading={
        <div>
          <nav aria-label="Breadcrumb" className="text-sm text-muted">
            <ol className="flex gap-2"><li><Link href="/" className="underline-offset-4 hover:underline">Home</Link></li><li aria-hidden="true">/</li><li aria-current="page">{categoryTitle(slug).replace(/ deals$/, "")}</li></ol>
          </nav>
          <h1 className="mt-1 text-3xl font-bold md:text-4xl">{categoryTitle(slug)}</h1>
        </div>
      }
    />
  );
}
