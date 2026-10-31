// node:test suite for the konstant-gate dsh plugin (the VENDORED build, konstant-gate.mjs, i.e.
// exactly what `agents sync` installs). The plugin's two seams are driven through a fake cordis
// context (the listeners it registers) and a fake agent (session header, steer, inject); bin/konstant
// is a scripted fake (fake-konstant.mjs) whose replies follow the real CLI's exit codes and JSON.
// The real CLI behind those replies is tested in tests/harness/test_dsh_gate.py and the live e2e.
// Run: node --test tests/harness/dsh_gate/   (tests/harness/test_dsh_gate.py runs it under pytest)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const BUNDLE = process.env.KONSTANT_GATE_BUNDLE
  ?? join(here, '..', '..', '..', 'src', 'konstant', 'harnesses', 'dsh_gate', 'konstant-gate.mjs')
const plugin = await import(pathToFileURL(BUNDLE).href)
const FAKE = join(here, 'fake-konstant.mjs')
const CWD = mkdtempSync(join(tmpdir(), 'konstant-gate-cwd-'))   // the session's directory (must exist)
const HOME = mkdtempSync(join(tmpdir(), 'konstant-gate-ws-'))    // the workspace (KONSTANT_HOME; its var/logs)

const BLOCK = '=== TASK GATE (docs) ===\nphases...\n=== END TASK GATE ==='
const typed = (extra = {}) => ({ code: 0, stdout: JSON.stringify({ type: 'docs', why: 'tag', block: BLOCK, run_dir: '/ws/var/runs/r1', out: '/ws/o', job: null, ...extra }) })
const small = { code: 0, stdout: JSON.stringify({ type: 'small', why: 'small-shape' }) }

function setup(script, config = {}, env = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'konstant-gate-test-'))
  const state = join(dir, 'state.json')
  const log = join(dir, 'calls.jsonl')
  writeFileSync(state, JSON.stringify(script))
  writeFileSync(log, '')
  process.env.FAKE_K_STATE = state
  process.env.FAKE_K_LOG = log
  const saved = {}
  for (const [k, v] of Object.entries(env)) { saved[k] = process.env[k]; process.env[k] = v }
  const handlers = {}
  const registered = []
  const ctx = { logger: { info() {}, warn() {} }, on(ev, fn) { (handlers[ev] ??= []).push(fn) },
    inject(deps, fn) { if (deps.includes('shellEnv')) fn({ shellEnv: { register: (r) => registered.push(r) } }) } }
  plugin.apply(ctx, { konstant: FAKE, home: HOME, ...config })
  for (const [k] of Object.entries(env)) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k] }
  const calls = () => readFileSync(log, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l))
  return { ctx, handlers, calls, registered }
}

function agent(header = {}) {
  const a = { steered: [], injected: [], session: { header: { id: 'session-0001', cwd: CWD, ...header } } }
  a.steer = (m) => a.steered.push(m)
  a.inject = (m) => a.injected.push(m)
  return a
}

const user = (text) => Object.freeze({ role: 'user', id: 'm-1', content: [{ type: 'text', text }], source: { kind: 'user' } })
const text = (m) => m.content.filter(b => b.type === 'text').map(b => b.text).join('')

async function preStep(h, a, msgs) {
  return h.handlers['agent/pre-step'][0]({ agent: a, messages: msgs }, async () => ({ kind: 'continue', messages: msgs }))
}
async function stop(h, a) {
  await h.handlers['agent/turn-stopping'][0]({ agent: a, signal: new AbortController().signal })
}

