"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/jobs", label: "Jobs" },
  { href: "/admin/catalog", label: "Catalogue" },
  { href: "/admin/scoring", label: "Scoring" },
];

export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Admin sections" className="mt-1 flex flex-wrap gap-2">
      {TABS.map((t) => {
        const current = t.href === "/admin" ? pathname === "/admin" : pathname.startsWith(t.href);
        return <Link key={t.href} href={t.href} className="chip" aria-current={current ? "true" : undefined}>{t.label}</Link>;
      })}
    </nav>
  );
}
