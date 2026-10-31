---
name: infra-hardening
description: The floor under every host or service change - persistence across reboots, validate-before-install, ordering of config drop-ins, secrets by path, cron's different environment, fail-open vs fail-closed, backups and blast radius. Load before changing a host, service, scheduler, firewall, sudoers or SSH configuration.
---
# Infra hardening

> A control that fails open and logs nothing is worse than no control: it also buys the confidence
> of having one. For every control you add, ask: if this stops working, how would anyone find out?

## Persistence: enable is not started, a reboot is a test

`systemctl enable` arms the next boot only; check `is-active`, the timer list and a real produced
artifact. Runtime tunables (power limits, sysctl set by hand, a firewall ruleset loaded by hand) do
not survive a reboot unless a unit restores them. Verify a firewall after a reboot, or verify the
unit that restores it, never the live ruleset alone.

## Validate before install

- sudoers: `visudo -cf <candidate>` before it goes into `/etc/sudoers.d/`; a broken drop-in can lock
  out sudo entirely.
- sshd: `sshd -t`, and keep an existing session open while reloading.
- compose: `docker compose config --quiet` before `up -d`.
- cron: back up (`crontab -l > backup`), then verify by job count and a content diff, not by exit
  status; a removal by pattern can delete the comment and orphan the job line.

## Ordering is a security property

Many daemons take the first match and load drop-ins in lexical order; a correct directive in a late
file can be a silent no-op (an early-sorting file re-enabling password login). Name hardening
drop-ins to sort first, and verify by asking the daemon for its effective config (`sshd -T`), not by
reading the file.

## Secrets by path, never by value

Root-owned or owner-only (`0600`) files referenced by path; never in a skill, job record, commit
message, log or chat. Compare secrets by fingerprint (`sha256sum | cut -c1-12`), never by echoing.
The same secret in N places means N places to rotate: when N services fail auth together, suspect
one key copied N times. Ask every channel a secret can leave by (logs, memory stores, backups,
pushed repositories), not just the obvious one. Grep the diff before committing.

## Cron is a different machine

Cron's PATH excludes user-installed binaries; a bare command that works in your shell dies with 127
there. Use absolute paths and test the literal installed line in a minimal environment
(`env -i PATH=/usr/bin:/bin sh -c '<line>'`), including its redirect. `CRON_TZ` is ignored by some
cron implementations: write UTC and comment the local time, or use a systemd timer.

## Before a host change, answer four questions

1. What crosses a boundary (network, user, namespace)? 2. Who can read it (enumerate holders, not
intent)? 3. On failure, open or closed, and what does the code path actually do? 4. How would we
notice, and who sees the signal? If you cannot answer the fourth, you are not ready.

## Blast radius

Prefer the change that degrades over the one that breaks: fail closed for authorisation, fail open
for observation (a monitoring hook that crashes must not take the host down). Back up before editing
and put the backup path in the report. Know what a restart destroys (regenerated keys, dropped
in-flight work) before restarting. One host at a time; verify the first before the next.
