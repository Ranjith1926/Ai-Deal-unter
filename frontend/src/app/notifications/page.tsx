import type { Metadata } from "next";
import Link from "next/link";
import { InboxList } from "@/components/InboxList";
import { EmptyState, ErrorState } from "@/components/States";
import { tryApi } from "@/lib/api";
import { requireUser } from "@/lib/session";
import type { Inbox } from "@/lib/types";

export const metadata: Metadata = { title: "Notifications", robots: { index: false } };

export default async function NotificationsPage() {
  await requireUser("/notifications");
  const res = await tryApi<Inbox>("/api/me/notifications", { auth: true });
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-3xl font-bold md:text-4xl">Notifications</h1>
        <p className="mt-1 text-muted">
          Every price alert lands here, whatever other channels you use. Choose email, push or Telegram in your{" "}
          <Link href="/profile" className="font-semibold underline">profile</Link>.
        </p>
      </div>
      {!res ? <ErrorState /> : res.data.items.length === 0 ? (
        <EmptyState title="Nothing here yet" action={{ href: "/alerts", label: "See your price alerts" }}>
          When a product you&apos;re watching reaches your target price, we&apos;ll tell you here.
        </EmptyState>
      ) : <InboxList inbox={res.data} />}
    </div>
  );
}
