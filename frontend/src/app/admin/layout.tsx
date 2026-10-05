import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { AdminNav } from "@/components/AdminNav";
import { getUser } from "@/lib/session";

export const metadata: Metadata = { title: { default: "Admin", template: "%s · Admin" }, robots: { index: false, follow: false } };

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await getUser();
  if (!user) redirect("/login?next=%2Fadmin");
  // Non-admins get a plain 404 rather than a hint that an admin area exists. The API enforces this too.
  if (!user.is_admin) notFound();
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-bold uppercase tracking-wide text-muted">Administration</p>
        <AdminNav />
      </div>
      {children}
    </div>
  );
}
