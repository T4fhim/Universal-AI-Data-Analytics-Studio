// The bundle budget of the ECharts renderer (CI.8a): `pnpm check:bundle`, a step of the CI `web` job.
//
// Two promises of plans/phase-4-chart-intelligence.md (CI.8a), checked on a real production build:
//  * the initial bundle does not grow: ECharts is a lazy chunk, never in the static import closure of a page;
//  * the lazy chunk stays within BUDGET_KB gzipped (CI.0 measured about 295 KB for the catalogue's import set).
//
// How: a build with UADAS_BUDGET=1 (vite.config.ts) that also builds the gallery, because a production build
// of index.html alone contains no chart code at all, plus a manifest. A page's *static* closure is what the
// browser fetches before any script runs; the ECharts bundle must be reachable only through a dynamic import.
// What is measured for the lazy chunk is its closure minus anything the pages already load, which is what a
// first chart actually costs. Gzip level 9, as in CI.0, so the numbers are comparable.
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const BUDGET_KB = 300
const BUNDLE = 'src/charts/echarts-bundle.ts'
const PAGES = ['index.html', 'charts.html']

const webDir = resolve(import.meta.dirname, '..')
const outDir = resolve(webDir, 'dist-budget')

const build = spawnSync(process.execPath, [resolve(webDir, 'node_modules/vite/bin/vite.js'), 'build'], {
  cwd: webDir,
  env: { ...process.env, UADAS_BUDGET: '1' },
  stdio: 'inherit',
})
if (build.status !== 0) {
  console.error('check-bundle: the build failed')
  process.exit(1)
}

const manifest = JSON.parse(readFileSync(resolve(outDir, '.vite/manifest.json'), 'utf8'))

// The static import closure of a manifest entry: itself and everything it imports without `import()`.
function closure(key, seen = new Set()) {
  if (seen.has(key)) return seen
  seen.add(key)
  for (const child of manifest[key]?.imports ?? []) closure(child, seen)
  return seen
}

const gzipKb = (keys) =>
  [...keys].reduce((sum, key) => sum + gzipSync(readFileSync(resolve(outDir, manifest[key].file)), { level: 9 }).length, 0) / 1024

const failures = []
const bundle = manifest[BUNDLE]
if (!bundle?.isDynamicEntry) {
  failures.push(`${BUNDLE} is not a dynamic entry of the build: ECharts would be loaded up front (or not built at all)`)
}

const initial = new Set()
for (const page of PAGES) {
  if (!manifest[page]) {
    failures.push(`${page} is missing from the build`)
    continue
  }
  const pageClosure = closure(page)
  pageClosure.forEach((key) => initial.add(key))
  if (pageClosure.has(BUNDLE)) failures.push(`${page} imports ${BUNDLE} statically: the ECharts chunk is in the initial load`)
  console.log(`initial load of ${page}: ${gzipKb(pageClosure).toFixed(0)} KB gzip`)
}

// The closure check above only looks for the one module that is meant to be lazy. A static `import 'echarts/core'`
// anywhere a page reaches would put the library into the entry or a shared chunk while that check still passed
// (and made the lazy chunk look smaller), so also look at what the initial chunks are made of, from their source
// maps, and prove the detector works by requiring it to find ECharts in the lazy chunk.
const ECHARTS_SOURCE = /node_modules\/(?:\.pnpm\/(?:echarts|zrender)@[^/]+\/node_modules\/)?(?:echarts|zrender)\//
const madeOfECharts = (key) =>
  JSON.parse(readFileSync(resolve(outDir, `${manifest[key].file}.map`), 'utf8')).sources.some((source) =>
    ECHARTS_SOURCE.test(source.replaceAll('\\', '/')),
  )
for (const key of initial) {
  if (madeOfECharts(key)) failures.push(`${manifest[key].file} is loaded up front and contains ECharts or zrender code`)
}
if (bundle && !madeOfECharts(BUNDLE)) {
  failures.push('the source-map detector found no ECharts in the lazy chunk, so its "none up front" result cannot be trusted')
}

if (bundle) {
  const lazy = [...closure(BUNDLE)].filter((key) => !initial.has(key))
  const kb = gzipKb(lazy)
  console.log(`ECharts lazy chunk (${lazy.length} file${lazy.length === 1 ? '' : 's'}): ${kb.toFixed(0)} KB gzip, budget ${BUDGET_KB} KB`)
  if (kb > BUDGET_KB) failures.push(`the ECharts chunk is ${kb.toFixed(0)} KB gzipped, over the ${BUDGET_KB} KB budget`)
}

if (failures.length > 0) {
  for (const failure of failures) console.error(`check-bundle: ${failure}`)
  process.exit(1)
}
console.log('check-bundle: within budget')
