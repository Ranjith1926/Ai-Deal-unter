"use client";

import { BellOff, BellRing, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

type State = "checking" | "unsupported" | "denied" | "off" | "on";

function keyBytes(base64url: string): Uint8Array {
  const padded = (base64url + "===".slice((base64url.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration("/");
  return (await reg?.pushManager.getSubscription()) ?? null;
}

/** Turns push notifications on or off for *this* browser. Each device subscribes separately. */
export function PushDevice({ vapidPublicKey }: { vapidPublicKey: string }) {
  const [state, setState] = useState<State>("checking");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      setState("unsupported");
      return;
    }
    if (Notification.permission === "denied") { setState("denied"); return; }
    currentSubscription().then((sub) => setState(sub ? "on" : "off")).catch(() => setState("off"));
  }, []);

  async function turnOn() {
    setBusy(true); setError(null);
    try {
      if ((await Notification.requestPermission()) !== "granted") { setState("denied"); return; }
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      const sub = (await reg.pushManager.getSubscription())
        ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(vapidPublicKey) as BufferSource }));
      const json = sub.toJSON();
      const res = await fetch("/bff/me/push-subscriptions", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        await sub.unsubscribe().catch(() => null);
        throw new Error(body?.message ?? "The server did not accept this browser");
      }
      setState("on");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't turn on push notifications");
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true); setError(null);
    try {
      const sub = await currentSubscription();
      if (sub) {
        await fetch("/bff/me/push-subscriptions/remove", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ endpoint: sub.endpoint }),
        });
        await sub.unsubscribe();
      }
      setState("off");
    } catch {
      setError("Couldn't turn off push notifications");
    } finally {
      setBusy(false);
    }
  }

  if (state === "checking") return null;
  if (state === "unsupported") return <p className="hint">This browser doesn&apos;t support push notifications.</p>;
  if (state === "denied") return <p className="hint">Notifications are blocked for this site. Allow them in your browser&apos;s site settings, then reload.</p>;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      {state === "on" ? (
        <button type="button" onClick={turnOff} disabled={busy} className="btn btn-outline btn-sm">
          {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <BellOff size={16} aria-hidden="true" />} Turn off on this device
        </button>
      ) : (
        <button type="button" onClick={turnOn} disabled={busy} className="btn btn-outline btn-sm">
          {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <BellRing size={16} aria-hidden="true" />} Turn on for this device
        </button>
      )}
      <span role="status" className={`text-sm ${error ? "font-semibold text-danger" : "text-muted"}`}>
        {error ?? (state === "on" ? "This device will receive push alerts." : "This device is not receiving push alerts.")}
      </span>
    </div>
  );
}
