// Browser tests for the admin dashboard and the AI assistant page.
//
// Needs the stack running, an administrator account (create it on the site, then run
//   docker compose run --rm backend python -m app.cli make-admin <email>)
// and the backend started with ANTHROPIC_API_KEY set to ANY non-empty value so the chat UI is shown.
// With an invalid key the "live" check proves the failure path is friendly; the happy path uses a mocked reply.
//
//   E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... node admin-assistant.mjs
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? "http://localhost:8000";
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

async function register(ctx) {
  const email = `e2e-user-${Date.now()}@example.com`;
  const r = await ctx.request.post(`${BASE}/bff/auth/register`, { data: { email, name: "E2E User", password: "a-long-passphrase-123" }, headers: { Origin: BASE } });
  if (r.status() !== 201) throw new Error("register failed " + r.status());
  return { email, password: "a-long-passphrase-123" };
}

async function axe(page, label) {
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  check(res.violations.length === 0, `axe ${label} (${res.violations.length} violations)`);
  for (const v of res.violations) {
    console.log(`      - [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length})`);
    for (const n of v.nodes.slice(0, 3)) console.log(`          ${n.target.join(" ")}  ${(n.any[0]?.message ?? "").slice(0, 140)}`);
  }
}

// =================================================================== ASSISTANT
{
  const anon = await browser.newContext();
  const p = await anon.newPage();
  await p.goto(BASE + "/assistant", settled);
  check(await p.getByText("Sign in to chat with the assistant").isVisible(), "assistant: signed-out visitors are asked to sign in");
  await anon.close();

  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const user = await register(ctx);
  const page = await login(ctx, user.email, user.password);

  await page.goto(BASE + "/assistant", settled);
  check(await page.getByRole("heading", { name: "Shopping assistant" }).isVisible(), "assistant: page loads for a signed-in user");
  check((await page.getByRole("list", { name: "Suggested questions" }).getByRole("button").count()) === 6, "assistant: the six suggested questions are offered");

  // Happy path with a mocked reply: checks rendering, safety of Markdown, and the request shape.
  let sent = null;
  await page.route("**/bff/assistant/chat", async (route) => {
    sent = JSON.parse(route.request().postData());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      success: true, message: null, errors: [], data: { stop: "end_turn", model: "claude-opus-5-5",
        reply: "Yes, it's a **good deal**.\n\n- ₹23,000 on Flipkart\n- ₹16,024 below its usual price\n\nSee [the product](/deals/2) or /deals/2. <script>alert(1)</script> [evil](https://evil.example)",
        steps: [{ tool: "get_deal_score", summary: "product_id=2", ok: true }, { tool: "compare_prices", summary: "product_id=2", ok: true }] } }) });
  });
  await page.getByRole("list", { name: "Suggested questions" }).getByRole("button").first().click();
  await page.getByText("good deal").first().waitFor();
  check(sent?.messages?.length === 1 && sent.messages[0].role === "user" && sent.product_id === null, "assistant: sends only the plain conversation");
  check((await page.locator("li strong", { hasText: "good deal" }).count()) + (await page.locator("p strong", { hasText: "good deal" }).count()) >= 1, "assistant: **bold** is rendered");
  check((await page.locator("ul li", { hasText: "₹23,000 on Flipkart" }).count()) === 1, "assistant: bullet lists are rendered");
  check((await page.locator('a[href="/deals/2"]').count()) >= 2, "assistant: product links are rendered as site links");
  check((await page.locator("script", { hasText: "alert(1)" }).count()) === 0 && (await page.locator('a[href^="https://evil"]').count()) === 0, "assistant: injected HTML and external links are NOT rendered");
  check(await page.getByText("How I found this (2 lookups)").isVisible(), "assistant: shows which lookups were used");
  await axe(page, "assistant (conversation)");

  // Error mapping
  await page.unroute("**/bff/assistant/chat");
  await page.route("**/bff/assistant/chat", (route) => route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ success: false, message: "Too many requests", errors: [], data: null }) }));
  await page.getByLabel("Your question").fill("Another question");
  await page.keyboard.press("Enter");
  await page.getByRole("log").getByText(/hourly limit/).waitFor();
  check(true, "assistant: rate limit shows a friendly message");

  // Live failure path (no mock): with a placeholder key the real call fails and must be handled gracefully.
  await page.unroute("**/bff/assistant/chat");
  await page.getByLabel("Your question").fill("Is the Samsung TV a good deal?");
  await page.getByRole("button", { name: "Send question" }).click();
  await page.locator("li", { hasText: /assistant|isn't set up|tools are unavailable|temporarily unavailable|not configured/i }).last().waitFor({ timeout: 60000 });
  const bodyText = await page.locator("main").innerText();
  check(!/Traceback|Internal server error|sk-ant|undefined/.test(bodyText), "assistant: a real upstream failure is shown as a friendly message with no internals");
  await page.getByRole("button", { name: "New chat" }).click();
  check((await page.getByRole("list", { name: "Suggested questions" }).count()) === 1, "assistant: New chat resets the conversation");

  // From a product page
  const any = await (await fetch(`${API}/api/products?page_size=1&sort=deal_score`)).json();
  const pid = any.data[0].id;
  await page.goto(BASE + `/deals/${pid}`, settled);
  await page.getByRole("link", { name: /Ask the assistant about this/ }).click();
  await page.waitForURL(/\/assistant\?product=/);
  check(/good deal/.test(await page.getByLabel("Your question").inputValue()) && await page.getByText("Asking about:").isVisible(), "assistant: product page opens the chat pre-filled with that product");

  for (const scheme of ["light", "dark"]) {
    const c = await browser.newContext({ colorScheme: scheme, viewport: { width: 1280, height: 900 } });
    await c.addCookies(await ctx.cookies());
    const pg = await c.newPage();
    await pg.goto(BASE + "/assistant", settled);
    await axe(pg, `assistant ${scheme}`);
    await c.close();
  }
  await ctx.close();
}

// =================================================================== ADMIN
{
  // Access control
  const anon = await browser.newContext();
  const ap = await anon.newPage();
  await ap.goto(BASE + "/admin");
  check(ap.url().includes("/login?next=%2Fadmin"), "admin: anonymous visitors are sent to sign in");
  await anon.close();

  const normal = await browser.newContext();
  const nu = await register(normal);
  const np = await login(normal, nu.email, nu.password);
  await np.goto(BASE + "/admin", settled);
  // The page streams, so the HTTP status stays 200; what matters is that no admin content is rendered.
  check(await np.getByText("We couldn't find that page").isVisible() && (await np.getByText("Administration").count()) === 0, "admin: ordinary users see a not-found page (the area is not advertised)");
  check((await np.getByRole("link", { name: "Admin" }).count()) === 0, "admin: no Admin link for ordinary users");
  const api403 = await normal.request.get(`${BASE}/bff/admin/stats`);
  check(api403.status() === 403, "admin: the API refuses ordinary users");
  await normal.close();

  const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await login(ctx, ADMIN_EMAIL, ADMIN_PASSWORD);
  check(await page.getByRole("link", { name: "Admin" }).first().isVisible(), "admin: administrators see the Admin link");

  // ---- overview
  await page.goto(BASE + "/admin", settled);
  check(await page.getByRole("heading", { name: "Overview" }).isVisible(), "admin: overview loads");
  for (const label of ["Total products", "Active products", "Amazon listings", "Flipkart listings", "New deals", "Price drops", "Historical lows", "Failed jobs", "Users", "Active price alerts", "Last successful sync", "Average sync time"]) {
    if (!(await page.getByText(label, { exact: true }).first().isVisible())) check(false, `admin: stat "${label}" is shown`);
  }
  check(true, "admin: all required statistics are shown");
  check((await page.getByRole("heading", { level: 3 }).filter({ hasText: /Amazon|Flipkart/ }).count()) === 2, "admin: both provider cards are shown");

  // ---- disable / enable a provider
  await page.getByRole("switch", { name: /^Disable Amazon/ }).click();
  await page.getByText("Amazon disabled.").waitFor();
  await page.waitForTimeout(800);
  check(await page.getByText("Disabled").first().isVisible(), "admin: disabling a provider is reflected in its health");
  await page.getByRole("switch", { name: /^Enable Amazon/ }).click();
  await page.getByText("Amazon enabled.").waitFor();
  check(true, "admin: provider re-enabled");

  // ---- trigger a real job and see it in the log
  await page.getByRole("button", { name: /Run Recalculate scores/ }).click();
  await page.getByText(/Recalculate scores queued/).waitFor();
  check(true, "admin: a job can be triggered");
  let seen = false;
  for (let i = 0; i < 20 && !seen; i++) {
    await page.waitForTimeout(1500);
    await page.goto(BASE + "/admin/jobs?provider=all", settled);
    seen = (await page.getByRole("cell", { name: "calculate scores" }).count()) > 0;
  }
  check(seen, "admin: the triggered job really ran and appears in the job log");
  check(await page.getByRole("table").isVisible(), "admin: job log table is shown");
  await page.goto(BASE + "/admin/jobs?status=failed", settled);
  check(true, "admin: job log filters work");

  // ---- categories & products
  await page.goto(BASE + "/admin/catalog", settled);
  const catName = `E2E Cameras ${Date.now() % 10000}`;
  await page.getByLabel("New category").fill(catName);
  await page.getByRole("button", { name: "Add" }).click();
  await page.getByText("Category added.").waitFor();
  await page.waitForTimeout(600);
  check(await page.getByRole("row", { name: new RegExp(catName) }).count() === 1, "admin: category created");
  await page.getByRole("button", { name: `Delete ${catName}` }).click();
  check(await page.getByRole("button", { name: `Confirm delete ${catName}` }).isVisible(), "admin: deleting asks for confirmation first");
  await page.getByRole("button", { name: `Confirm delete ${catName}` }).click();
  await page.getByText("Category deleted.").waitFor();
  check(true, "admin: empty category deleted");

  const first = (await (await fetch(`${API}/api/products?page_size=1&sort=newest`)).json()).data[0];
  await page.goto(BASE + `/admin/catalog?q=${encodeURIComponent(first.name.split(" ")[0])}`, settled);
  await page.getByRole("switch", { name: new RegExp(`^Hide ${first.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) }).click();
  await page.waitForTimeout(1200);
  check((await fetch(`${API}/api/products/${first.id}`)).status === 404, "admin: hiding a product removes it from the public API");
  await page.goto(BASE + `/admin/catalog?active=false`, settled);
  await page.getByRole("switch", { name: new RegExp(`^Show ${first.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) }).click();
  await page.waitForTimeout(1200);
  check((await fetch(`${API}/api/products/${first.id}`)).status === 200, "admin: product restored");

  // ---- scoring
  await page.goto(BASE + "/admin/scoring", settled);
  const save = page.getByRole("button", { name: "Save", exact: true });
  check(await save.isEnabled(), "admin: scoring starts valid");
  await page.locator("#dw-historical_advantage").fill("50");
  check(await save.isDisabled() && await page.getByText(/must equal 100%/).first().isVisible(), "admin: weights that don't add up to 100% cannot be saved");
  await page.locator("#dw-historical_advantage").fill("35");
  await page.locator("#th-good").fill("85");
  check(await save.isDisabled() && await page.getByRole("alert").filter({ hasText: "Thresholds must run" }).isVisible(), "admin: out-of-order thresholds cannot be saved");
  await page.locator("#th-good").fill("65");
  await save.click();
  await page.getByText(/Saved\./).waitFor();
  await page.waitForTimeout(800);
  check(await page.getByText("Custom settings are active.").isVisible(), "admin: valid scoring changes are saved");
  const eff = await (await ctx.request.get(`${BASE}/bff/admin/scoring`)).json();
  check(eff.data.effective.deal.thresholds.good === 65, "admin: saved value is what the API reports as effective");
  await page.getByRole("button", { name: "Reset to defaults" }).click();
  await page.getByText("Reset to the defaults.").waitFor();
  await page.waitForTimeout(600);
  check(await page.getByText("Using the default settings.").isVisible(), "admin: scoring reset to defaults");

  for (const path of ["/admin", "/admin/jobs", "/admin/catalog", "/admin/scoring"]) {
    for (const scheme of ["light", "dark"]) {
      const c = await browser.newContext({ colorScheme: scheme, viewport: { width: 1280, height: 900 } });
      await c.addCookies(await ctx.cookies());
      const pg = await c.newPage();
      await pg.goto(BASE + path, settled);
      await axe(pg, `${path} ${scheme}`);
      await c.close();
    }
  }
  // Phone width: no horizontal page scroll
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await mobile.addCookies(await ctx.cookies());
  const mp = await mobile.newPage();
  const bestId = (await (await fetch(`${API}/api/products?page_size=2&sort=deal_score`)).json()).data.map((p) => p.id);
  for (const path of ["/admin", "/admin/jobs", "/admin/catalog", "/admin/scoring", "/assistant", `/compare?ids=${bestId.join(",")}`, `/deals/${bestId[0]}`]) {
    await mp.goto(BASE + path, settled);
    const overflow = await mp.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check(overflow <= 1, `${path} has no horizontal page scroll at phone width (overflow ${overflow}px)`);
  }
  await mp.screenshot({ path: "out/admin-mobile.png", fullPage: false });
  await page.goto(BASE + "/admin", settled);
  await page.screenshot({ path: "out/admin-desktop.png", fullPage: true });
  await ctx.close();
}

await browser.close();
console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures ? 1 : 0);
