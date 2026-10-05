"use client";

import { Loader2, Send } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { flashAndReload } from "./Flash";
import { PushDevice } from "./PushDevice";
import type { NotificationChannels, User } from "@/lib/types";

// In-app is not a choice: every alert is always kept in the notifications inbox.
const CHANNELS = [
  { key: "email", label: "Email", hint: "Sent to your account email." },
  { key: "push", label: "Push notifications", hint: "On this browser or phone; turn it on for each device." },
  { key: "telegram", label: "Telegram", hint: "Message our bot, then paste your chat ID below." },
] as const;
type ChannelKey = (typeof CHANNELS)[number]["key"];

function Status({ state }: { state: { ok: boolean; text: string } | null }) {
  return <p role="status" className={`text-sm font-semibold ${state?.ok ? "text-fg" : "text-danger"}`}>{state?.text}</p>;
}

export function ProfileForm({ user, available }: { user: User; available: NotificationChannels | null }) {
  const prefs = user.notification_preferences as Record<string, unknown>;
  const isAvailable = (key: ChannelKey) => Boolean(available?.[key]);
  const [name, setName] = useState(user.name);
  const [channels, setChannels] = useState<Record<string, boolean>>(
    Object.fromEntries(CHANNELS.map((c) => [c.key, Boolean(prefs[c.key])])),
  );
  const [chatId, setChatId] = useState(typeof prefs.telegram === "object" && prefs.telegram ? String((prefs.telegram as { chat_id?: string }).chat_id ?? "") : "");
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (isAvailable("telegram") && channels.telegram && !chatId.trim()) {
      setState({ ok: false, text: "Add your Telegram chat ID, or untick Telegram." });
      return;
    }
    setBusy(true); setState(null);
    const notification_preferences: Record<string, unknown> = {};
    for (const c of CHANNELS) notification_preferences[c.key] = c.key === "telegram" && channels.telegram && chatId.trim() ? { chat_id: chatId.trim() } : channels[c.key];
    const res = await fetch("/bff/me", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, notification_preferences }) }).catch(() => null);
    const body = await res?.json().catch(() => null);
    if (res?.ok) { flashAndReload("Saved."); return; }  // reload so the header shows the new name
    setBusy(false);
    setState({ ok: false, text: body?.errors?.[0] ?? body?.message ?? "Couldn't save your changes." });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      <div>
        <label htmlFor="p-name" className="label">Name</label>
        <input id="p-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required className="input" />
      </div>
      <div>
        <label htmlFor="p-email" className="label">Email</label>
        <input id="p-email" value={user.email} readOnly className="input bg-surface-2" aria-describedby="p-email-hint" />
        <p id="p-email-hint" className="hint">Your sign-in email can&apos;t be changed here.</p>
      </div>
      <fieldset>
        <legend className="label">How should we notify you about price alerts?</legend>
        <div className="space-y-2">
          {CHANNELS.map((c) => {
            const on = isAvailable(c.key);
            return (
              <div key={c.key} className={`rounded-xl border border-line p-3 ${on ? "" : "bg-surface-2"}`}>
                <label className={`flex min-h-11 items-start gap-3 ${on ? "cursor-pointer" : "cursor-not-allowed"}`}>
                  <input type="checkbox" className="mt-1 size-5 accent-[var(--primary)]" disabled={!on}
                    checked={on && channels[c.key]} onChange={(e) => setChannels((s) => ({ ...s, [c.key]: e.target.checked }))}
                    aria-describedby={`ch-${c.key}-hint`} />
                  <span>
                    <span className="font-bold">{c.label}</span>
                    <span id={`ch-${c.key}-hint`} className="block text-sm text-muted">{on ? c.hint : "Not set up on this server yet."}</span>
                  </span>
                </label>
                {c.key === "push" && on && channels.push && available?.vapid_public_key && <PushDevice vapidPublicKey={available.vapid_public_key} />}
                {c.key === "telegram" && on && channels.telegram && (
                  <div className="mt-3">
                    <label htmlFor="p-chat" className="label">Telegram chat ID</label>
                    <input id="p-chat" value={chatId} onChange={(e) => setChatId(e.target.value)} inputMode="numeric" className="input" aria-describedby="p-chat-hint" />
                    <p id="p-chat-hint" className="hint">
                      {available?.telegram_bot_username
                        ? <>Send any message to <a className="font-semibold underline" href={`https://t.me/${available.telegram_bot_username}`} target="_blank" rel="noopener noreferrer">@{available.telegram_bot_username}</a>; it replies with your chat ID.</>
                        : "Send any message to our Telegram bot; it replies with your chat ID."}
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <p className="hint">Every alert is also kept in your <Link className="font-semibold underline" href="/notifications">notifications inbox</Link>, so you never miss one.</p>
      </fieldset>
      <button type="submit" disabled={busy} className="btn btn-primary">{busy && <Loader2 size={18} className="animate-spin" aria-hidden="true" />} Save changes</button>
      <Status state={state} />
    </form>
  );
}

export function PasswordForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const next = String(f.get("new_password"));
    if (next.length < 10) { setState({ ok: false, text: "Use at least 10 characters for the new password." }); return; }
    setBusy(true); setState(null);
    const res = await fetch("/bff/auth/change-password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: f.get("current_password"), new_password: next }),
    }).catch(() => null);
    const body = await res?.json().catch(() => null);
    setBusy(false);
    if (!res?.ok) { setState({ ok: false, text: body?.errors?.[0] ?? body?.message ?? "Couldn't change your password." }); return; }
    // Every session was revoked server-side, so finish signing out here too.
    await fetch("/bff/session/logout", { method: "POST" }).catch(() => null);
    router.push("/login");
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <div><label htmlFor="cur-pw" className="label">Current password</label><input id="cur-pw" name="current_password" type="password" autoComplete="current-password" required className="input" /></div>
      <div>
        <label htmlFor="new-pw" className="label">New password</label>
        <input id="new-pw" name="new_password" type="password" autoComplete="new-password" required className="input" aria-describedby="new-pw-hint" />
        <p id="new-pw-hint" className="hint">At least 10 characters. You will be signed out on all devices.</p>
      </div>
      <button type="submit" disabled={busy} className="btn btn-outline">{busy && <Loader2 size={18} className="animate-spin" aria-hidden="true" />} Change password</button>
      <Status state={state} />
    </form>
  );
}

/** Sends a test message on each channel the user has saved, so they can check their setup. */
export function ChannelTests({ user, available }: { user: User; available: NotificationChannels | null }) {
  const prefs = user.notification_preferences as Record<string, unknown>;
  const enabled = ["in_app", ...CHANNELS.filter((c) => available?.[c.key] && prefs[c.key]).map((c) => c.key)];
  const labels: Record<string, string> = { in_app: "inbox", email: "email", push: "push", telegram: "Telegram" };
  const [busy, setBusy] = useState<string | null>(null);
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);

  async function send(channel: string) {
    setBusy(channel); setState(null);
    const res = await fetch("/bff/me/notifications/test", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel }),
    }).catch(() => null);
    const body = await res?.json().catch(() => null);
    setBusy(null);
    if (res?.ok) setState({ ok: true, text: `Test ${labels[channel]} message queued. It should arrive within a few minutes.` });
    else setState({ ok: false, text: res?.status === 429 ? "You have sent a lot of tests. Try again later." : body?.message ?? "Couldn't send a test." });
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">Send yourself a test on the channels you have saved.</p>
      <div className="flex flex-wrap gap-2">
        {enabled.map((c) => (
          <button key={c} type="button" onClick={() => send(c)} disabled={busy !== null} className="btn btn-outline btn-sm">
            {busy === c ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Send size={16} aria-hidden="true" />} Test {labels[c]}
          </button>
        ))}
      </div>
      <Status state={state} />
    </div>
  );
}
