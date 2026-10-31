---
name: security-scan-triage
description: Run the deterministic scanners first - SAST (Semgrep), secret scanning (gitleaks, trufflehog, detect-secrets), dependency audit (pip-audit, npm audit, osv-scanner, Trivy) - triage by reachability, reproduce what you rank high, and report without pasting secret values. Load at the start of a security review or before a release.
---
# Security scan triage

Scanners find the known classes fast and reproducibly; run them before reasoning, over a copy of
the tree and over the diff, never against a live host.

## 1. Static analysis (Semgrep)

```
semgrep --config auto <tree>
semgrep --config p/security-audit --config p/secrets --sarif -o OUT/.tmp/semgrep.sarif <tree>
SEMGREP_BASELINE_REF=<ref> semgrep ci      # only findings new since <ref>; any finding -> exit 1
```

Pattern rules over-fire. Rank by severity **and reachability**: a request parameter reaching a
string-built query is HIGH or CRITICAL; the same pattern on a constant is a false positive. Drop
unreachable hits explicitly and say how many.

## 2. Secrets (gitleaks, trufflehog, detect-secrets)

```
gitleaks detect --source <tree> --report-format json --report-path OUT/.tmp/gitleaks.json
trufflehog filesystem <tree> --json         # can check whether a found key is live
detect-secrets scan <tree> > .secrets.baseline   # flag only new secrets against a baseline
```

Report a found secret by `file:line` and type, **never its value** (your report would re-leak it).
A committed real secret is CRITICAL and the fix is **rotate**, not only remove: history keeps it. A
key confirmed live is CRITICAL by definition; do not test it further. The same secret in several
files is one root cause (compare fingerprints), not several findings.

## 3. Dependencies (SCA)

```
pip-audit -r requirements.txt
npm audit --omit=dev                         # does not audit peerDependencies
osv-scanner scan --lockfile <lockfile>
trivy fs <tree>                              # dependencies, misconfiguration, secrets
```

Prefer lockfile-based scanners (exact versions). Rank by severity and whether the vulnerable code
path is used, and name the fixed version to upgrade to.

## 4. Reproduce before you assert "exploitable"

On a local or sandbox instance only: send the injecting input and show the leak; call the endpoint
without credentials and show the 200. Reproduced is VERIFIED; reasoned only is UNVERIFIED, ranked on
plausible impact and labelled.

## 5. Findings

```
[CRITICAL] <file>:<line> - <class> (rule id / tool / CVE)
  impact: how untrusted input reaches it / what it exposes
  verified: <command and result> | UNVERIFIED (reasoned only)
  fix: parameterize | rotate and remove | upgrade to x.y.z | add the authz check
```

Then hand the flow-level questions to skill `security-review`. A missing tool is BLOCKED for that
family (name it), never silently skipped.
