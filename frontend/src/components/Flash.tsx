"use client";

import { CheckCircle2, X } from "lucide-react";
import { useEffect, useState } from "react";

const KEY = "dh_flash";

/**
 * Reload the page and show `text` once it has loaded. Used after changes that alter what the
 * server renders (admin settings, deleted alerts, a renamed account). A reload is deterministic;
 * relying on the client router to re-render server components proved unreliable for repeated
 * refreshes of the same page.
 */
export function flashAndReload(text: string): void {
  try { sessionStorage.setItem(KEY, text); } catch { /* storage unavailable: just reload */ }
  window.location.reload();
}

export function FlashMessage() {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(KEY);
      if (saved) {
        sessionStorage.removeItem(KEY);
        setText(saved);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!text) return;
    const t = setTimeout(() => setText(null), 8000);
    return () => clearTimeout(t);
  }, [text]);

  if (!text) return <div role="status" aria-live="polite" />;
  return (
    <div role="status" aria-live="polite" className="fixed inset-x-0 top-3 z-50 flex justify-center px-4">
      <p className="flex max-w-xl items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 font-semibold shadow-pop">
        <CheckCircle2 size={20} className="shrink-0 text-primary" aria-hidden="true" />
        <span>{text}</span>
        <button type="button" className="btn btn-ghost btn-icon !min-h-8 !min-w-8 !p-0" onClick={() => setText(null)} aria-label="Dismiss message"><X size={16} aria-hidden="true" /></button>
      </p>
    </div>
  );
}
