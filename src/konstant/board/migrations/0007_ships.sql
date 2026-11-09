-- konstant board schema v7: ships and the shipping halt (docs/LEVEL5.md 5, wave L5-4). Applied by
-- konstant.board.migrate. A ship moves a target (a GitHub pull request, a local branch, an apply
-- dir or the owner's command) to the exact commit the verifier passed; the post-ship checks then
-- either keep it or roll it back. Both are recorded here by the board from the factory identity,
-- after the board's own copy of the ship guard (board/api/ships.py) agreed.
--
-- `ships`: one row per attempt. The commit, its pre-ship target tip and the target never change;
-- the state moves only forward: shipping -> shipped | failed (the target was never moved),
-- shipped -> rolled_back | rollback_failed. At most one row is `shipping` per workspace (one ship at
-- a time), and a job ships once (a rolled-back job gets a follow-up job instead).
-- `shipping_log`: append-only; the newest row says whether shipping is halted (a failed rollback
-- halts ALL shipping until the owner resumes it).

CREATE TABLE ships (
  id            INTEGER PRIMARY KEY,
  job_id        INTEGER NOT NULL REFERENCES jobs(id),
  goal_id       INTEGER REFERENCES goals(id),
  target        TEXT NOT NULL CHECK (target IN ('github', 'branch', 'apply', 'command')),
  branch        TEXT,
  commit_sha    TEXT NOT NULL CHECK (length(commit_sha) IN (40, 64)),
  pre_ref       TEXT NOT NULL CHECK (length(pre_ref) IN (40, 64)),
  tip_sha       TEXT,                   -- the target's tip after the ship (github: the merge)
  rollback_sha  TEXT,                   -- the rollback commit (or its merge) when rolled back
  state         TEXT NOT NULL CHECK (state IN ('shipping', 'shipped', 'failed', 'rolled_back',
                  'rollback_failed')),
  post_json     TEXT,                   -- the post-ship checks: names, pass/fail, redacted reasons
  reason        TEXT,
  follow_up_id  INTEGER REFERENCES jobs(id),
  actor         TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX ships_job ON ships(job_id);
CREATE UNIQUE INDEX ships_one_at_a_time ON ships(state) WHERE state = 'shipping';
CREATE UNIQUE INDEX ships_once_per_job ON ships(job_id)
  WHERE state IN ('shipping', 'shipped', 'rolled_back', 'rollback_failed');
CREATE TRIGGER ships_no_delete BEFORE DELETE ON ships
  BEGIN SELECT RAISE(ABORT, 'ships are never deleted'); END;
CREATE TRIGGER ships_fixed BEFORE UPDATE OF job_id, goal_id, target, branch, commit_sha, pre_ref,
  actor, created_at ON ships
  BEGIN SELECT RAISE(ABORT, 'a ship''s commit, base and target are fixed'); END;
CREATE TRIGGER ships_forward BEFORE UPDATE OF state ON ships
  WHEN NEW.state IS NOT OLD.state AND NOT (
       (OLD.state = 'shipping' AND NEW.state IN ('shipped', 'failed'))
    OR (OLD.state = 'shipped' AND NEW.state IN ('rolled_back', 'rollback_failed')))
  BEGIN SELECT RAISE(ABORT, 'a ship''s state only moves forward'); END;
CREATE TRIGGER ships_once BEFORE UPDATE OF tip_sha, rollback_sha, post_json, follow_up_id ON ships
  WHEN (OLD.tip_sha IS NOT NULL AND NEW.tip_sha IS NOT OLD.tip_sha)
    OR (OLD.rollback_sha IS NOT NULL AND NEW.rollback_sha IS NOT OLD.rollback_sha)
    OR (OLD.post_json IS NOT NULL AND NEW.post_json IS NOT OLD.post_json)
    OR (OLD.follow_up_id IS NOT NULL AND NEW.follow_up_id IS NOT OLD.follow_up_id)
  BEGIN SELECT RAISE(ABORT, 'a ship''s result is recorded once'); END;

CREATE TABLE shipping_log (
  id     INTEGER PRIMARY KEY,
  state  TEXT NOT NULL CHECK (state IN ('halted', 'resumed')),
  reason TEXT NOT NULL,
  ship_id INTEGER REFERENCES ships(id),
  actor  TEXT NOT NULL,
  at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TRIGGER shipping_log_no_update BEFORE UPDATE ON shipping_log
  BEGIN SELECT RAISE(ABORT, 'shipping_log is append-only'); END;
CREATE TRIGGER shipping_log_no_delete BEFORE DELETE ON shipping_log
  BEGIN SELECT RAISE(ABORT, 'shipping_log is append-only'); END;
