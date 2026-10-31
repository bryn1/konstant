// konstant-gate source-sha256=47db9a7de50e2274e3e52130d6b6c8e64c30556e5b61969d799f831e8c4e1b30 esbuild=0.28.2 (built by build.mjs from index.ts; do not edit)
// index.ts
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
var name = "konstant-gate";
var SOURCE_KIND = "konstant-gate";
function textOf(content) {
  return content.filter((b) => b.type === "text").map((b) => b.text).join("");
}
function gateable(text) {
  const t = text.trim();
  return t.length > 0 && !t.startsWith("/");
}
function depthOf(agent) {
  const h = agent.session.header;
  const runtime = agent.options?.subagentDepth;
  const depth = Math.max(h.delegationDepth ?? 0, typeof runtime === "number" ? runtime : 0);
  return h.origin === "subagent" ? Math.max(depth, 1) : depth;
}
function isLeaf(agent) {
  return depthOf(agent) >= 1;
}
function childEnv(agent) {
  return agent !== void 0 && depthOf(agent) >= 1 ? { KONSTANT_ROLE: "worker", KONSTANT_IN_TASK: "1" } : {};
}
function normReason(reason, run) {
  const r = run === "" ? reason : reason.split(run).join("<run>");
  return r.replace(/\d{4}-\d{2}-\d{2}[T ][0-9:.]+(?:Z|[+-][0-9:]+)?/g, "<ts>").replace(/\b[0-9a-f]{12,64}\b/g, "<sha>").replace(/\d{9,}/g, "<n>").replace(/\s+/g, " ").trim();
}
function message(text, summary) {
  return Object.freeze({
    role: "user",
    id: randomUUID(),
    content: [{ type: "text", text }],
    source: { kind: SOURCE_KIND, form: "notice", summary }
  });
}
function nudgeText(resumes, max, reasons) {
  return `konstant DoD LOOP (mechanical, resume ${resumes}/${max}): unmet - ${reasons[0] ?? "?"}. Continue: fix the unmet condition(s), re-run the verifying phases the gate named (each writes a NEW verdict file with its # JUDGED line), wait until every child has delivered, then end your turn: the check runs again. Do not end your turn while a child is running. Full unmet list: ${reasons.join(" | ")}`;
}
function verifyText(job, round, max, reasons) {
  return `konstant verify FAIL for job ${job} (round ${round}/${max}): ${reasons.join(" | ") || "no reasons returned"}. Fix the findings, re-run the verifying phases (new verdict files with fresh # JUDGED lines), then end your turn: the DoD check, the close and the verifier run again.`;
}
function runKonstant(cfg, args, stdin, cwd, timeoutMs) {
  return new Promise((resolve) => {
    const env = { ...process.env, KONSTANT_HOME: cfg.home };
    for (const k of ["KONSTANT_IN_TASK", "KONSTANT_RUN", "KONSTANT_ROLE"]) delete env[k];
    let child;
    try {
      child = spawn(cfg.konstant, args, { cwd, env, stdio: ["pipe", "pipe", "pipe"] });
    } catch (error) {
      resolve({ code: 127, stdout: "", stderr: String(error) });
      return;
    }
    let stdout = "";
    let stderr = "";
    let done = false;
    const finish = (r) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve(r);
    };
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish({ code: 124, stdout, stderr: `${stderr}
konstant-gate: timed out after ${String(timeoutMs)} ms` });
    }, timeoutMs);
    child.stdout.on("data", (d) => {
      stdout += d.toString();
    });
    child.stderr.on("data", (d) => {
      stderr += d.toString();
    });
    child.on("error", (e) => finish({ code: 127, stdout, stderr: `${stderr}${String(e)}` }));
    child.on("close", (code) => finish({ code: code ?? 1, stdout, stderr }));
    child.stdin.on("error", () => {
    });
    child.stdin.end(stdin);
  });
}
var tail = (s) => (s.trim().split("\n").pop() ?? "").slice(0, 300);
var lines = (s) => s.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
function apply(ctx, config) {
  const cfg = {
    enabled: true,
    maxResumes: 3,
    maxVerifyRounds: 3,
    verify: true,
    fileJob: false,
    gateTimeoutMs: 12e4,
    checkTimeoutMs: 12e5,
    verifyTimeoutMs: 36e5,
    ...config
  };
  const log = (level, text) => {
    const logger = ctx.logger;
    logger?.[level]?.(`konstant-gate: ${text}`);
    try {
      const dir = join(cfg.home, "var", "logs");
      mkdirSync(dir, { recursive: true, mode: 448 });
      appendFileSync(join(dir, "konstant-gate.log"), `${(/* @__PURE__ */ new Date()).toISOString()} ${level} ${text}
`, { mode: 384 });
    } catch {
    }
  };
  if (!cfg.enabled) return;
  if (process.env.KONSTANT_IN_TASK === "1") {
    log("info", "inside a konstant task run phase (KONSTANT_IN_TASK=1): not gating");
    return;
  }
  const seen = /* @__PURE__ */ new WeakSet();
  const loops = /* @__PURE__ */ new WeakMap();
  const notice = (agent, text, summary) => {
    agent.inject(message(text, summary));
  };
  ctx.on("agent/disposed", ({ agent }) => {
    loops.delete(agent);
  });
  const withEnv = ctx;
  withEnv.inject?.(["shellEnv"], (envCtx) => {
    envCtx.shellEnv.register({
      name: "konstant-gate",
      variables: {
        KONSTANT_ROLE: { description: "worker in a delegated child: the konstant CLI acts as the worker role." },
        KONSTANT_IN_TASK: { description: "1 in a delegated child: the konstant CLI refuses every token but worker and viewer." }
      },
      resolve: (execution) => childEnv(execution.agent)
    });
  });
  ctx.on("agent/pre-step", async ({ agent }, next) => {
    const decision = await next();
    if (decision.kind === "reject") return decision;
    let out = decision.messages;
    for (let i = 0; i < out.length; i += 1) {
      const m = out[i];
      if (m.source.kind !== "user" || seen.has(m)) continue;
      seen.add(m);
      const text = textOf(m.content);
      if (!gateable(text) || isLeaf(agent)) continue;
      const sid = String(agent.session.header.id);
      const cwd = agent.session.header.cwd ?? process.cwd();
      const args = ["task", "gate", "--json", "--harness", "dsh", "--cwd", cwd, "--session", sid];
      if (cfg.fileJob) args.push("--file-job");
      args.push("-");
      const r = await runKonstant(cfg, args, text, cwd, cfg.gateTimeoutMs);
      let g = {};
      try {
        g = JSON.parse(r.stdout);
      } catch {
        g = {};
      }
      if (r.code !== 0 || g.type === void 0) {
        log("warn", `gate failed session=${sid} exit=${String(r.code)}: ${tail(r.stderr)}`);
        notice(agent, `konstant gate failed (exit ${String(r.code)}): this message went through UNGATED - ${tail(r.stderr)}`, "konstant gate failed: ungated");
        continue;
      }
      log("info", `decision session=${sid} type=${g.type} why=${String(g.why)}`);
      if (g.type === "small" || !g.block || !g.run_dir) continue;
      const job = g.job === null || g.job === void 0 ? null : String(g.job);
      const tagged = job !== null && !/\[job:[0-9.]+\]/.test(text) ? `[job:${g.job_display ?? job}] ` : "";
      const gated = `${g.block}
${tagged}${text}`;
      const at = m.content.findIndex((b) => b.type === "text");
      const content = at === -1 ? [{ type: "text", text: gated }, ...m.content] : m.content.map((b, idx) => idx === at && b.type === "text" ? { ...b, text: gated } : b);
      const replacement = Object.freeze({ ...m, id: randomUUID(), content });
      seen.add(replacement);
      out = out.toSpliced(i, 1, replacement);
      loops.set(agent, { run: g.run_dir, job, resumes: 0, verifyRounds: 0, finished: false, cwd });
      log("warn", `dod-loop ARMED session=${sid} type=${g.type} job=${String(job)} run=${g.run_dir}`);
    }
    return out === decision.messages ? decision : { ...decision, messages: out };
  });
  ctx.on("agent/turn-stopping", async ({ agent, signal }) => {
    const st = loops.get(agent);
    if (st === void 0 || st.finished) return;
    const sid = String(agent.session.header.id);
    const c = await runKonstant(cfg, ["task", "check", "--offline", st.run], "", st.cwd, cfg.checkTimeoutMs);
    if (signal.aborted) return;
    const finish = (text, summary) => {
      st.finished = true;
      log("warn", `${summary} session=${sid}`);
      notice(agent, text, summary);
    };
    if (c.code === 0) {
      if (st.job !== null && cfg.verify) {
        const v = await runKonstant(cfg, ["task", "close", "--json", st.run], "", st.cwd, cfg.verifyTimeoutMs);
        if (signal.aborted) return;
        let res = {};
        try {
          res = JSON.parse(v.stdout);
        } catch {
          res = {};
        }
        const reasons2 = res.reasons ?? [];
        if (v.code === 0) {
          finish(`konstant: DoD MET after ${String(st.resumes)} resumes; job ${st.job} closed and verified (konstant verify PASS, status ${String(res.status)})`, `konstant verify PASS job ${st.job}`);
          return;
        }
        if (v.code === 3 && res.verdict === "FAIL" && st.verifyRounds < cfg.maxVerifyRounds) {
          st.verifyRounds += 1;
          st.resumes = 0;
          st.prevFirst = void 0;
          log("warn", `verify FAIL job=${st.job} session=${sid} round ${String(st.verifyRounds)}/${String(cfg.maxVerifyRounds)}`);
          agent.steer(message(verifyText(st.job, st.verifyRounds, cfg.maxVerifyRounds, reasons2), `konstant verify FAIL job ${st.job}`));
          return;
        }
        const label = res.verdict ? `konstant verify ${res.verdict}` : `konstant task close exit ${String(v.code)}`;
        finish(`konstant: job ${st.job} ended: ${label}${reasons2.length ? ` - ${reasons2.join("; ").slice(0, 600)}` : ` - ${tail(v.stderr)}`}`, `${label} job ${st.job}`);
        return;
      }
      if (st.job === null && cfg.fileJob) {
        finish("konstant: DoD MET but no job; nothing closes (UNBOUND: the gate filed none)", "dod-loop MET but UNBOUND");
        return;
      }
      finish(`konstant: dod-loop MET after ${String(st.resumes)} resumes (run ${st.run})`, `dod-loop MET (${String(st.resumes)} resumes)`);
      return;
    }
    const reasons = lines(c.stdout);
    if (c.code === 4) {
      finish(`konstant: dod-loop BLOCKED after ${String(st.resumes)} resumes: ${reasons.join("; ")}`, "dod-loop BLOCKED");
      return;
    }
    if (c.code !== 3 || reasons.length === 0) {
      finish(`konstant: dod-loop CHECK-ERROR (task check exit ${String(c.code)}): ${tail(c.stderr) || reasons.join("; ")}`, "dod-loop CHECK-ERROR");
      return;
    }
    const first = normReason(reasons[0] ?? "", st.run);
    if (st.prevFirst !== void 0 && first === st.prevFirst) {
      finish(`konstant: dod-loop STOP - first unmet reason repeated unchanged (round ${String(st.resumes + 1)} == round ${String(st.resumes)}): ${reasons[0] ?? ""}`, `dod-loop UNMET (first reason repeated, ${String(st.resumes)} resumes)`);
      return;
    }
    st.prevFirst = first;
    if (st.resumes >= cfg.maxResumes) {
      finish(`konstant: dod-loop UNMET after ${String(cfg.maxResumes)} resumes: ${reasons.join("; ")}`, `dod-loop UNMET after ${String(cfg.maxResumes)} resumes`);
      return;
    }
    st.resumes += 1;
    log("warn", `dod-loop resume ${String(st.resumes)}/${String(cfg.maxResumes)} session=${sid}: ${reasons[0] ?? ""}`);
    agent.steer(message(nudgeText(st.resumes, cfg.maxResumes, reasons), `dod-loop resume ${String(st.resumes)}/${String(cfg.maxResumes)}`));
  });
}
var __testonly = { textOf, gateable, isLeaf, depthOf, normReason, nudgeText, verifyText, SOURCE_KIND };
export {
  __testonly,
  apply,
  childEnv,
  name,
  normReason,
  nudgeText,
  runKonstant,
  verifyText
};
