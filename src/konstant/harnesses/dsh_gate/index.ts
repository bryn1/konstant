/**
 * konstant-gate: konstant's task gate and DoD loop inside a DeepSeek Harness (dsh) session (web UI,
 * tui or headless), so a person driving dsh gets the same loop as `konstant task run`.
 * Built onto konstant's CLI: every rule lives in konstant (Python); this plugin only wires dsh's seams to it.
 *
 *  (a) TASK GATE (`agent/pre-step`, waterfall): every user message of the session that is not
 *      empty, not a `/`-command and not from a delegated child goes through
 *      `konstant task gate --json --cwd <session cwd> -`. A typed task's text is replaced, in
 *      place, by the gate block + the original text (the run record is written by konstant). A
 *      small task passes unchanged. A gate that fails never blocks the session: the text goes
 *      through UNGATED and a visible notice says so.
 *  (b) DoD LOOP (`agent/turn-stopping` + `agent.steer()`): at the natural end of a gated turn
 *      `konstant task check --offline <run>` runs. 0 MET; 3 UNMET -> a resume nudge is steered
 *      into the SAME turn, up to `maxResumes`, and the loop stops early when the first unmet
 *      reason repeats unchanged; 4 BLOCKED -> notice, never resumed; anything else -> CHECK-ERROR
 *      notice, never MET, never resumed.
 *  (c) VERIFIER HAND-OFF: MET with a bound job -> `konstant task close <run>` (close the job with
 *      the check as evidence, then `konstant verify`). PASS -> verified; FAIL -> resume with the
 *      verifier's reasons, its own budget `maxVerifyRounds` (the board's max_rounds), the UNMET
 *      budget reset; BLOCKED or an error -> notice. MET with `fileJob` on and no job -> UNBOUND.
 *  (d) LEAVES ARE NEVER GATED: a delegated child (session header `origin === 'subagent'` or
 *      `delegationDepth >= 1`) passes untouched with no loop, and inside a `konstant task run`
 *      phase (KONSTANT_IN_TASK=1, the runner drives the loop) the plugin installs nothing.
 *  (e) A CHILD ACTS AS WORKER (`shellEnv`, the seam the replaced kb-guard plugin used): every bash
 *      call of a delegated child gets KONSTANT_ROLE=worker and KONSTANT_IN_TASK=1, so the konstant
 *      CLI it runs refuses every token but worker and viewer (a phase never files, claims, closes
 *      or verifies; the session, the orchestrator, does).
 *
 * konstant is run with node:child_process (argv, never a shell) and outside dsh's tool sandbox:
 * it is the workspace's own machinery, writing its run records under var/. The plugin imports
 * no dsh package at run time (types only), so the vendored build loads from any path.
 * @module konstant-gate
 */

import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { appendFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent, PreStepDecision } from '@deepseek-ai/dsh-agent'
import type { ContentBlock, UserMessage } from '@deepseek-ai/dsh-llm'

export const name = 'konstant-gate'

/** Plugin config: written by `konstant agents sync` into .dsh/konstant-session.patch.yml. */
export interface Config {
  /** Absolute path of the workspace's bin/konstant. */
  konstant: string
  /** The workspace (KONSTANT_HOME). */
  home: string
  enabled?: boolean
  /** [gate] max_resumes: DoD-loop resume nudges per gated task. */
  maxResumes?: number
  /** [board.policy] max_rounds: verify FAIL resumes per gated task. */
  maxVerifyRounds?: number
  /** [gate] verify_after_close: at MET with a job, close it and run `konstant verify`. */
  verify?: boolean
  /** [gate] file_job: file and claim a board job for a typed task that names none. */
  fileJob?: boolean
  gateTimeoutMs?: number
  checkTimeoutMs?: number
  verifyTimeoutMs?: number
}

const SOURCE_KIND = 'konstant-gate'

interface Result { code: number; stdout: string; stderr: string }

/** One gated task's loop state (per agent; a new typed message re-arms it). */
interface LoopState {
  run: string
  job: string | null
  resumes: number
  verifyRounds: number
  prevFirst?: string | undefined
  finished: boolean
  cwd: string
}

/** The text of a message, joined over its text blocks. */
function textOf(content: readonly ContentBlock[]): string {
  return content.filter((b): b is Extract<ContentBlock, { type: 'text' }> => b.type === 'text').map(b => b.text).join('')
}

/** Never gate: empty messages and `/`-commands. */
function gateable(text: string): boolean {
  const t = text.trim()
  return t.length > 0 && !t.startsWith('/')
}

