# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's private vulnerability reporting:
open the repository's **Security** tab and choose **Report a vulnerability**
(<https://github.com/bryn1/konstant/security/advisories/new>). Do not open a public issue for a
vulnerability.

A useful report names the konstant version (the release you installed), the harness and its
version, the output of `bin/konstant doctor`, and a reproduction: the commands, or a fake harness
that plays the misbehaving agent (see `tests/fixtures/fake_harness.py` for the shape). Reports are
acknowledged on the advisory; a fix ships with a test under `tests/review/` that fails without it.

## Scope

konstant runs coding agents and checks their work by running it. Read
[docs/CONCEPTS.md, "Security model and limits"](docs/CONCEPTS.md#security-model-and-limits)
first: it lists what konstant enforces itself and what it only mitigates (for example, an
unsandboxed phase runs agent-written code with your rights). A way around something listed as
enforced there, a way for an agent to reach `verified` without the work being done, or a way for
a phase to read the owner, orchestrator or verifier token where the docs say it cannot, is in
scope. The limits that page already states are known.

Supported versions: the latest release.
