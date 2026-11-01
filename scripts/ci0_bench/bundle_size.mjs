// CI.0 part 2: what a lazy ECharts chunk would weigh. `node bundle_size.mjs` (after `npm install` here).
// Builds a modular `echarts/core` + the charts and components the 14 registered types need with apps/web's own
// Vite (the product's bundler), minified, and compares it with the one-file builds. Not the product's build:
// a lib-mode measurement of the tree-shaken import set, to size the CI.8a budget.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { brotliCompressSync, gzipSync } from "node:zlib";

const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.join(here, "../../apps/web/node_modules");
const echartsDir = path.join(here, "node_modules/echarts");
const work = mkdtempSync(path.join(tmpdir(), "ci0-bundle-"));

const entries = {
  catalogue: `import * as echarts from "echarts/core";
import { LineChart, BarChart, PieChart, ScatterChart, BoxplotChart, CandlestickChart, HeatmapChart, TreemapChart, RadarChart, FunnelChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent, DataZoomComponent, MarkPointComponent, MarkLineComponent, AriaComponent, DatasetComponent, GraphicComponent, RadarComponent, AxisPointerComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { LabelLayout, UniversalTransition } from "echarts/features";
echarts.use([LineChart, BarChart, PieChart, ScatterChart, BoxplotChart, CandlestickChart, HeatmapChart, TreemapChart, RadarChart, FunnelChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent, DataZoomComponent, MarkPointComponent, MarkLineComponent, AriaComponent, DatasetComponent, GraphicComponent, RadarComponent, AxisPointerComponent, CanvasRenderer, LabelLayout, UniversalTransition]);
window.__echarts = echarts;
`,
  line_and_bar_only: `import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, CanvasRenderer]);
window.__echarts = echarts;
`,
};
writeFileSync(
  path.join(work, "vite.config.mjs"),
  `export default { root: ${JSON.stringify(work)}, logLevel: "warn",
  resolve: { alias: [{ find: /^echarts\\/(.*)$/, replacement: ${JSON.stringify(echartsDir)} + "/$1.js" }] },
  build: { lib: { entry: process.env.ENTRY, formats: ["es"], fileName: () => process.env.OUTNAME }, minify: true, outDir: "dist", emptyOutDir: false } };\n`,
);

const kb = (n) => Math.round(n / 1024);
const size = (file) => {
  const b = readFileSync(file);
  return { raw_kb: kb(b.length), gzip_kb: kb(gzipSync(b, { level: 9 }).length), brotli_kb: kb(brotliCompressSync(b).length) };
};
const report = {};
for (const [name, source] of Object.entries(entries)) {
  const entry = path.join(work, `${name}.entry.js`);
  writeFileSync(entry, source);
  execFileSync(process.execPath, [path.join(web, "vite/bin/vite.js"), "build", "--config", path.join(work, "vite.config.mjs")], {
    cwd: work, env: { ...process.env, ENTRY: entry, OUTNAME: `${name}.js` }, stdio: "inherit",
  });
  report[`echarts modular, ${name}`] = size(path.join(work, "dist", `${name}.js`));
}
report["echarts.min.js (one-file build)"] = size(path.join(echartsDir, "dist/echarts.min.js"));
report["plotly.min.js (what apps/web ships)"] = size(path.join(web, "plotly.js-dist-min/plotly.min.js"));
console.log(JSON.stringify(report, null, 1), "\nbuilt in", pathToFileURL(work).href);
