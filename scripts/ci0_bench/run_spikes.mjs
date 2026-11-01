// CI.0 part 2: the four ECharts recipe spikes. `node run_spikes.mjs` (after `npm install` here).
// Playwright comes from apps/web (already pinned there), so this directory adds no second copy.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(here, "../../apps/web/package.json"))("@playwright/test");
const out = path.join(here, "out");
mkdirSync(out, { recursive: true });

// CI0_CHROMIUM points at a browser binary when the one Playwright expects is not installed.
const browser = await chromium.launch({ headless: true, executablePath: process.env.CI0_CHROMIUM || undefined });
const results = {};
let failed = 0;
for (const name of ["candlestick", "waterfall", "logbar", "decal"]) {
  const page = await (await browser.newContext({ viewport: { width: 720, height: 420 } })).newPage();
  const messages = [];
  page.on("console", (m) => { if (["warning", "error"].includes(m.type())) messages.push(m.text().slice(0, 200)); });
  page.on("pageerror", (e) => messages.push("pageerror: " + String(e).slice(0, 200)));
  await page.goto(pathToFileURL(path.join(here, "spikes.html")).href);
  results.echartsVersion = await page.evaluate(() => window.echartsVersion);
  try {
    results[name] = await page.evaluate((n) => window.runSpike(n), name);
  } catch (e) {
    results[name] = { error: String(e.message).slice(0, 300) };
  }
  results[name].console = messages;
  await page.locator("#c").screenshot({ path: path.join(out, `spike_${name}.png`) });
  const checks = results[name].checks ?? {};
  const bad = Object.entries(checks).filter(([, v]) => v !== true).map(([k]) => k);
  failed += bad.length + (results[name].error ? 1 : 0);
  console.log(`${bad.length || results[name].error ? "FAIL" : "PASS"}  ${name}  ${bad.join(", ")}${results[name].error ?? ""}`);
}
await browser.close();
writeFileSync(path.join(out, "spikes.json"), JSON.stringify(results, null, 1));
console.log(`echarts ${results.echartsVersion}: ${failed} failing check(s); details in out/spikes.json, screenshots in out/`);
