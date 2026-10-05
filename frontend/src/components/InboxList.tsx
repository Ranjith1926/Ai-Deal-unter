"use client";

import { CheckCheck, Loader2 } from "lucide-react";
import { useState } from "react";
import { formatDate } from "@/lib/format";
import type { Inbox, InboxItem } from "@/lib/types";

const URL_PATTERN = /(https:\/\/[^\s<>"']+)/g;

/** Plain text with https links made clickable. Nothing is parsed as HTML. */
function MessageText({ text }: { text: string }) {
  return (
    <p className="mt-1 break-words text-muted [overflow-wrap:anywhere]">
      {text.split(URL_PATTERN).map((part, i) =>
        i % 2 === 1
          ? <a key={i} href={part} target="_blank" rel="noopener noreferrer nofollow sponsored" className="font-semibold text-fg underline">View deal</a>
          : part)}
    </p>
  );
}

export function InboxList({ inbox }: { inbox: Inbox }) {
  const [items, setItems] = useState<InboxItem[]>(inbox.items);
  const [busy, setBusy] = useState(false);
  const unread = items.filter((n) => !n.is_read).length;

  async function markRead(id: number | null) {
    setBusy(id === null);
    const url = id === null ? "/bff/me/notifications/read" : `/bff/me/notifications/${id}/read`;
    const res = await fetch(url, { method: "POST" }).catch(() => null);
    setBusy(false);
    if (res?.ok) setItems((all) => all.map((n) => (id === null || n.id === id ? { ...n, is_read: true } : n)));
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p role="status" className="text-sm font-semibold">{unread === 0 ? "All caught up" : `${unread} unread`}</p>
        {unread > 0 && (
          <button type="button" onClick={() => markRead(null)} disabled={busy} className="btn btn-outline btn-sm">
            {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <CheckCheck size={16} aria-hidden="true" />} Mark all as read
          </button>
        )}
      </div>
      <ul className="space-y-3">
        {items.map((n) => (
          <li key={n.id} className={`card p-4 ${n.is_read ? "" : "border-primary"}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <h2 className="min-w-0 font-bold">
                {!n.is_read && <span className="mr-2 inline-block size-2 rounded-full bg-primary align-middle" aria-hidden="true" />}
                {n.title}
                {!n.is_read && <span className="sr-only"> (unread)</span>}
              </h2>
              <time className="text-sm text-muted" dateTime={n.created_at}>{formatDate(n.created_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</time>
            </div>
            <MessageText text={n.message} />
            {!n.is_read && (
              <button type="button" onClick={() => markRead(n.id)} className="btn btn-ghost btn-sm mt-2">Mark as read</button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
