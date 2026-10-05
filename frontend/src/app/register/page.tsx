import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";
import { AuthShell } from "@/components/AuthShell";
import { one, type Params } from "@/components/FilterPanel";
import { getUser } from "@/lib/session";

export const metadata: Metadata = { title: "Create account", robots: { index: false } };

export default async function RegisterPage({ searchParams }: { searchParams: Promise<Params> }) {
  const next = one((await searchParams).next);
  if (await getUser()) redirect("/");
  const q = next ? `?next=${encodeURIComponent(next)}` : "";
  return (
    <AuthShell title="Create your account" subtitle="Free. Get price alerts and save products you're watching."
      footer={<>Already have an account? <Link href={`/login${q}`} className="font-bold text-primary underline underline-offset-4">Sign in</Link></>}>
      <AuthForm mode="register" next={next} />
    </AuthShell>
  );
}