/** Delegation depth: 0 = the session itself; a header saying `origin: 'subagent'` is never below 1. */
function depthOf(agent: Agent): number {
  const h = agent.session.header as { origin?: string; delegationDepth?: number }
  const runtime = (agent as unknown as { options?: { subagentDepth?: number } }).options?.subagentDepth
  const depth = Math.max(h.delegationDepth ?? 0, typeof runtime === 'number' ? runtime : 0)
  return h.origin === 'subagent' ? Math.max(depth, 1) : depth
}

/** A delegated child (dsh's persisted childSessionMeta() markers): never gated, no loop. */
function isLeaf(agent: Agent): boolean {
  return depthOf(agent) >= 1
}

/** The environment a bash call of `agent` gets from this plugin: a child acts as worker. */
export function childEnv(agent: Agent | undefined): Record<string, string> {
  return agent !== undefined && depthOf(agent) >= 1 ? { KONSTANT_ROLE: 'worker', KONSTANT_IN_TASK: '1' } : {}
}

/** A reason with run-specific noise removed, so "the same reason again" is a string comparison. */
export function normReason(reason: string, run: string): string {
  const r = run === '' ? reason : reason.split(run).join('<run>')
  return r
    .replace(/\d{4}-\d{2}-\d{2}[T ][0-9:.]+(?:Z|[+-][0-9:]+)?/g, '<ts>')
    .replace(/\b[0-9a-f]{12,64}\b/g, '<sha>')
    .replace(/\d{9,}/g, '<n>')
    .replace(/\s+/g, ' ')
    .trim()
}

/** A konstant-made user message (the shape dsh-llm's createUserMessage builds: frozen, fresh id). */
function message(text: string, summary: string): UserMessage {
  return Object.freeze({
    role: 'user', id: randomUUID(), content: [{ type: 'text', text }],
    source: { kind: SOURCE_KIND, form: 'notice', summary },
  }) as unknown as UserMessage
}

export function nudgeText(resumes: number, max: number, reasons: string[]): string {
  return `konstant DoD LOOP (mechanical, resume ${resumes}/${max}): unmet - ${reasons[0] ?? '?'}. Continue: fix the `
    + 'unmet condition(s), re-run the verifying phases the gate named (each writes a NEW verdict file with its '
    + '# JUDGED line), wait until every child has delivered, then end your turn: the check runs again. Do not end '
    + `your turn while a child is running. Full unmet list: ${reasons.join(' | ')}`
}

export function verifyText(job: string, round: number, max: number, reasons: string[]): string {
  return `konstant verify FAIL for job ${job} (round ${round}/${max}): ${reasons.join(' | ') || 'no reasons returned'}. `
    + 'Fix the findings, re-run the verifying phases (new verdict files with fresh # JUDGED lines), then end your '
    + 'turn: the DoD check, the close and the verifier run again.'
}

/** Run bin/konstant with argv (no shell) and `stdin`; 124 on timeout, 127 when it cannot start. */
export function runKonstant(cfg: Config, args: string[], stdin: string, cwd: string, timeoutMs: number): Promise<Result> {
  return new Promise((resolve) => {
    const env: Record<string, string | undefined> = { ...process.env, KONSTANT_HOME: cfg.home }
    for (const k of ['KONSTANT_IN_TASK', 'KONSTANT_RUN', 'KONSTANT_ROLE']) delete env[k]
    let child
    try {
      child = spawn(cfg.konstant, args, { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] })
    } catch (error: unknown) {
      resolve({ code: 127, stdout: '', stderr: String(error) })
      return
    }
    let stdout = ''
    let stderr = ''
    let done = false
    const finish = (r: Result): void => {
      if (done) return
      done = true
      clearTimeout(timer)
      resolve(r)
    }
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      finish({ code: 124, stdout, stderr: `${stderr}\nkonstant-gate: timed out after ${String(timeoutMs)} ms` })
    }, timeoutMs)
    child.stdout.on('data', (d: Buffer) => { stdout += d.toString() })
    child.stderr.on('data', (d: Buffer) => { stderr += d.toString() })
    child.on('error', (e: Error) => finish({ code: 127, stdout, stderr: `${stderr}${String(e)}` }))
    child.on('close', (code: number | null) => finish({ code: code ?? 1, stdout, stderr }))
    child.stdin.on('error', () => {})
    child.stdin.end(stdin)
  })
}

const tail = (s: string): string => (s.trim().split('\n').pop() ?? '').slice(0, 300)
const lines = (s: string): string[] => s.split('\n').map(l => l.trim()).filter(l => l.length > 0)

/**
 * Install the gate's listeners (scoped to `ctx`, disposed with it).
 * @param ctx - plugin context.
 * @param config - see {@link Config}.
 */
