"""The scenario writer's memory without a token (memory/view.py): konstant exports what the
`scenario` identity may read (the shared pool, the sealed pool) into its drafts dir, the phase's
MCP server recalls from that copy and writes notes there, and konstant stores them afterwards
into the sealed pool, which no producer reads. The intake run drives it through the real dsh
adapter and konstant's jail."""
from __future__ import annotations

import json

from konstant.client import ClientError
from konstant.memory import view
from tests.factory.test_scenario_isolation import iws  # noqa: F401  (fixture)
from tests.factory.test_intake import intake
from tests.holdout.conftest import needs_jail


class BoardClient:
    """konstant.client.Client's get/post over the TestClient, as one identity."""

    def __init__(self, mb, who):
        self.mb, self.who = mb, who

    def get(self, path, **params):
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
        r = self.mb.call(self.who, "GET", path + (f"?{qs}" if qs else ""))
        if r.status_code != 200:
            raise ClientError(r.text, r.status_code)
        return r.json()

    def post(self, path, body):
        r = self.mb.call(self.who, "POST", path, body)
        if r.status_code != 200:
            raise ClientError(r.text, r.status_code)
        return r.json()


def test_view_reads_the_shared_pool_and_its_notes_land_sealed(mb, tmp_path):
    job = mb.insert_job("verified", type="code", title="old")
    run = mb.home / "var" / "runs" / "r-old"
    run.mkdir(parents=True)
    (run / "record.json").write_text(json.dumps({"job": job}))
    mb.store("worker", "greeting lesson: names are used verbatim", run="r-old")
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    env = view.prepare(BoardClient(mb, "scenario"), drafts)
    vc = view.ViewClient(env[view.VIEW_ENV], env[view.OUT_ENV])
    res = vc.get("/api/memory/recall", q="greeting")
    assert res["hits"][0]["path"].startswith("shared/worker/facts/")
    assert res["hits"][0]["trust"] == f"verified job {job}" and "read-only view" in res["mode"]
    vc.post("/api/memory/note", {"title": "scenario lesson", "text": "zebra inputs only"})
    stored = view.collect(BoardClient(mb, "scenario"), drafts)
    assert stored == ["sealed/scenario/scenario lesson.md"]
    assert not (drafts / ".memory").exists()
    assert mb.paths("worker", "zebra") == [] and mb.paths("verifier", "zebra") == stored


def test_view_client_has_no_other_board_route(tmp_path):
    (tmp_path / "v").mkdir()
    (tmp_path / "o").mkdir()
    vc = view.ViewClient(str(tmp_path / "v"), str(tmp_path / "o"))
    for path in ("/api/jobs", "/api/memory/notes", "/api/memory/export"):
        try:
            vc.get(path)
        except ClientError:
            continue
        raise AssertionError(f"{path} answered")


@needs_jail
def test_intake_scenario_writer_recalls_the_shared_pool_and_writes_sealed(iws):
    iws.ok("--as", "worker", "memory", "store", "greeting lesson: names are used verbatim")
    res = intake(iws, "scenario-memory")
    assert res.returncode == 0, res.stderr[-2000:]
    store = iws.home / "var" / "holdout"
    runs = sorted((store / "2" / "runs").iterdir())
    log = next((runs[-1] / "phases").glob("*.log")).read_text()
    lines = [ln for ln in log.splitlines() if ln.startswith("scenario-memory: ")]
    assert any("greeting lesson" in ln for ln in lines), lines          # read the shared pool
    assert any("sealed pool" in ln for ln in lines), lines             # its note went behind glass
    sealed = [n["path"] for n in iws.json("--as", "owner", "memory", "list", "--pool",
                                          "sealed")["notes"]]
    assert "sealed/scenario/scenario lesson.md" in sealed
    for who in ("worker", "planner", "orchestrator"):
        got = iws.json("--as", who, "memory", "recall", "proof", "inputs")["hits"]
        assert all(not h["path"].startswith("sealed/") for h in got), who
    assert not (store / "2" / "drafts").exists()                        # .memory went with it
