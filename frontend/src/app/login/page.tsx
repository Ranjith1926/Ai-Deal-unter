import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";
import { AuthShell } from "@/components/AuthShell";
import { one, type Params } from "@/components/FilterPanel";
import { getUser } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in", robots: { index: false } };

export default async function LoginPage({ searchParams }: { searchParams: Promise<Params> }) {
  const next = one((await searchParams).next);
  if (await getUser()) redirect(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
  const q = next ? `?next=${encodeURIComponent(next)}` : "";
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to manage price alerts and favourites."
      footer={<>New here? <Link href={`/register${q}`} className="font-bold text-primary underline underline-offset-4">Create an account</Link></>}>
      <AuthForm mode="login" next={next} />
    </AuthShell>
  );
}
