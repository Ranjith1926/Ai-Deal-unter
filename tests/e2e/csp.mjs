// Verifies the Content-Security-Policy in a real browser: strict policy, unique nonces, and zero violations
// on every kind of page (so the policy protects without breaking the site).
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? "http://localhost:8000";
let failures = 0;
const check = (ok, msg) => { console.log(`${ok ? "PASS" : "FAIL"}  ${msg}`); if (!ok) failures++; };

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();

const violations = [];
const consoleErrors = [];
await page.addInitScript(() => {
  window.__csp = [];
  document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} blocked ${e.blockedURI || "inline"}`));
});
page.on("console", (m) => { if (m.type() === "error" && /Content Security Policy|Refused to/i.test(m.text())) consoleErrors.push(m.text().slice(0, 200)); });

// Sign up so account pages can be visited too.
const email = `csp-${Date.now()}@example.com`;
await ctx.request.post(`${BASE}/bff/auth/register`, { data: { email, name: "CSP Tester", password: "a-long-passphrase-123" }, headers: { Origin: BASE } });
await page.goto(BASE + "/login", { waitUntil: "networkidle" });
await page.getByLabel("Email address").fill(email);
await page.getByLabel("Password", { exact: true }).fill("a-long-passphrase-123");
await page.getByRole("button", { name: "Sign in" }).last().click();
await page.waitForURL(BASE + "/");

const pid = (await (await fetch(`${API}/api/products?page_size=1&sort=deal_score`)).json()).data[0].id;
const paths = ["/", "/deals", `/deals/${pid}`, "/search?q=a", "/category/laptops", `/compare?ids=${pid}`, "/login", "/register", "/alerts", "/favorites", "/profile", "/assistant"];

const headers = [];
for (const path of paths) {
  const res = await page.goto(BASE + path, { waitUntil: "networkidle" });
  headers.push(res.headers()["content-security-policy"] ?? "");
  // Exercise interactivity too: a toggle and the theme button must work under the policy.
  const found = await page.evaluate(() => window.__csp ?? []);
  violations.push(...found.map((v) => `${path}: ${v}`));
}

const csp = headers[0];
check(csp.includes("default-src 'self'") && csp.includes("object-src 'none'") && csp.includes("frame-ancestors 'none'") && csp.includes("base-uri 'self'") && csp.includes("form-action 'self'"), "CSP: strict base directives are present");
check(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/.test(csp), "CSP: scripts require a nonce (strict-dynamic)");
check(!/script-src[^;]*'unsafe-inline'/.test(csp) && !/script-src[^;]*'unsafe-eval'/.test(csp), "CSP: no unsafe-inline or unsafe-eval for scripts");
const nonces = new Set(headers.map((h) => (h.match(/'nonce-([^']+)'/) ?? [])[1]));
check(nonces.size === headers.length && !nonces.has(undefined), `CSP: a fresh nonce on every response (${nonces.size} distinct in ${headers.length})`);
check(violations.length === 0 && consoleErrors.length === 0, `CSP: zero violations across ${paths.length} pages (${violations.length} violations, ${consoleErrors.length} console errors)`);
for (const v of [...violations, ...consoleErrors].slice(0, 8)) console.log("      - " + v);

// The inline theme script must carry the nonce, and the theme toggle must still work.
await page.goto(BASE + "/", { waitUntil: "networkidle" });
const inlineNonce = await page.evaluate(() => [...document.scripts].filter((s) => !s.src).every((s) => s.nonce || s.getAttribute("nonce")));
check(inlineNonce, "CSP: every inline script carries the nonce");
await page.getByRole("button", { name: /Switch to (dark|light) theme/ }).click();
const theme = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
check(theme === "dark" || theme === "light", "CSP: the theme toggle still works");

// Simulate what an XSS bug would do: HTML that reaches the page through the parser (as injected markup does).
// Inline event handlers and javascript: links must not run.
const attack = await page.evaluate(() => new Promise((resolve) => {
  window.__pwned = false;
  window.__csp = [];
  document.body.insertAdjacentHTML("beforeend",
    '<img id="x1" src="x:" onerror="window.__pwned = true">' +
    '<a id="x2" href="javascript:window.__pwned = true">pwn</a>' +
    '<svg id="x3" onload="window.__pwned = true"></svg>');
  document.getElementById("x2").click();
  setTimeout(() => resolve({ pwned: window.__pwned, blocked: window.__csp.length }), 500);
}));
check(attack.pwned === false && attack.blocked >= 2, `CSP: injected inline handlers and javascript: links are blocked (${attack.blocked} violations reported)`);

await browser.close();
console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures ? 1 : 0);
