// Browser tests for Phase 10 notifications: channel settings, real email delivery (via the dev Mailpit
// catcher), the full password-reset journey from the emailed link, and the in-app inbox.
//
// Needs the dev stack with Mailpit (docker compose up -d) and SMTP_HOST=mailpit in .env, plus an administrator
// (to flush the queue instead of waiting for the 5-minute schedule):
//   E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... node notifications.mjs
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025/api/v1";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL;
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD;
if (!ADMIN_EMAIL || !ADMIN_PASSWORD) throw new Error("Set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD");

let failures = 0;
const check = (ok, msg) => { console.log(`${ok ? "PASS" : "FAIL"}  ${msg}`); if (!ok) failures++; };
const settled = { waitUntil: "networkidle" };
const browser = await chromium.launch();

async function login(ctx, email, password) {
  const page = await ctx.newPage();
  await page.goto(BASE + "/login", settled);
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).last().click();
  await page.waitForURL(BASE + "/", { timeout: 15000 });
  return page;
}

async function axe(page, label) {
  const run = () => new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  // A late client-side reload can interrupt a scan; scan again once the page has settled.
  const res = await run().catch(async () => { await page.waitForLoadState("networkidle"); return run(); });
  check(res.violations.length === 0, `axe ${label} (${res.violations.length} violations)`);
  for (const v of res.violations) console.log(`      - [${v.impact}] ${v.id}: ${v.help}`);
}

// The admin flushes the notification queue through the real job system (Celery), as the scheduler would.
const adminCtx = await browser.newContext();
await login(adminCtx, ADMIN_EMAIL, ADMIN_PASSWORD);
async function flush() {
  const r = await adminCtx.request.post(`${BASE}/bff/admin/jobs/trigger`, { data: { job: "send_notifications" }, headers: { Origin: BASE } });
  if (r.status() !== 202) throw new Error("could not trigger send_notifications: " + r.status());
}

async function waitForEmail(to, subject) {
  for (let i = 0; i < 20; i++) {
    await flush();
    await new Promise((r) => setTimeout(r, 1500));
    const list = await (await fetch(`${MAILPIT}/messages?limit=200`)).json();
    const msg = list.messages.find((m) => m.Subject === subject && m.To.some((t) => t.Address === to));
    if (msg) return (await fetch(`${MAILPIT}/message/${msg.ID}`)).json();
  }
  return null;
}

const email = `e2e-notify-${Date.now()}@example.com`;
const password = "a-long-passphrase-123";
const ctx = await browser.newContext();
const reg = await ctx.request.post(`${BASE}/bff/auth/register`, { data: { email, name: "Notify Tester", password }, headers: { Origin: BASE } });
if (reg.status() !== 201) throw new Error("register failed " + reg.status());

// ------------------------------------------------------------------ signed out
const anon = await (await browser.newContext()).newPage();
await anon.goto(BASE + "/notifications", settled);
check(anon.url().includes("/login"), "notifications: inbox needs an account");

// ------------------------------------------------------------------ channel settings
const page = await login(ctx, email, password);
check(await page.getByRole("link", { name: "Notifications" }).first().isVisible(), "header: notifications link for signed-in users");
await page.goto(BASE + "/profile", settled);
const emailBox = page.getByRole("checkbox", { name: /Email/ });
check(await emailBox.isEnabled(), "profile: email is available (SMTP configured)");
check(await page.getByRole("checkbox", { name: /Telegram/ }).isDisabled(), "profile: unconfigured Telegram is disabled, not silently ignored");
check(await page.getByText("Not set up on this server yet.").first().isVisible(), "profile: says why a channel is unavailable");
await emailBox.check();
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByText("Saved.").waitFor();
await page.waitForLoadState("networkidle");  // the form reloads the page after saving
check(await page.getByRole("checkbox", { name: /Email/ }).isChecked(), "profile: email preference saved");
await axe(page, "/profile");

// ------------------------------------------------------------------ real email via SMTP
await page.getByRole("button", { name: "Test email" }).click();
await page.getByText(/Test email message queued/).waitFor();
check(true, "profile: test email queued");
const testMail = await waitForEmail(email, "Test notification from AI Deal Hunter");
check(testMail !== null, "email: test message delivered over SMTP to the user's address");
check(testMail?.Text?.includes("notification settings"), "email: carries the why-you-got-this footer");

// ------------------------------------------------------------------ inbox
await page.getByRole("button", { name: "Test inbox" }).click();
await page.getByText(/Test inbox message queued/).waitFor();
await flush();
let unread = false;
for (let i = 0; i < 15 && !unread; i++) {
  await page.waitForTimeout(1000);
  await page.goto(BASE + "/notifications", settled);
  unread = await page.getByText("1 unread").isVisible();
}
check(unread, "inbox: test notification arrives unread");
check(await page.getByRole("heading", { name: /Test notification from AI Deal Hunter/ }).isVisible(), "inbox: shows the notification title");
await axe(page, "/notifications");
await page.emulateMedia({ colorScheme: "dark" });
await axe(page, "/notifications dark");
await page.emulateMedia({ colorScheme: "light" });
await page.getByRole("button", { name: "Mark all as read" }).click();
await page.getByText("All caught up").waitFor();
await page.reload(settled);
check(await page.getByText("All caught up").isVisible(), "inbox: read state persists");

const phone = await ctx.newPage();
await phone.setViewportSize({ width: 360, height: 780 });
for (const path of ["/notifications", "/profile"]) {
  await phone.goto(BASE + path, settled);
  const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(overflow <= 0, `${path} has no horizontal page scroll at phone width (overflow ${overflow}px)`);
}

// ------------------------------------------------------------------ password reset, end to end
const resetCtx = await browser.newContext();
const rp = await resetCtx.newPage();
await rp.goto(BASE + "/forgot-password", settled);
await rp.getByLabel("Email address").fill(email);
await rp.getByRole("button", { name: "Send reset link" }).click();
await rp.getByText(/reset link is on its way/).waitFor();
const resetMail = await waitForEmail(email, "Reset your AI Deal Hunter password");
check(resetMail !== null, "reset: email delivered");
const link = resetMail?.Text?.match(/https?:\/\/\S+reset-password\?token=[\w-]+/)?.[0];
check(Boolean(link) && !resetMail.Text.includes("notification settings"), "reset: email has the link and no marketing footer");
if (link) {
  await rp.goto(link.replace(/^https?:\/\/[^/]+/, BASE), settled);
  const newPassword = "a-brand-new-passphrase-456";
  await rp.getByLabel("New password").fill(newPassword);
  await rp.getByRole("button", { name: "Set new password" }).click();
  await rp.waitForURL(/\/login/, { timeout: 15000 }).catch(() => null);
  const fresh = await browser.newContext();
  const ok = await login(fresh, email, newPassword).then(() => true).catch(() => false);
  check(ok, "reset: the emailed link sets a new password that works");
  const reuse = await resetCtx.request.post(`${BASE}/bff/auth/password-reset/confirm`, {
    data: { token: new URL(link).searchParams.get("token"), new_password: "yet-another-passphrase-789" }, headers: { Origin: BASE },
  });
  check(reuse.status() === 422, "reset: the emailed link works only once");
}

await browser.close();
console.log(failures ? `\n${failures} CHECK(S) FAILED` : "\nALL CHECKS PASSED");
process.exit(failures ? 1 : 0);