test('a typed task gets the gate block in place, the original text after it, and arms the loop', async () => {
  const h = setup({ gate: [typed()], check: [{ code: 0 }] })
  const a = agent()
  const d = await preStep(h, a, [user('[type:docs] write USAGE.md')])
  assert.equal(d.messages.length, 1)
  assert.equal(text(d.messages[0]), `${BLOCK}\n[type:docs] write USAGE.md`)
  assert.equal(d.messages[0].source.kind, 'user')
  const g = h.calls()[0]
  assert.deepEqual(g.argv.slice(0, 7), ['task', 'gate', '--json', '--harness', 'dsh', '--cwd', CWD])
  assert.deepEqual(g.argv.slice(7), ['--session', 'session-0001', '-'])
  assert.equal(g.stdin, '[type:docs] write USAGE.md')
  assert.equal(g.home, HOME)
  await stop(h, a)
  assert.deepEqual(h.calls()[1].argv, ['task', 'check', '--offline', '/ws/var/runs/r1'])
  assert.equal(a.steered.length, 0)
  assert.match(text(a.injected[0]), /dod-loop MET after 0 resumes/)
  await stop(h, a)                                     // finished: no second check
  assert.equal(h.calls().length, 2)
})

test('a small task passes unchanged and arms nothing', async () => {
  const h = setup({ gate: [small] })
  const a = agent()
  const msgs = [user('what is the board?')]
  const d = await preStep(h, a, msgs)
  assert.equal(d.messages, msgs)
  await stop(h, a)
  assert.equal(h.calls().length, 1)
})

test('empty and /-command messages are never gated', async () => {
  const h = setup({})
  const a = agent()
  await preStep(h, a, [user('  '), user('/compact')])
  assert.equal(h.calls().length, 0)
})

test('UNMET resumes the same turn with the reasons, then MET', async () => {
  const h = setup({ gate: [typed()], check: [{ code: 3, stdout: 'DONE: no DONE.md in OUT\nphases: REVIEW-verdict.md missing\n' }, { code: 0 }] })
  const a = agent()
  await preStep(h, a, [user('[type:docs] write USAGE.md')])
  await stop(h, a)
  assert.equal(a.steered.length, 1)
  assert.match(text(a.steered[0]), /resume 1\/3\): unmet - DONE: no DONE.md in OUT/)
  assert.match(text(a.steered[0]), /REVIEW-verdict.md missing/)
  assert.equal(a.steered[0].source.kind, 'konstant-gate')        // a nudge is never re-gated
  await preStep(h, a, [a.steered[0]])
  assert.equal(h.calls().filter(c => c.argv[1] === 'gate').length, 1)
  await stop(h, a)
  assert.match(text(a.injected.at(-1)), /MET after 1 resumes/)
})

test('the first unmet reason repeating unchanged stops the loop early', async () => {
  const same = { code: 3, stdout: 'DONE: no DONE.md in /ws/var/runs/r1/out at 2026-10-30T10:00:00Z\n' }
  const again = { code: 3, stdout: 'DONE: no DONE.md in /ws/var/runs/r1/out at 2026-10-30T11:11:11Z\n' }
  const h = setup({ gate: [typed()], check: [same, again] })
  const a = agent()
  await preStep(h, a, [user('[type:docs] x.md')])
  await stop(h, a)
  await stop(h, a)
  assert.equal(a.steered.length, 1)
  assert.match(text(a.injected.at(-1)), /STOP - first unmet reason repeated unchanged/)
})

test('the resume cap ends UNMET', async () => {
  const h = setup({ gate: [typed()], check: [{ code: 3, stdout: 'a\n' }, { code: 3, stdout: 'b\n' }] }, { maxResumes: 1 })
  const a = agent()
  await preStep(h, a, [user('[type:docs] x.md')])
  await stop(h, a)
  await stop(h, a)
  assert.equal(a.steered.length, 1)
  assert.match(text(a.injected.at(-1)), /UNMET after 1 resumes: b/)
})

