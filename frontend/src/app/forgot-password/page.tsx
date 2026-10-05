import type { Metadata } from "next";
import Link from "next/link";
import { AuthForm } from "@/components/AuthForm";
import { AuthShell } from "@/components/AuthShell";

export const metadata: Metadata = { title: "Reset password", robots: { index: false } };

export default function ForgotPasswordPage() {
  return (
    <AuthShell title="Reset your password" subtitle="Enter your email and we'll send you a link to choose a new one."
      footer={<Link href="/login" className="font-bold text-primary underline underline-offset-4">Back to sign in</Link>}>
      <AuthForm mode="forgot" />
    </AuthShell>
  );
}
