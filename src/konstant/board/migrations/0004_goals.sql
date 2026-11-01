-- konstant board schema v4: goals and intake (docs/LEVEL5.md 4, wave L5-3). Applied by
-- konstant.board.migrate. A goal is what the owner asked for and its limits; its spec is copied
-- and hashed once and never changes (the factory reads only that copy). A goal said in the
-- owner's chat is `proposed` until the owner's next message in that same session says yes
-- (4.0 step 2); a proposal that was not confirmed is `withdrawn` and frees its slug.
-- `intake` is the goal's intake state: the board files goal jobs (as the planner identity) and
-- takes their DoD review ONLY while the factory identity holds it at `filing`, so a planner or
-- DoD-reviewer phase cannot file or review around the deterministic filing (4.2 step 3).

CREATE TABLE goals (
  id            INTEGER PRIMARY KEY,
  slug          TEXT NOT NULL,
  project_id    INTEGER NOT NULL REFERENCES projects(id),
  spec_text     TEXT NOT NULL,          -- the bytes as filed (the copy is written from them)
  spec_json     TEXT NOT NULL,          -- the validated spec, defaults applied
  spec_sha256   TEXT NOT NULL CHECK (length(spec_sha256) = 64),
  source        TEXT NOT NULL CHECK (source IN ('file', 'chat')),
  session       TEXT,
  status        TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'paused', 'done',
                  'stopped', 'withdrawn')),
  intake        TEXT NOT NULL DEFAULT 'none' CHECK (intake IN ('none', 'planning', 'filing',
                  'filed', 'refused')),
  created_by    TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE UNIQUE INDEX goals_slug ON goals(slug) WHERE status <> 'withdrawn';
CREATE TRIGGER goals_no_delete BEFORE DELETE ON goals
  BEGIN SELECT RAISE(ABORT, 'goals are never deleted; cancel one'); END;
CREATE TRIGGER goals_spec_immutable BEFORE UPDATE OF slug, project_id, spec_text, spec_json, spec_sha256,
  source, session, created_by, created_at ON goals
  BEGIN SELECT RAISE(ABORT, 'a goal spec is immutable'); END;
CREATE TRIGGER goals_withdrawn_final BEFORE UPDATE OF status ON goals
  WHEN OLD.status IN ('withdrawn', 'stopped', 'done') AND NEW.status IS NOT OLD.status
  BEGIN SELECT RAISE(ABORT, 'a withdrawn, stopped or done goal stays so'); END;
CREATE TRIGGER goals_filed_once BEFORE UPDATE OF intake ON goals
  WHEN OLD.intake = 'filed' AND NEW.intake IS NOT OLD.intake
  BEGIN SELECT RAISE(ABORT, 'a goal is taken in once'); END;

ALTER TABLE jobs ADD COLUMN goal_id INTEGER REFERENCES goals(id);
ALTER TABLE jobs ADD COLUMN budget_json TEXT;
ALTER TABLE jobs ADD COLUMN ship_mode TEXT CHECK (ship_mode IN ('auto', 'decision'));
CREATE INDEX jobs_goal ON jobs(goal_id);
CREATE TRIGGER jobs_goal_immutable BEFORE UPDATE OF goal_id, budget_json, ship_mode ON jobs
  WHEN NEW.goal_id IS NOT OLD.goal_id OR NEW.budget_json IS NOT OLD.budget_json
       OR NEW.ship_mode IS NOT OLD.ship_mode
  BEGIN SELECT RAISE(ABORT, 'a job''s goal, budget and ship mode are set at filing'); END;
