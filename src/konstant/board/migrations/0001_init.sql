-- konstant board schema v1 (DESIGN §4.1). Applied by konstant.board.migrate.
CREATE TABLE schema_meta (version INTEGER NOT NULL);
INSERT INTO schema_meta (version) VALUES (0);

CREATE TABLE projects (
  id           INTEGER PRIMARY KEY,
  slug         TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  path         TEXT NOT NULL,
  root_job_id  INTEGER,
  status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE jobs (
  id                 INTEGER PRIMARY KEY,
  project_id         INTEGER NOT NULL REFERENCES projects(id),
  parent_id          INTEGER REFERENCES jobs(id),
  type               TEXT NOT NULL,
  title              TEXT NOT NULL,
  brief              TEXT NOT NULL DEFAULT '',
  acceptance         TEXT NOT NULL DEFAULT '',
  status             TEXT NOT NULL CHECK (status IN ('queued', 'waiting_approval', 'claimed',
                       'blocked', 'completed_unverified', 'verified', 'reviewed', 'cancelled')),
  priority           INTEGER NOT NULL DEFAULT 2,
  requested_by       TEXT NOT NULL,
  assignee           TEXT,
  after_id           INTEGER REFERENCES jobs(id),
  approval_required  INTEGER NOT NULL DEFAULT 0,
  verify_round       INTEGER NOT NULL DEFAULT 0,
  closed_by          TEXT,
  evidence_json      TEXT,
  result_summary     TEXT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX jobs_parent ON jobs(parent_id);
CREATE INDEX jobs_status ON jobs(status);

-- acceptance is immutable after insert: the DoD a job was filed with is the DoD it is judged by.
CREATE TRIGGER jobs_acceptance_immutable BEFORE UPDATE OF acceptance ON jobs
  WHEN NEW.acceptance IS NOT OLD.acceptance
  BEGIN SELECT RAISE(ABORT, 'acceptance is immutable'); END;
-- `verified` and `reviewed` are terminal: no update may change the status of such a row.
CREATE TRIGGER jobs_terminal_is_final BEFORE UPDATE OF status ON jobs
  WHEN OLD.status IN ('verified', 'reviewed') AND NEW.status IS NOT OLD.status
  BEGIN SELECT RAISE(ABORT, 'terminal status cannot change'); END;
CREATE TRIGGER jobs_no_delete BEFORE DELETE ON jobs
  BEGIN SELECT RAISE(ABORT, 'jobs are never deleted; cancel instead'); END;

CREATE TABLE trail (
  id            INTEGER PRIMARY KEY,
  job_id        INTEGER NOT NULL REFERENCES jobs(id),
  ts            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  actor         TEXT NOT NULL,
  role          TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('note', 'status', 'evidence', 'verdict', 'finding',
                  'move', 'approval', 'review')),
  body          TEXT NOT NULL DEFAULT '',
  payload_json  TEXT
);
CREATE INDEX trail_job ON trail(job_id);
-- the trail is append-only.
CREATE TRIGGER trail_no_update BEFORE UPDATE ON trail
  BEGIN SELECT RAISE(ABORT, 'trail is append-only'); END;
CREATE TRIGGER trail_no_delete BEFORE DELETE ON trail
  BEGIN SELECT RAISE(ABORT, 'trail is append-only'); END;

CREATE TABLE verifications (
  id           INTEGER PRIMARY KEY,
  job_id       INTEGER NOT NULL REFERENCES jobs(id),
  round        INTEGER NOT NULL,
  actor        TEXT NOT NULL,
  started_at   TEXT,
  finished_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  verdict      TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL', 'BLOCKED')),
  probes_json  TEXT,
  rerun_json   TEXT
);

CREATE TABLE runs (
  id           INTEGER PRIMARY KEY,
  job_id       INTEGER REFERENCES jobs(id),
  run_dir      TEXT NOT NULL,
  type         TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  result       TEXT CHECK (result IN ('MET', 'UNMET', 'BLOCKED', 'ERROR'))
);

CREATE TABLE tokens (
  id          INTEGER PRIMARY KEY,
  role        TEXT NOT NULL CHECK (role IN ('owner', 'orchestrator', 'worker', 'verifier', 'viewer')),
  label       TEXT NOT NULL,
  sha256      TEXT NOT NULL UNIQUE,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
