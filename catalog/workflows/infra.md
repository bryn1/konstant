---
description: Run an infra task (deploy, service, container, cron, configuration, backup) through placement plan, a backed-up and reversible change, verification of the literal installed artifact, adversarial review and architecture check. Load when a task is [type:infra].
---
## Producer brief

- **Inventory first**: what runs now, which units, files, crons and consumers the change touches;
  read before writing. A change that replaces a running service follows
  `replace-a-running-system` (side effects, consumers, rollback, retirement list).
- **Backup, validate, apply, verify**: back up each file you edit (path in the report), validate the
  candidate (`visudo -cf`, `sshd -t`, `docker compose config --quiet`, a dry run), apply, then check
  the result as the system will run it (skill `infra-hardening`).
- **Rollback stated before apply**, rehearsed once where the change matters; one host at a time.
- **Least machinery**: extend the existing deploy path; no second mechanism for the same job.

## Verification

The tester checks the **literal artifact**: the installed cron line run in its real environment,
the unit `is-active` and `is-enabled` and its produced output, the service answering a request that
proves domain behaviour (not only `/health`), persistence across a restart where claimed. Every
monitor or check added gets a planted red and one real run. Live state that the verifier must
re-check later goes into the evidence as `PROBE:` lines (`systemctl is-active <unit> => ^active$`).

## Exit

DONE.md with DoD, `N1` and surface rows (deploy is never N/A here), the backup paths and rollback in
evidence, CLEANUP line; the check exits 0; close with `PROBE:` lines for the live state.
