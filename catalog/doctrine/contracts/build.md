Your deliverable is a **BUILD**: changed code (or configuration) that is **committed** in the
project's git tree. A report about the work is not the work. If you cannot commit, you are BLOCKED:
say so with the exact command and error that stopped you. Never write a diagnosis and return
success; that records delivery over work that did not happen.

- **Prove it runs.** Run the build, the tests, the entry point; paste the summary line with its
  count and exit code. `no tests ran` / `collected 0 items` is not tested.
- **Never write a verdict file** (`*-verdict.md`). Verdicts belong to the verifying phases; a
  producer that writes one is refused by the DoD check (AUTHORSHIP).
- **File hygiene.** One concern per file. Source files: target about 250 lines; over 400 lines
  needs a `reason: <why>` line in the first 5 lines; a project file this run grows past 600 lines
  without one fails the check. Tests up to 600. Generated, vendored, data and config files are
  exempt. Write the plain version first and extract a shared unit only once it is used twice,
  outgrows the target or mixes concerns. Splitting is part of the DoD, not follow-up work.
- **No unfinished-work markers** (`TODO`, `FIXME`, `XXX`) added where the DoD asked for behaviour.
- **Scratch goes under `OUT/.tmp/`**; no untracked file is left outside OUT when you finish.
