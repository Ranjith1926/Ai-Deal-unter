import Link from "next/link";
import { AlertTriangle, Info, SearchX } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: { href: string; label: string } }) {
  return (
    <div className="card flex flex-col items-center gap-2 px-6 py-10 text-center">
      <SearchX size={32} className="text-muted" aria-hidden="true" />
      <h2 className="text-lg font-bold">{title}</h2>
      {children && <p className="max-w-prose text-muted">{children}</p>}
      {action && <Link href={action.href} className="btn btn-primary mt-2">{action.label}</Link>}
    </div>
  );
}

export function ErrorState({ title = "We couldn't load this right now", children }: { title?: string; children?: ReactNode }) {
  return (
    <div role="alert" className="card flex items-start gap-3 border-danger px-5 py-4">
      <AlertTriangle className="mt-0.5 shrink-0 text-danger" size={22} aria-hidden="true" />
      <div>
        <h2 className="font-bold">{title}</h2>
        <p className="text-muted">{children ?? "Please try again in a moment. Your data is safe."}</p>
      </div>
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return (
    <p className={`flex items-start gap-2 rounded-xl px-4 py-3 text-sm ${tone === "warn" ? "bg-warn-soft text-warn-fg" : "bg-surface-2 text-fg"}`}>
      {tone === "warn" ? <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden="true" /> : <Info size={18} className="mt-0.5 shrink-0" aria-hidden="true" />}
      <span>{children}</span>
    </p>
  );
}

export function CardSkeleton() {
  return (
    <div className="card p-4" aria-hidden="true">
      <div className="skeleton h-36 w-full" />
      <div className="skeleton mt-4 h-4 w-1/3" />
      <div className="skeleton mt-2 h-5 w-5/6" />
      <div className="skeleton mt-4 h-8 w-1/2" />
      <div className="skeleton mt-4 h-12 w-full" />
    </div>
  );
}

export function GridSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div role="status" aria-busy="true" aria-label="Loading deals" className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-4">
      {Array.from({ length: count }, (_, i) => <CardSkeleton key={i} />)}
    </div>
  );
}
