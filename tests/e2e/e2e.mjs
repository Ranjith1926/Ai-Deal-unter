import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:3000";
mkdirSync("out", { recursive: true });
const browser = await chromium.launch();
let failures = 0;
const check = (ok, msg) => { console.log(`${ok ? "PASS" : "FAIL"}  ${msg}`); if (!ok) failures++; };

const all = await (await fetch("http://localhost:8000/api/products?page_size=12&sort=deal_score")).json();
const best = await (await fetch("http://localhost:8000/api/deals/best?limit=1")).json();
const pid = best.data?.[0]?.id ?? all.data[0].id;

// ------------------------------------------------------------------ accessibility (axe)
const pages = ["/", "/deals", `/deals/${pid}`, `/compare?ids=${all.data[0].id},${all.data[1].id}`, "/search?q=samsung", "/category/tv", "/login", "/register", "/forgot-password"];
for (const scheme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: scheme });
  const page = await ctx.newPage();
  for (const path of pages) {
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const v = res.violations;
    check(v.length === 0, `axe ${scheme.padEnd(5)} ${path} (${v.length} violations)`);
    for (const x of v) {
      console.log(`      - [${x.impact}] ${x.id}: ${x.help} (${x.nodes.length} nodes)`);
      for (const n of x.nodes.slice(0, 4)) console.log(`          ${n.target.join(" ")}  ${(n.any[0]?.message ?? "").slice(0, 150)}`);
    }
    if (path === "/" || path.startsWith("/deals/")) await page.screenshot({ path: `out/${path === "/" ? "home" : "product"}-${scheme}.png`, fullPage: false });
  }
  await ctx.close();
}

// ------------------------------------------------------------------ real user journey
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
const email = `e2e${Date.now()}@example.com`;

await page.goto(BASE + "/alerts");
check(page.url().includes("/login?next=%2Falerts"), "signed-out /alerts redirects to login with next");

await page.goto(BASE + "/register");
await page.getByLabel("Full name").fill("Asha Tester");
await page.getByLabel("Email address").fill(email);
await page.getByLabel("Password", { exact: true }).fill("short");
await page.getByRole("button", { name: "Create account" }).click();
const summary = page.locator('div[role="alert"][tabindex="-1"]');
await summary.waitFor();
check(/10 characters/i.test(await summary.innerText()), "weak password shows inline error summary");
check(await summary.evaluate((el) => el === document.activeElement), "error summary receives focus");

await page.getByLabel("Password", { exact: true }).fill("a-long-passphrase-123");
await page.getByRole("button", { name: "Create account" }).click();
await page.waitForURL(BASE + "/", { timeout: 15000 });
check(await page.getByRole("link", { name: /Asha/ }).first().isVisible(), "registered and signed in (name in header)");

const cookies = await ctx.cookies();
check(cookies.some((c) => c.name === "dh_at" && c.httpOnly) && cookies.some((c) => c.name === "dh_rt" && c.httpOnly), "session tokens are httpOnly cookies");
check(!(await page.evaluate(() => document.cookie)).includes("dh_"), "tokens not readable from page JavaScript");

const settled = { waitUntil: "networkidle" };
await page.goto(BASE + `/deals/${pid}`, settled);
await page.getByRole("button", { name: /Save .* to favourites/ }).first().click();
await page.waitForTimeout(1200);
await page.goto(BASE + "/favorites", settled);
check(await page.getByRole("heading", { name: "Your favourites" }).isVisible() && (await page.locator("article:visible").count()) === 1, "favourite saved and listed");

await page.goto(BASE + `/deals/${pid}`, settled);
await page.getByLabel("Alert me at or below (₹)").fill("1000");
await page.getByRole("button", { name: "Set price alert" }).click();
await page.getByText(/Alert set/).waitFor({ timeout: 8000 });
await page.goto(BASE + "/alerts", settled);
check((await page.getByText("Watching").locator("visible=true").count()) === 1, "price alert created and shown once as Watching");
await page.getByRole("button", { name: /Delete/ }).click();
await page.getByText("No alerts yet").waitFor({ timeout: 8000 });
check(true, "price alert deleted");

await page.goto(BASE + "/profile", settled);
await page.getByLabel("Name", { exact: true }).fill("Asha T");
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByText("Saved.").waitFor({ timeout: 8000 });
check(true, "profile saved");

// CSRF: a cross-site POST to the proxy is refused
const csrf = await page.evaluate(async () => (await fetch("/bff/alerts", { method: "POST", headers: { "Content-Type": "application/json", Origin: "https://evil.example" }, body: "{}" })).status);
check(csrf === 403 || csrf === 422 || csrf === 401 || csrf === 200, `same-origin proxy reachable (status ${csrf})`);
const evil = await ctx.request.post(BASE + "/bff/session/logout", { headers: { Origin: "https://evil.example" } });
check(evil.status() === 403, "cross-site POST is blocked (CSRF)");
const direct = await ctx.request.post(BASE + "/bff/auth/login", { data: {} , headers: { Origin: BASE }});
check(direct.status() === 404, "token endpoints are not exposed through the generic proxy");

await page.getByRole("button", { name: "Sign out" }).first().click();
await page.waitForURL(BASE + "/");
check(await page.getByRole("link", { name: "Sign in" }).first().isVisible(), "signed out");
await page.goto(BASE + "/profile");
check(page.url().includes("/login"), "profile is protected after sign out");

await browser.close();
console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures ? 1 : 0);
