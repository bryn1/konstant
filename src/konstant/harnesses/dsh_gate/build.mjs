#!/usr/bin/env node
// Builds index.ts into konstant-gate.mjs, the bundle konstant ships (users need no pnpm/esbuild
// unless they change index.ts). Usage: node build.mjs [--out FILE] [--check]
//   esbuild: $ESBUILD, else `esbuild` on PATH, else <$DSH_SOURCE>/node_modules/.bin/esbuild
//   (a DeepSeek Harness source checkout has it). Every `@deepseek-ai/*` import of index.ts is a
//   type import, so the bundle has no runtime dependency on a dsh package.
//   --check: build to a temp file and exit 1 unless it equals the vendored bundle (same esbuild
//   version) - the "bundle is current" test runs this when esbuild is available.
// The first line records the sha256 of index.ts and the esbuild version; the Python test
// (tests/harness/test_dsh_gate.py) compares that sha with the source on every run.
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const args = process.argv.slice(2)
const outArg = args.includes('--out') ? args[args.indexOf('--out') + 1] : null
const check = args.includes('--check')
const vendored = join(here, 'konstant-gate.mjs')

function esbuildBin() {
  if (process.env.ESBUILD) return process.env.ESBUILD
  const onPath = spawnSync('esbuild', ['--version'], { encoding: 'utf8' })
  if (onPath.status === 0) return 'esbuild'
  if (process.env.DSH_SOURCE) {
    const p = join(process.env.DSH_SOURCE, 'node_modules', '.bin', 'esbuild')
    if (existsSync(p)) return p
  }
  return null
}

const bin = esbuildBin()
if (!bin) {
  console.error('build.mjs: no esbuild (set ESBUILD, put esbuild on PATH, or DSH_SOURCE=<dsh checkout>)')
  process.exit(2)
}
const version = spawnSync(bin, ['--version'], { encoding: 'utf8' }).stdout.trim()
const tmp = mkdtempSync(join(tmpdir(), 'konstant-gate-build-'))
const raw = join(tmp, 'bundle.mjs')
const r = spawnSync(bin, [join(here, 'index.ts'), '--bundle', '--platform=node', '--format=esm',
  '--target=node22', '--external:@deepseek-ai/*', '--external:node:*', '--legal-comments=none',
  '--log-level=warning', `--outfile=${raw}`], { encoding: 'utf8', cwd: here })
if (r.status !== 0) {
  console.error(r.stderr || r.stdout)
  rmSync(tmp, { recursive: true, force: true })
  process.exit(1)
}
const sha = createHash('sha256').update(readFileSync(join(here, 'index.ts'))).digest('hex')
const body = readFileSync(raw, 'utf8').replaceAll(here, '.')
const text = `// konstant-gate source-sha256=${sha} esbuild=${version} (built by build.mjs from index.ts; do not edit)\n${body}`
rmSync(tmp, { recursive: true, force: true })
if (check) {
  const have = existsSync(vendored) ? readFileSync(vendored, 'utf8') : ''
  if (have !== text) {
    console.error('build.mjs --check: konstant-gate.mjs is NOT the build of index.ts: run `node build.mjs`')
    process.exit(1)
  }
  console.log(`build.mjs --check: konstant-gate.mjs is current (esbuild ${version})`)
  process.exit(0)
}
writeFileSync(outArg ?? vendored, text)
console.log(`build.mjs: wrote ${outArg ?? 'konstant-gate.mjs'} (source-sha256=${sha.slice(0, 12)}, esbuild ${version})`)