export function apply(ctx: Context, config: Config): void {
  const cfg: Required<Config> = {
    enabled: true, maxResumes: 3, maxVerifyRounds: 3, verify: true, fileJob: false,
    gateTimeoutMs: 120_000, checkTimeoutMs: 1_200_000, verifyTimeoutMs: 3_600_000, ...config,
  }
  // every decision: dsh's logger AND var/logs/konstant-gate.log of the workspace (the record a
  // person or a test reads afterwards; dsh's headless mode does not print plugin log lines)
  const log = (level: 'info' | 'warn', text: string): void => {
    const logger = (ctx as unknown as { logger?: Record<string, (s: string) => void> }).logger
    logger?.[level]?.(`konstant-gate: ${text}`)
    try {
      const dir = join(cfg.home, 'var', 'logs')
      mkdirSync(dir, { recursive: true, mode: 0o700 })
      appendFileSync(join(dir, 'konstant-gate.log'), `${new Date().toISOString()} ${level} ${text}\n`, { mode: 0o600 })
    } catch { /* a log that cannot be written never blocks the session */ }
  }
  if (!cfg.enabled) return
  if (process.env.KONSTANT_IN_TASK === '1') {
    // a phase of `konstant task run`: the runner owns the gate and the loop; a phase is a leaf
    log('info', 'inside a konstant task run phase (KONSTANT_IN_TASK=1): not gating')
    return
  }
  const seen = new WeakSet<UserMessage>()
  const loops = new WeakMap<Agent, LoopState>()
  const notice = (agent: Agent, text: string, summary: string): void => { agent.inject(message(text, summary)) }

  ctx.on('agent/disposed', ({ agent }: { agent: Agent }) => { loops.delete(agent) })

  // (e) a delegated child's bash acts as worker (no-op when the profile has no shellEnv service)
  const withEnv = ctx as unknown as { inject?: (deps: string[], fn: (c: { shellEnv: { register: (r: unknown) => void } }) => void) => void }
  withEnv.inject?.(['shellEnv'], (envCtx) => {
    envCtx.shellEnv.register({
      name: 'konstant-gate',
      variables: {
        KONSTANT_ROLE: { description: 'worker in a delegated child: the konstant CLI acts as the worker role.' },
        KONSTANT_IN_TASK: { description: '1 in a delegated child: the konstant CLI refuses every token but worker and viewer.' },
      },
      resolve: (execution: { agent?: Agent }) => childEnv(execution.agent),
    })
  })

  ctx.on('agent/pre-step', async ({ agent }: { agent: Agent }, next: () => Promise<PreStepDecision>): Promise<PreStepDecision> => {
    const decision = await next()
    if (decision.kind === 'reject') return decision
    let out = decision.messages
    for (let i = 0; i < out.length; i += 1) {
      const m = out[i] as UserMessage
      if (m.source.kind !== 'user' || seen.has(m)) continue
      seen.add(m)
      const text = textOf(m.content)
      if (!gateable(text) || isLeaf(agent)) continue
      const sid = String(agent.session.header.id)
      const cwd = (agent.session.header as { cwd?: string }).cwd ?? process.cwd()
      // --session: the job this session works on is bound (var/sessions.json) and claimed
      const args = ['task', 'gate', '--json', '--harness', 'dsh', '--cwd', cwd, '--session', sid]
      if (cfg.fileJob) args.push('--file-job')
      args.push('-')
      const r = await runKonstant(cfg, args, text, cwd, cfg.gateTimeoutMs)
      let g: { type?: string; why?: string; block?: string; run_dir?: string; job?: number | null; job_display?: string | null } = {}
      try { g = JSON.parse(r.stdout) as typeof g } catch { g = {} }
      if (r.code !== 0 || g.type === undefined) {
        log('warn', `gate failed session=${sid} exit=${String(r.code)}: ${tail(r.stderr)}`)
        notice(agent, `konstant gate failed (exit ${String(r.code)}): this message went through UNGATED - ${tail(r.stderr)}`, 'konstant gate failed: ungated')
        continue
      }
      log('info', `decision session=${sid} type=${g.type} why=${String(g.why)}`)
      if (g.type === 'small' || !g.block || !g.run_dir) continue
      const job = g.job === null || g.job === undefined ? null : String(g.job)
      const tagged = job !== null && !/\[job:[0-9.]+\]/.test(text) ? `[job:${g.job_display ?? job}] ` : ''
      const gated = `${g.block}\n${tagged}${text}`
      const at = m.content.findIndex(b => b.type === 'text')
      const content: ContentBlock[] = at === -1
        ? [{ type: 'text', text: gated }, ...m.content]
        : m.content.map((b, idx) => (idx === at && b.type === 'text' ? { ...b, text: gated } : b))
      const replacement = Object.freeze({ ...m, id: randomUUID(), content }) as unknown as UserMessage
      seen.add(replacement)
      out = out.toSpliced(i, 1, replacement)
      loops.set(agent, { run: g.run_dir, job, resumes: 0, verifyRounds: 0, finished: false, cwd })
      log('warn', `dod-loop ARMED session=${sid} type=${g.type} job=${String(job)} run=${g.run_dir}`)
    }
    return out === decision.messages ? decision : { ...decision, messages: out }
  })

  ctx.on('agent/turn-stopping', async ({ agent, signal }: { agent: Agent; signal: AbortSignal }): Promise<void> => {
    const st = loops.get(agent)
    if (st === undefined || st.finished) return
    const sid = String(agent.session.header.id)
    const c = await runKonstant(cfg, ['task', 'check', '--offline', st.run], '', st.cwd, cfg.checkTimeoutMs)
    if (signal.aborted) return
    const finish = (text: string, summary: string): void => {
      st.finished = true
      log('warn', `${summary} session=${sid}`)
      notice(agent, text, summary)
    }
    if (c.code === 0) {
      if (st.job !== null && cfg.verify) {
        const v = await runKonstant(cfg, ['task', 'close', '--json', st.run], '', st.cwd, cfg.verifyTimeoutMs)
        if (signal.aborted) return
        let res: { verdict?: string | null; reasons?: string[]; status?: string } = {}
        try { res = JSON.parse(v.stdout) as typeof res } catch { res = {} }
        const reasons = res.reasons ?? []
        if (v.code === 0) {
          finish(`konstant: DoD MET after ${String(st.resumes)} resumes; job ${st.job} closed and verified (konstant verify PASS, status ${String(res.status)})`, `konstant verify PASS job ${st.job}`)
          return
        }
        if (v.code === 3 && res.verdict === 'FAIL' && st.verifyRounds < cfg.maxVerifyRounds) {
          st.verifyRounds += 1
          st.resumes = 0
          st.prevFirst = undefined
          log('warn', `verify FAIL job=${st.job} session=${sid} round ${String(st.verifyRounds)}/${String(cfg.maxVerifyRounds)}`)
          agent.steer(message(verifyText(st.job, st.verifyRounds, cfg.maxVerifyRounds, reasons), `konstant verify FAIL job ${st.job}`))
          return
        }
        const label = res.verdict ? `konstant verify ${res.verdict}` : `konstant task close exit ${String(v.code)}`
        finish(`konstant: job ${st.job} ended: ${label}${reasons.length ? ` - ${reasons.join('; ').slice(0, 600)}` : ` - ${tail(v.stderr)}`}`, `${label} job ${st.job}`)
        return
      }
      if (st.job === null && cfg.fileJob) {
        finish('konstant: DoD MET but no job; nothing closes (UNBOUND: the gate filed none)', 'dod-loop MET but UNBOUND')
        return
      }
      finish(`konstant: dod-loop MET after ${String(st.resumes)} resumes (run ${st.run})`, `dod-loop MET (${String(st.resumes)} resumes)`)
      return
    }
    const reasons = lines(c.stdout)
    if (c.code === 4) {
      finish(`konstant: dod-loop BLOCKED after ${String(st.resumes)} resumes: ${reasons.join('; ')}`, 'dod-loop BLOCKED')
      return
    }
    if (c.code !== 3 || reasons.length === 0) {
      finish(`konstant: dod-loop CHECK-ERROR (task check exit ${String(c.code)}): ${tail(c.stderr) || reasons.join('; ')}`, 'dod-loop CHECK-ERROR')
      return
    }
    const first = normReason(reasons[0] ?? '', st.run)
    if (st.prevFirst !== undefined && first === st.prevFirst) {
      finish(`konstant: dod-loop STOP - first unmet reason repeated unchanged (round ${String(st.resumes + 1)} == round ${String(st.resumes)}): ${reasons[0] ?? ''}`, `dod-loop UNMET (first reason repeated, ${String(st.resumes)} resumes)`)
      return
    }
    st.prevFirst = first
    if (st.resumes >= cfg.maxResumes) {
      finish(`konstant: dod-loop UNMET after ${String(cfg.maxResumes)} resumes: ${reasons.join('; ')}`, `dod-loop UNMET after ${String(cfg.maxResumes)} resumes`)
      return
    }
    st.resumes += 1
    log('warn', `dod-loop resume ${String(st.resumes)}/${String(cfg.maxResumes)} session=${sid}: ${reasons[0] ?? ''}`)
    agent.steer(message(nudgeText(st.resumes, cfg.maxResumes, reasons), `dod-loop resume ${String(st.resumes)}/${String(cfg.maxResumes)}`))
  })
}

/** Test-only accessor for the pure helpers. */
export const __testonly = { textOf, gateable, isLeaf, depthOf, normReason, nudgeText, verifyText, SOURCE_KIND }