test('BLOCKED is reported and never resumed; a check error is never MET', async () => {
  for (const [reply, want] of [[{ code: 4, stdout: 'D1 | claim | BLOCKED\n' }, /BLOCKED after 0 resumes/],
                               [{ code: 5, stderr: 'boom' }, /CHECK-ERROR \(task check exit 5\)/],
                               [{ code: 3, stdout: '' }, /CHECK-ERROR/]]) {
    const h = setup({ gate: [typed()], check: [reply] })
    const a = agent()
    await preStep(h, a, [user('[type:docs] x.md')])
    await stop(h, a)
    assert.equal(a.steered.length, 0)
    assert.match(text(a.injected.at(-1)), want)
    assert.doesNotMatch(text(a.injected.at(-1)), /MET after/)
  }
})

test('a failing gate never blocks: the text goes through UNGATED with a visible notice', async () => {
  const h = setup({ gate: [{ code: 1, stderr: 'konstant: board unreachable' }] })
  const a = agent()
  const msgs = [user('[type:docs] x.md')]
  const d = await preStep(h, a, msgs)
  assert.equal(d.messages, msgs)
  assert.match(text(a.injected[0]), /went through UNGATED - konstant: board unreachable/)
  await stop(h, a)
  assert.equal(h.calls().length, 1)
})

test('a delegated child (subagent origin or depth >= 1) is never gated and never armed', async () => {
  for (const header of [{ origin: 'subagent' }, { delegationDepth: 1 }]) {
    const h = setup({})
    const a = agent(header)
    const msgs = [user('[type:docs] x.md')]
    assert.equal((await preStep(h, a, msgs)).messages, msgs)
    await stop(h, a)
    assert.equal(h.calls().length, 0)
  }
})

test('inside a konstant task run phase the plugin installs nothing', async () => {
  const h = setup({}, {}, { KONSTANT_IN_TASK: '1' })
  assert.equal(h.handlers['agent/pre-step'], undefined)
  assert.equal(h.handlers['agent/turn-stopping'], undefined)
})

test('MET with a job: close + verify PASS ends verified; the job tag is added once', async () => {
  const close = { code: 0, stdout: JSON.stringify({ verdict: 'PASS', reasons: [], status: 'verified', job: 7 }) }
  const h = setup({ gate: [typed({ job: 7, job_display: '1.2' })], check: [{ code: 0 }], close: [close] })
  const a = agent()
  const d = await preStep(h, a, [user('[type:docs] write USAGE.md')])
  assert.match(text(d.messages[0]), /\n\[job:1\.2\] \[type:docs\] write USAGE\.md$/)
  await stop(h, a)
  assert.deepEqual(h.calls()[2].argv, ['task', 'close', '--json', '/ws/var/runs/r1'])
  assert.match(text(a.injected.at(-1)), /job 7 closed and verified \(konstant verify PASS, status verified\)/)
})

test('verify FAIL resumes with the verifier reasons on its own budget, then PASS', async () => {
  const fail = { code: 3, stdout: JSON.stringify({ verdict: 'FAIL', reasons: ['PROBE grep -c x USAGE.md: no match'], status: 'queued' }) }
  const pass = { code: 0, stdout: JSON.stringify({ verdict: 'PASS', reasons: [], status: 'verified' }) }
  const h = setup({ gate: [typed({ job: 7 })], check: [{ code: 0 }, { code: 3, stdout: 'x\n' }, { code: 0 }], close: [fail, pass] }, { maxResumes: 1 })
  const a = agent()
  const d = await preStep(h, a, [user('[job:7] [type:docs] write USAGE.md')])
  assert.doesNotMatch(text(d.messages[0]), /\[job:7\] \[job:7\]/)      // tagged once
  await stop(h, a)                                     // MET -> close -> FAIL -> resume
  assert.match(text(a.steered[0]), /konstant verify FAIL for job 7 \(round 1\/3\): PROBE grep -c x USAGE.md: no match/)
  await stop(h, a)                                     // UNMET: the reset budget allows a resume
  assert.equal(a.steered.length, 2)
  await stop(h, a)                                     // MET -> close -> PASS
  assert.match(text(a.injected.at(-1)), /closed and verified/)
})

