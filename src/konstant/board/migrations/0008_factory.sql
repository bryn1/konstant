-- konstant board schema v8: the factory loop's records (docs/LEVEL5.md 6, wave L5-5). Applied by
-- konstant.board.migrate. Written by the board from the factory identity only
-- (board/api/factory.py); read by every token (the Factory tab, `factory status`).
--
-- `budget_ledger`: what the factory spent, append-only. One row per charge: `attempts` and
-- `task_runs` before a job's task run starts (so a run killed with the host still counts),
-- `wall_s`, `phases`, `tokens`, `cost` measured from a finished run's phase manifests. `ref` makes
-- a charge idempotent (a factory that resumes never charges the same run twice).
-- `escalations`: what needed the owner. At most ONE open (unacknowledged) row per (goal, job,
-- kind): the notifier delivers a kind once until the owner acknowledges it (`factory ack`).
-- Only delivered_* and acked_* are ever written after the insert, each once.
-- `factory_log`: append-only; the newest row says whether the factory is halted (a notifier that
-- could not deliver, an internal error) until the owner resumes it.

CREATE TABLE budget_ledger (
  id       INTEGER PRIMARY KEY,
  goal_id  INTEGER REFERENCES goals(id),
  job_id   INTEGER REFERENCES jobs(id),
  kind     TEXT NOT NULL CHECK (kind IN ('wall_s', 'attempts', 'task_runs', 'phases', 'tokens',
             'cost', 'rollbacks')),
  amount   REAL NOT NULL CHECK (amount >= 0),
  ref      TEXT NOT NULL UNIQUE,          -- e.g. attempt:<job>:<n>, run:<run dir>:<kind>
  actor    TEXT NOT NULL,
  at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX budget_ledger_goal ON budget_ledger(goal_id);
CREATE INDEX budget_ledger_job ON budget_ledger(job_id);
CREATE TRIGGER budget_ledger_no_update BEFORE UPDATE ON budget_ledger
  BEGIN SELECT RAISE(ABORT, 'budget_ledger is append-only'); END;
CREATE TRIGGER budget_ledger_no_delete BEFORE DELETE ON budget_ledger
  BEGIN SELECT RAISE(ABORT, 'budget_ledger is append-only'); END;

CREATE TABLE escalations (
  id            INTEGER PRIMARY KEY,
  goal_id       INTEGER REFERENCES goals(id),
  job_id        INTEGER REFERENCES jobs(id),
  kind          TEXT NOT NULL CHECK (kind IN ('BLOCKED', 'DECISION', 'BUDGET_STOP', 'LEAK',
                  'ROLLBACK_FAILED', 'HALTED')),
  reason        TEXT NOT NULL,
  event_id      INTEGER,                -- the line in var/factory/events.jsonl
  delivered_at  TEXT,
  delivered_to  TEXT,
  acked_by      TEXT,
  acked_at      TEXT,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE UNIQUE INDEX escalations_one_open ON escalations(coalesce(goal_id, 0), coalesce(job_id, 0),
  kind) WHERE acked_by IS NULL;
CREATE TRIGGER escalations_no_delete BEFORE DELETE ON escalations
  BEGIN SELECT RAISE(ABORT, 'escalations are never deleted; acknowledge one'); END;
CREATE TRIGGER escalations_fixed BEFORE UPDATE OF goal_id, job_id, kind, reason, event_id,
  created_at ON escalations
  BEGIN SELECT RAISE(ABORT, 'an escalation''s goal, job, kind and reason are fixed'); END;
CREATE TRIGGER escalations_once BEFORE UPDATE OF delivered_at, delivered_to, acked_by, acked_at
  ON escalations
  WHEN (OLD.delivered_at IS NOT NULL AND NEW.delivered_at IS NOT OLD.delivered_at)
    OR (OLD.acked_by IS NOT NULL AND NEW.acked_by IS NOT OLD.acked_by)
  BEGIN SELECT RAISE(ABORT, 'an escalation is delivered once and acknowledged once'); END;

CREATE TABLE factory_log (
  id      INTEGER PRIMARY KEY,
  state   TEXT NOT NULL CHECK (state IN ('halted', 'resumed')),
  reason  TEXT NOT NULL,
  actor   TEXT NOT NULL,
  at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TRIGGER factory_log_no_update BEFORE UPDATE ON factory_log
  BEGIN SELECT RAISE(ABORT, 'factory_log is append-only'); END;
CREATE TRIGGER factory_log_no_delete BEFORE DELETE ON factory_log
  BEGIN SELECT RAISE(ABORT, 'factory_log is append-only'); END;
