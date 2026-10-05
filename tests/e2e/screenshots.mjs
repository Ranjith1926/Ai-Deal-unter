import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:3000";
mkdirSync("out", { recursive: true }); // writes PNGs to ./out (git-ignored)
const browser = await chromium.launch();

const targets = [
  ["home", "/"],
  ["deals", "/deals"],
  ["product", "/deals/PRODUCT_ID"],
  ["compare", "/compare?ids=IDS"],
  ["login", "/login"],
];

// Find a scored product (the best deal) for the detail page, and two ids to compare.
const best = await (await fetch("http://localhost:8000/api/deals/best?limit=4")).json();
const all = await (await fetch("http://localhost:8000/api/products?page_size=12&sort=deal_score")).json();
const productId = best.data?.[0]?.id ?? all.data[0].id;
const ids = all.data.slice(0, 2).map((p) => p.id).join(",");
console.log("product", productId, "compare", ids);

for (const [vp, size] of [["desktop", { width: 1440, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
  const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: vp === "mobile" ? 2 : 1 });
  const page = await ctx.newPage();
  for (const [name, path] of targets) {
    const url = BASE + path.replace("PRODUCT_ID", productId).replace("IDS", ids);
    await page.goto(url, { waitUntil: "networkidle" });
    await page.screenshot({ path: `out/${name}-${vp}.png`, fullPage: name !== "home" && name !== "deals" ? true : false });
    // full-page for home too, but capped
    if (name === "home") await page.screenshot({ path: `out/${name}-${vp}-full.png`, fullPage: true });
  }
  await ctx.close();
}
await browser.close();
console.log("done");
