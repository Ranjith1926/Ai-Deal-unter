import type { Metadata } from "next";
import Link from "next/link";
import { Bot } from "lucide-react";
import { AssistantChat } from "@/components/AssistantChat";
import { one, type Params } from "@/components/FilterPanel";
import { Notice } from "@/components/States";
import { tryApi } from "@/lib/api";
import { getUser } from "@/lib/session";
import type { ProductDetail } from "@/lib/types";

export const metadata: Metadata = { title: "Shopping assistant", description: "Ask an AI assistant to find, compare and judge deals using real price history." };

export default async function AssistantPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const [user, status] = await Promise.all([getUser(), tryApi<{ enabled: boolean }>("/api/assistant/status", { revalidate: 30 })]);
  const productId = /^\d+$/.test(one(params.product) ?? "") ? Number(one(params.product)) : undefined;
  const product = productId ? await tryApi<ProductDetail>(`/api/products/${productId}`, { revalidate: 30 }) : null;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="flex items-center gap-3 text-3xl font-bold md:text-4xl"><Bot size={34} className="text-primary" aria-hidden="true" /> Shopping assistant</h1>
        <p className="mt-1 text-muted">It uses the same price history and scores as the rest of the site, and tells you when there isn&apos;t enough data to be sure.</p>
      </div>

      {!user ? (
        <div className="card flex flex-col items-start gap-3 p-6">
          <p className="font-semibold">Sign in to chat with the assistant.</p>
          <p className="text-muted">It can also set and manage price alerts for you, so it needs to know who you are.</p>
          <div className="flex gap-2">
            <Link href="/login?next=%2Fassistant" className="btn btn-primary">Sign in</Link>
            <Link href="/register?next=%2Fassistant" className="btn btn-outline">Create account</Link>
          </div>
        </div>
      ) : status && !status.data.enabled ? (
        <Notice tone="warn">
          The assistant isn&apos;t switched on yet. An administrator needs to add an Anthropic API key to the server settings
          (<code>ANTHROPIC_API_KEY</code>). Everything else on the site works as normal.
        </Notice>
      ) : (
        <AssistantChat initialQuestion={one(params.q)} productId={product?.data.id} productName={product?.data.name} />
      )}
    </div>
  );
}
