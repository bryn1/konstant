-- konstant board schema v9 (wave L5-F2b, REVIEW L5-R2 K-17): ROLLED_BACK becomes an escalation,
-- so the owner hears of every rollback (it was an outcome only, and a follow-up chain could run
-- unseen). SQLite cannot change a CHECK in place: the table is rebuilt with the same columns,
-- rows, index and triggers, and the one new kind.

DROP TRIGGER IF EXISTS escalations_no_delete;
DROP TRIGGER IF EXISTS escalations_fixed;
DROP TRIGGER IF EXISTS escalations_once;
DROP INDEX IF EXISTS escalations_one_open;

CREATE TABLE escalations_v9 (
  id            INTEGER PRIMARY KEY,
  goal_id       INTEGER REFERENCES goals(id),
  job_id        INTEGER REFERENCES jobs(id),
  kind          TEXT NOT NULL CHECK (kind IN ('BLOCKED', 'DECISION', 'BUDGET_STOP', 'LEAK',
                  'ROLLBACK_FAILED', 'HALTED', 'ROLLED_BACK')),
  reason        TEXT NOT NULL,
  event_id      INTEGER,                -- the line in var/factory/events.jsonl
  delivered_at  TEXT,                   -- chat: when an owner turn showed it (K-08)
  delivered_to  TEXT,
  acked_by      TEXT,
  acked_at      TEXT,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
INSERT INTO escalations_v9 (id, goal_id, job_id, kind, reason, event_id, delivered_at,
  delivered_to, acked_by, acked_at, created_at)
  SELECT id, goal_id, job_id, kind, reason, event_id, delivered_at, delivered_to, acked_by,
         acked_at, created_at FROM escalations;
DROP TABLE escalations;
ALTER TABLE escalations_v9 RENAME TO escalations;

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
