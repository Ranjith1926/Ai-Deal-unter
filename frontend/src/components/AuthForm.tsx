"use client";

import { AlertCircle, Eye, EyeOff, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

type Mode = "login" | "register" | "forgot" | "reset";

const COPY: Record<Mode, { submit: string; busy: string }> = {
  login: { submit: "Sign in", busy: "Signing in…" },
  register: { submit: "Create account", busy: "Creating account…" },
  forgot: { submit: "Send reset link", busy: "Sending…" },
  reset: { submit: "Set new password", busy: "Saving…" },
};

interface FieldErrors { [field: string]: string }

/** Only same-site relative paths are honoured after sign-in (no open redirects). */
function safeNext(next: string | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function AuthForm({ mode, next, token }: { mode: Mode; next?: string; token?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [summary, setSummary] = useState<string[]>([]);
  const [done, setDone] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);
  const summaryRef = useRef<HTMLDivElement>(null);

  useEffect(() => { if (summary.length) summaryRef.current?.focus(); }, [summary]);

  async function post(url: string, payload: unknown) {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await res.json().catch(() => null);
    return { res, body };
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email") ?? "").trim();
    const password = String(f.get("password") ?? "");
    const name = String(f.get("name") ?? "").trim();

    // Client-side checks catch the obvious; the server remains the authority.
    const fe: FieldErrors = {};
    if (mode !== "reset" && !/^\S+@\S+\.\S+$/.test(email)) fe.email = "Enter a valid email address, like name@example.com.";
    if (mode === "register" && !name) fe.name = "Enter your name.";
    if (mode !== "forgot" && password.length < (mode === "login" ? 1 : 10)) fe.password = mode === "login" ? "Enter your password." : "Use at least 10 characters.";
    if (Object.keys(fe).length) { setErrors(fe); setSummary(Object.values(fe)); return; }

    setBusy(true); setErrors({}); setSummary([]);
    try {
      let result: { res: Response; body: any };
      if (mode === "login") result = await post("/bff/session/login", { email, password });
      else if (mode === "register") result = await post("/bff/auth/register", { email, name, password });
      else if (mode === "forgot") result = await post("/bff/auth/password-reset/request", { email });
      else result = await post("/bff/auth/password-reset/confirm", { token, new_password: password });

      const { res, body } = result;
      if (!res.ok) {
        const msgs: string[] = body?.errors?.length ? body.errors : [body?.message ?? "Something went wrong. Please try again."];
        const mapped: FieldErrors = {};
        for (const m of msgs) {
          const field = /^(email|password|name)\b/i.exec(m)?.[1]?.toLowerCase();
          if (field) mapped[field] = m.replace(/^\w+:\s*/, "");
        }
        if (res.status === 429) msgs.splice(0, msgs.length, "Too many attempts. Please wait a minute and try again.");
        setErrors(mapped); setSummary(msgs);
        return;
      }
      if (mode === "login") { router.push(safeNext(next)); router.refresh(); }
      else if (mode === "register") {
        const login = await post("/bff/session/login", { email, password });
        if (login.res.ok) { router.push(safeNext(next)); router.refresh(); } else router.push("/login");
      } else if (mode === "forgot") setDone("If an account exists for that email, a reset link is on its way. It expires in 30 minutes.");
      else { setDone("Your password has been updated. Please sign in with the new one."); setTimeout(() => router.push("/login"), 1500); }
    } catch {
      setSummary(["We couldn't reach the server. Check your connection and try again."]);
    } finally {
      setBusy(false);
    }
  }

  if (done) return <p role="status" className="rounded-xl bg-primary-soft px-4 py-3 font-semibold text-fg">{done}</p>;

  const err = (f: string) => errors[f];
  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4" aria-busy={busy}>
      {summary.length > 0 && (
        <div ref={summaryRef} tabIndex={-1} role="alert" className="rounded-xl border-2 border-danger bg-danger-soft px-4 py-3 text-fg outline-none">
          <p className="flex items-center gap-2 font-bold"><AlertCircle size={18} aria-hidden="true" /> Please fix the following</p>
          <ul className="mt-1 list-disc pl-6 text-sm">{summary.map((m) => <li key={m}>{m}</li>)}</ul>
        </div>
      )}

      {mode === "register" && (
        <div>
          <label htmlFor="name" className="label">Full name</label>
          <input id="name" name="name" autoComplete="name" required className="input" aria-invalid={!!err("name")} aria-describedby={err("name") ? "name-err" : undefined} />
          {err("name") && <p id="name-err" className="field-error">{err("name")}</p>}
        </div>
      )}

      {mode !== "reset" && (
        <div>
          <label htmlFor="email" className="label">Email address</label>
          <input id="email" name="email" type="email" inputMode="email" autoComplete="email" required className="input" aria-invalid={!!err("email")} aria-describedby={err("email") ? "email-err" : undefined} />
          {err("email") && <p id="email-err" className="field-error">{err("email")}</p>}
        </div>
      )}

      {mode !== "forgot" && (
        <div>
          <div className="flex items-center justify-between">
            <label htmlFor="password" className="label !mb-0">{mode === "reset" ? "New password" : "Password"}</label>
            {mode === "login" && <Link href="/forgot-password" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">Forgot password?</Link>}
          </div>
          <div className="relative mt-1.5">
            <input id="password" name="password" type={showPw ? "text" : "password"} required className="input pr-12"
              autoComplete={mode === "login" ? "current-password" : "new-password"} aria-invalid={!!err("password")}
              aria-describedby={`${err("password") ? "password-err " : ""}${mode !== "login" ? "password-hint" : ""}`.trim() || undefined} />
            <button type="button" onClick={() => setShowPw((s) => !s)} aria-pressed={showPw} aria-label={showPw ? "Hide password" : "Show password"}
              className="btn btn-ghost btn-icon absolute right-0.5 top-0.5 !min-h-10 !min-w-10 !p-0">
              {showPw ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
            </button>
          </div>
          {mode !== "login" && <p id="password-hint" className="hint">At least 10 characters. A passphrase of a few words works well.</p>}
          {err("password") && <p id="password-err" className="field-error">{err("password")}</p>}
        </div>
      )}

      <button type="submit" disabled={busy} className="btn btn-primary w-full">
        {busy && <Loader2 size={18} className="animate-spin" aria-hidden="true" />}
        {busy ? COPY[mode].busy : COPY[mode].submit}
      </button>
    </form>
  );
}
