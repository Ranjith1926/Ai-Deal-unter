"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function LogoutButton({ className = "btn btn-ghost btn-sm" }: { className?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    await fetch("/bff/session/logout", { method: "POST" }).catch(() => null);
    router.push("/");
    router.refresh();
  }

  return (
    <button type="button" onClick={signOut} disabled={busy} className={className}>
      <LogOut size={16} aria-hidden="true" /> {busy ? "Signing out…" : "Sign out"}
    </button>
  );
}
