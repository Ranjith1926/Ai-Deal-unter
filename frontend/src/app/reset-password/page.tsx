import type { Metadata } from "next";
import Link from "next/link";
import { AuthForm } from "@/components/AuthForm";
import { AuthShell } from "@/components/AuthShell";
import { one, type Params } from "@/components/FilterPanel";
import { Notice } from "@/components/States";

export const metadata: Metadata = { title: "Choose a new password", robots: { index: false } };

export default async function ResetPasswordPage({ searchParams }: { searchParams: Promise<Params> }) {
  const token = one((await searchParams).token);
  return (
    <AuthShell title="Choose a new password" footer={<Link href="/login" className="font-bold text-primary underline underline-offset-4">Back to sign in</Link>}>
      {token ? <AuthForm mode="reset" token={token} /> : <Notice tone="warn">This reset link is missing its token. Request a new link from the “Forgot password?” page.</Notice>}
    </AuthShell>
  );
}
