"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export const NAV = [
  { href: "/deals", label: "Deals" },
  { href: "/assistant", label: "Assistant" },
  { href: "/compare", label: "Compare" },
  { href: "/alerts", label: "Alerts" },
  { href: "/favorites", label: "Favourites" },
];

export function NavLinks({ className = "" }: { className?: string }) {
  const pathname = usePathname();
  return (
    <>
      {NAV.map((item) => {
        const current = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href} href={item.href} aria-current={current ? "page" : undefined}
            className={`rounded-lg px-3 py-2 font-semibold hover:bg-surface-2 aria-[current=page]:bg-primary-soft aria-[current=page]:text-fg ${className}`}
          >
            {item.label}
          </Link>
        );
      })}
    </>
  );
}