test('verify FAIL past maxVerifyRounds and verify BLOCKED end with a notice, no resume', async () => {
  const fail = { code: 3, stdout: JSON.stringify({ verdict: 'FAIL', reasons: ['r'], status: 'queued' }) }
  const h = setup({ gate: [typed({ job: 7 })], check: [{ code: 0 }], close: [fail] }, { maxVerifyRounds: 0 })
  const a = agent()
  await preStep(h, a, [user('[type:docs] x.md')])
  await stop(h, a)
  assert.equal(a.steered.length, 0)
  assert.match(text(a.injected.at(-1)), /job 7 ended: konstant verify FAIL - r/)
  const blocked = { code: 4, stdout: JSON.stringify({ verdict: 'BLOCKED', reasons: ['no DoD probe matched'] }) }
  const h2 = setup({ gate: [typed({ job: 8 })], check: [{ code: 0 }], close: [blocked] })
  const a2 = agent()
  await preStep(h2, a2, [user('[type:docs] x.md')])
  await stop(h2, a2)
  assert.match(text(a2.injected.at(-1)), /job 8 ended: konstant verify BLOCKED - no DoD probe matched/)
})

test('fileJob: the gate files/binds by session; MET without a job is UNBOUND, never plain MET', async () => {
  const h = setup({ gate: [typed()], check: [{ code: 0 }] }, { fileJob: true })
  const a = agent()
  await preStep(h, a, [user('[type:docs] x.md')])
  assert.deepEqual(h.calls()[0].argv.slice(7), ['--session', 'session-0001', '--file-job', '-'])
  await stop(h, a)
  assert.match(text(a.injected.at(-1)), /UNBOUND/)
})

test('a new typed message re-arms: a fresh run replaces the old loop', async () => {
  const h = setup({ gate: [typed(), typed({ run_dir: '/ws/var/runs/r2' })], check: [{ code: 0 }] })
  const a = agent()
  await preStep(h, a, [user('[type:docs] one.md')])
  await preStep(h, a, [Object.freeze({ ...user('[type:docs] two.md'), id: 'm-2' })])
  await stop(h, a)
  assert.deepEqual(h.calls()[2].argv, ['task', 'check', '--offline', '/ws/var/runs/r2'])
})

test('normReason strips run paths, timestamps, shas and long numbers', () => {
  const n = plugin.normReason
  assert.equal(n('x /r/1 at 2026-10-30T10:00:00Z sha 0123456789abcdef0123 n 1761820800', '/r/1'),
    'x <run> at <ts> sha <sha> n <n>')
})

test('a delegated child\'s bash acts as worker; the session\'s own bash is untouched', async () => {
  const h = setup({})
  assert.equal(h.registered.length, 1)
  const env = h.registered[0]
  assert.equal(env.name, 'konstant-gate')
  assert.deepEqual(env.resolve({ agent: agent({ origin: 'subagent' }) }), { KONSTANT_ROLE: 'worker', KONSTANT_IN_TASK: '1' })
  assert.deepEqual(env.resolve({ agent: agent({ delegationDepth: 2 }) }), { KONSTANT_ROLE: 'worker', KONSTANT_IN_TASK: '1' })
  assert.deepEqual(env.resolve({ agent: agent() }), {})
  assert.deepEqual(env.resolve({}), {})
})

test('every decision is logged to var/logs/konstant-gate.log of the workspace', async () => {
  const h = setup({ gate: [typed()], check: [{ code: 3, stdout: 'r1\n' }] })
  const a = agent()
  await preStep(h, a, [user('[type:docs] logged.md')])
  await stop(h, a)
  const log = readFileSync(join(HOME, 'var', 'logs', 'konstant-gate.log'), 'utf8')
  assert.match(log, /decision session=session-0001 type=docs/)
  assert.match(log, /dod-loop ARMED session=session-0001 type=docs job=null run=\/ws\/var\/runs\/r1/)
  assert.match(log, /dod-loop resume 1\/3 session=session-0001: r1/)
})
