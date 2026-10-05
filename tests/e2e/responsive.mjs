// Fails if any public page scrolls horizontally on a small phone (360px wide).
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? "http://localhost:8000";
const b = await chromium.launch();
const c = await b.newContext({ viewport: { width: 360, height: 780 } });
const p = await c.newPage();
const ids = (await (await fetch(`${API}/api/products?page_size=3&sort=deal_score`)).json()).data.map((x) => x.id);
let failures = 0;
const paths = ["/", "/deals", "/search?q=a", "/category/laptops", `/deals/${ids[0]}`, `/deals/${ids[1]}`,
  `/compare?ids=${ids.join(",")}`, "/login", "/register", "/forgot-password", "/assistant"];
for (const path of paths) {
  await p.goto(BASE + path, { waitUntil: "networkidle" });
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 1) failures++;
  console.log(overflow <= 1 ? "PASS" : "FAIL", path.padEnd(30), `overflow ${overflow}px`);
}
await b.close();
process.exit(failures ? 1 : 0);
