// Runs the golden-screenshot tests inside the pinned Playwright container (see playwright.config.ts
// for why). `pnpm test:golden` compares; `pnpm test:golden:update` rewrites the `-linux` baselines.
//
// The repo is bind-mounted so baselines land in the working tree, but node_modules is a named
// volume: the host's copy holds Windows/macOS native binaries (vite, rolldown) that cannot run in
// the Linux container, and the volume keeps the container's own install between runs.
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const webDir = resolve(import.meta.dirname, '..')
const repoRoot = resolve(webDir, '..', '..')
const pkg = JSON.parse(readFileSync(resolve(webDir, 'package.json'), 'utf8'))

const playwright = pkg.devDependencies['@playwright/test']
if (!/^\d+\.\d+\.\d+$/.test(playwright)) {
  throw new Error(`@playwright/test must be pinned to an exact version to match the image; got ${playwright}`)
}
const image = `mcr.microsoft.com/playwright:v${playwright}-noble`
const pnpm = pkg.packageManager // "pnpm@x.y.z"

const update = process.argv.includes('--update')
const testArgs = update ? '--update-snapshots' : ''

const inside = [
  'set -e',
  'cd /work/apps/web',
  `npm install --global --silent ${pnpm}`,
  // The store must stay out of the bind mount, or pnpm writes a .pnpm-store into the repo.
  'pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store',
  `pnpm exec playwright test ${testArgs}`,
].join(' && ')

const run = spawnSync(
  'docker',
  [
    'run', '--rm', '--init', '--ipc=host',
    '-v', `${repoRoot}:/work`,
    '-v', 'uadas-web-node-modules:/work/apps/web/node_modules',
    '-e', 'CI=1',
    image,
    'bash', '-c', inside,
  ],
  { stdio: 'inherit' },
)
process.exit(run.status ?? 1)
