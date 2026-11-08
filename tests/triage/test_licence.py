"""The licence gate (konstant/triage/licence.py, the DoD rule gate/rules/licence.py): copied code
needs a recorded compatible licence or the DoD check refuses it. Red-then-green per rule, then
through the runner with the fake harness's copy modes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from konstant.gate import check
from konstant.triage import licence
from tests.cli.conftest import Workspace
from tests.gate.conftest import Scenario, done_text

REPO = Path(__file__).resolve().parents[2]
FAKE = f"{sys.executable} {REPO / 'tests' / 'fixtures' / 'fake_harness.py'} {{prompt_file}}"
MIT = "MIT License\n\nPermission is hereby granted, free of charge, to any person ...\n"


@pytest.mark.parametrize("src,proj,ok", [
    ("MIT", "MIT", True), ("BSD-3-Clause", "GPL-3.0-only", True), ("Apache-2.0", "MIT", True),
    ("Apache-2.0", "GPL-2.0-only", False), ("GPL-3.0-only", "MIT", False),
    ("GPL-2.0-or-later", "GPL-3.0-only", True), ("GPL-3.0-only", "GPL-2.0-only", False),
    ("LGPL-2.1-only", "GPL-3.0-only", True), ("MPL-2.0", "GPL-3.0-only", True),
    ("MPL-2.0", "MIT", False), ("unknown", "MIT", False), ("proprietary", "GPL-3.0-only", False),
    ("MIT", None, True), ("GPL-3.0-only", None, False), ("Apache 2.0", "MIT", True),
    ("GPLv3", "GPL-3.0-only", True), ("some-licence", "MIT", False),
])
def test_licence_table(src, proj, ok):
    assert licence.compatible(src, proj)[0] is ok


def test_project_licence_is_read_from_the_usual_places(tmp_path):
    assert licence.project_licence(tmp_path)[0] is None
    (tmp_path / "pyproject.toml").write_text('[project]\nlicense = "Apache-2.0"\n')
    assert licence.project_licence(tmp_path) == ("Apache-2.0", "pyproject.toml")
    (tmp_path / "LICENSE").write_text(MIT)
    assert licence.project_licence(tmp_path) == ("MIT", "LICENSE")
    (tmp_path / "LICENSE").write_text("SPDX-License-Identifier: GPL-3.0-or-later\n")
    assert licence.project_licence(tmp_path)[0] == "GPL-3.0-or-later"


@pytest.fixture()
def scen(tmp_path):
    def make(**kw):
        s = Scenario(tmp_path, use_git=True, **kw)
        s.write("LICENSE", MIT, s.project)
        s.commit("LICENSE")
        s.rec["git_base"] = subprocess.run(["git", "-C", str(s.project), "rev-parse", "HEAD"],
                                           capture_output=True, text=True).stdout.strip()
        s.save()
        return s
    return make


def lic_findings(s):
    return [f for f in check.run_check(s.run_dir, None, True)[3] if f.rule == "licence"]


def copy(s, header: str):
    s.write("greet.py", header + 'def greet():\n    return "hello"\n', s.project)
    s.commit("greet.py")


def test_a_marked_copy_without_a_row_is_refused_red_and_a_row_passes_green(scen):
    s = scen().good()
    assert lic_findings(s) == []                                        # nothing copied
    copy(s, "# adapted from https://example.org/greet.py\n")
    f = lic_findings(s)
    assert f and "greet.py shows a provenance note" in f[0].text and f[0].owner == "producer"
    s.done(done_text(rows=None) + "COPIED | greet.py | https://example.org/greet.py | MIT\n")
    assert lic_findings(s) == []


def test_an_incompatible_or_unknown_licence_is_refused(scen):
    s = scen().good()
    copy(s, "# adapted from https://example.org/greet.py\n")
    for lic, why in (("GPL-3.0-only", "cannot go into a MIT project"),
                     ("unknown", "is not a known licence"), ("", "'missing' is not a known")):
        s.done(done_text() + f"COPIED | greet.py | https://example.org/greet.py | {lic}\n")
        f = lic_findings(s)
        assert f and why in " ".join(x.text for x in f), (lic, [x.text for x in f])


def test_licenses_md_counts_and_an_spdx_header_is_a_mark(scen):
    s = scen().good()
    copy(s, "# SPDX-License-Identifier: BSD-3-Clause\n")
    assert lic_findings(s) and "SPDX-License-Identifier BSD-3-Clause" in lic_findings(s)[0].text
    s.write("LICENSES.md", "COPIED | greet.py | https://github.com/example/greet | BSD-3-Clause\n")
    assert lic_findings(s) == []


def test_a_research_source_url_in_the_code_needs_a_row(scen):
    s = scen().good()
    sd = s.ws / "var" / "research" / s.run_dir.name
    sd.mkdir(parents=True)
    (sd / "result.json").write_text(json.dumps({"parsed": {"sources": [
        {"id": "S1", "url": "https://example.org/greeters/reference", "licence": "MIT"}]}}))
    copy(s, "# see https://example.org/greeters/reference\n")
    assert lic_findings(s) and "research source URL" in lic_findings(s)[0].text
    s.write("DONE.md", "COPIED | greet.py | https://example.org/greeters/reference | MIT\n"
            + done_text())
    assert lic_findings(s) == []


def test_a_document_that_cites_a_source_is_not_a_copy(scen):
    s = scen().good()
    s.write("NOTES.md", "adapted from https://example.org/greet (a reference)\n")
    s.write("README.md", "Ported from https://example.org/greet\n", s.project)
    s.commit("README.md")
    assert lic_findings(s) == []


def test_declined_never_excuses_the_licence_rule(scen):
    s = scen().good()
    copy(s, "# adapted from https://example.org/greet.py\n")
    s.done(done_text() + "DECLINED | greet.py shows a provenance note | job 1\n")
    code, _l, _w, findings = check.run_check(s.run_dir, None, True)
    assert code == 3 and any(f.rule == "licence" for f in findings)
    assert "licence" in check.UNEXCUSABLE and "research" in check.UNEXCUSABLE


# --- through the runner (fake harness copy modes) --------------------------------------------

@pytest.fixture()
def rws(tmp_path):
    w = Workspace(tmp_path)
    proj = tmp_path / "projects" / "demo"
    proj.mkdir(parents=True)
    (proj / "LICENSE").write_text(MIT)
    for args in (["init", "-q", "-b", "main"], ["add", "LICENSE"], ["commit", "-q", "-m", "i"]):
        subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@example.com", "-c",
                        "user.name=t", *args], check=True)
    return w


@pytest.mark.parametrize("mode,rc", [("copy-unrecorded", 3), ("copy-gpl", 3),
                                     ("copy-licensed", 0)])
def test_runner_refuses_copied_code_without_a_compatible_recorded_licence(rws, mode, rc):
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet()", "--project", "demo", "--harness", FAKE,
                          "--max-resumes", "0"], capture_output=True, text=True,
                         env=rws.env(FAKE_HARNESS_MODE=mode), timeout=600, cwd=str(rws.home))
    assert res.returncode == rc, res.stdout + res.stderr
    if rc:
        assert "LICENCE: greet.py" in res.stdout, res.stdout
