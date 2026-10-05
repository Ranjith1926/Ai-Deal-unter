"use client";

import { Heart } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { flashAndReload } from "./Flash";

export function FavoriteButton({ productId, initial, signedIn, name }: { productId: number; initial: boolean; signedIn: boolean; name: string }) {
  const [saved, setSaved] = useState(initial);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const pathname = usePathname();

  async function toggle() {
    if (!signedIn) {
      router.push(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    const next = !saved;
    setSaved(next); // optimistic
    setError(null);
    const res = await fetch(`/bff/me/favorites/products/${productId}`, { method: next ? "PUT" : "DELETE" }).catch(() => null);
    if (!res?.ok) {
      setSaved(!next);
      setError("Couldn't update favourites. Please try again.");
      return;
    }
    // On the favourites page a removed product must disappear; elsewhere only this button changes.
    if (!next && pathname === "/favorites") { flashAndReload("Removed from favourites."); return; }
    startTransition(() => router.refresh());
  }

  return (
    <>
      <button
        type="button" onClick={toggle} disabled={pending} aria-pressed={saved}
        aria-label={saved ? `Remove ${name} from favourites` : `Save ${name} to favourites`}
        className="btn btn-ghost btn-icon rounded-full bg-surface/90 shadow-card"
      >
        <Heart size={20} aria-hidden="true" fill={saved ? "currentColor" : "none"} className={saved ? "text-danger" : ""} />
      </button>
      <span role="status" className="sr-only">{error ?? (saved ? "Saved to favourites" : "")}</span>
    </>
  );
}
