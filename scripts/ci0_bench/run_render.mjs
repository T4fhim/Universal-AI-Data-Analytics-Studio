// CI.0 part 2 browser benchmark: node run_render.mjs <mode>, mode = shell (software GL) | chromium (real GPU).
// Env: SMOKE=1 six quick cases, ONLY=line:100000,treemap:50000 a subset, CI0_CHROMIUM / CI0_CHROMIUM_SHELL a browser binary.
// Playwright comes from apps/web (already pinned there); echarts from this directory's npm install.
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(here, "../../apps/web/package.json"))("@playwright/test");
const page_url = pathToFileURL(path.join(here, "render_bench.html")).href;
const mode = process.argv[2] ?? "shell";
const REPS = 3;
const TIMEOUT = 90_000;

const sizes = [10_000, 100_000, 1_000_000];
const cases = [];
for (const n of sizes) for (const lib of ["plotly-svg", "plotly-gl", "echarts", "echarts-large"]) cases.push([lib, "scatter", n]);
for (const n of sizes) for (const lib of ["plotly-svg", "plotly-gl", "echarts", "echarts-lttb", "echarts-minmax"]) cases.push([lib, "line", n]);
for (const lib of ["plotly-svg", "echarts"]) cases.push([lib, "treemap", 50_000]);

if (process.env.SMOKE) cases.splice(0, cases.length, ["plotly-svg", "scatter", 10000], ["plotly-gl", "scatter", 10000], ["echarts", "scatter", 10000], ["echarts-large", "line", 10000], ["plotly-svg", "treemap", 5000], ["echarts", "treemap", 5000]);
if (process.env.ONLY) { const keep = process.env.ONLY.split(","); const kept = cases.filter(([l, k, n]) => keep.includes(k + ":" + n)); cases.splice(0, cases.length, ...kept); }
const args = ["--enable-precise-memory-info", "--ignore-gpu-blocklist"];
const launch = mode === "chromium"
  ? { executablePath: process.env.CI0_CHROMIUM || undefined, headless: false, args: [...args, "--headless=new", "--use-angle=d3d11", "--enable-gpu"] }
  : { executablePath: process.env.CI0_CHROMIUM_SHELL || undefined, headless: true, args };
const browser = await chromium.launch(launch);
const median = (xs) => xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)];
const out = [];
let gl = "";
for (const [lib, kind, n] of cases) {
  const runs = [];
  let status = "ok";
  for (let rep = 0; rep < REPS; rep++) {
    const ctx = await browser.newContext({ viewport: { width: 1000, height: 600 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 120)));
    try {
      await page.goto(page_url);
      const r = await Promise.race([
        page.evaluate(([l, k, m]) => window.runCase(l, k, m), [lib, kind, n]),
        new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), TIMEOUT)),
      ]);
      gl = r.gl;
      runs.push(r);
    } catch (e) {
      status = String(e.message).slice(0, 60);
      await ctx.close().catch(() => {});
      break;
    }
    if (errors.length) status = "pageerror: " + errors[0];
    await ctx.close();
    if (runs.length === 1 && runs[0].render_ms > 20_000) break; // too slow to repeat
  }
  const row = { lib, kind, n, status, reps: runs.length };
  if (runs.length) {
    for (const key of ["render_ms", "zoom_ms", "heap_mb", "payload_bytes", "stringify_ms"]) {
      const v = runs.map((r) => r[key]).filter((x) => x !== undefined);
      if (v.length) row[key] = Math.round(median(v) * 10) / 10;
    }
  }
  out.push(row);
  console.log(JSON.stringify(row));
}
await browser.close();
mkdirSync(path.join(here, "out"), { recursive: true });
writeFileSync(path.join(here, `out/render_${mode}${process.env.ONLY ? "_rest" : ""}.json`), JSON.stringify({ mode, gl, results: out }, null, 1));
console.log("GL renderer:", gl);
