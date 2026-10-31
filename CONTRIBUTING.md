# Contributing

Thanks for helping. konstant is small on purpose; read [docs/DESIGN.md](docs/DESIGN.md) section 1
(principles) before proposing a new mechanism: a change names what it replaces, and every gate
rule ships with a test that must go red without it.

## Dev install

```sh
git clone https://github.com/bryn1/konstant && cd konstant
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

Python >= 3.10 and `git` are required. `bubblewrap` (Linux) lets the jail tests run instead of
skipping; Node.js >= 22 runs the dsh plugin tests.

## Tests

```sh
.venv/bin/python -m pytest -q          # unit, board, CLI, gate, verify, catalog, harness, release, review
bash tests/e2e/fresh_install.sh        # build the tarball, install it fresh, walk a job to verified
bash tests/e2e/one_line.sh             # the same, installed through get.sh from a local server
```

No test calls a model: the runner is exercised with the deterministic fake harness
(`tests/fixtures/fake_harness.py`).

## Release build

```sh
.venv/bin/python -m konstant.release build --version 0.1.0     # needs a clean tree; --worktree otherwise
```

It archives the committed tree (`git archive`, minus the `export-ignore` paths in
`.gitattributes`), scans every file for public-safety patterns (`release/patterns.toml`, plus an
optional maintainer-local `--denylist FILE`), and writes `dist/` with the tarball, `get.sh`, their
`.sha256` files and `SCAN-REPORT.txt`, which must end `RESULT: CLEAN`. After a change to the CLI,
`python -m konstant.release clidoc --write` refreshes docs/CLI.md.

## Pull requests

- One change per pull request, with its tests; `pytest` and the release scan green.
- Edit `catalog/` (the one source), then `bin/konstant agents sync`; never edit generated files.
- Update DESIGN.md in the same change when behaviour changes, and add a CHANGELOG line.

Security problems go through [SECURITY.md](SECURITY.md), not a pull request.
