-- konstant board schema v2: sealed holdout scenarios (docs/LEVEL5.md 2.5, 3). Applied by
-- konstant.board.migrate. The board stores a COMMITMENT per scenario (sha256 of its file, the
-- canary inside the file is the salt) and never its content: no column holds a command, an
-- expectation, a hint or a canary (LEVEL5 2.3).

ALTER TABLE jobs ADD COLUMN holdout_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE verifications ADD COLUMN holdout_json TEXT;

CREATE TABLE holdouts (
  id            INTEGER PRIMARY KEY,
  job_id        INTEGER NOT NULL REFERENCES jobs(id),
  hid           TEXT NOT NULL CHECK (hid GLOB 'H[1-9]*' AND hid NOT GLOB 'H*[^0-9]*'),
  kind          TEXT NOT NULL CHECK (kind IN ('proof', 'regression')),
  sha256        TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
  author_label  TEXT NOT NULL,
  sealed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  trail_id      INTEGER,                -- the `holdout` trail row of the seal: orders it vs claims
  generation    INTEGER NOT NULL DEFAULT 1,   -- the set: a worn or burned set is replaced by n+1
  state         TEXT NOT NULL DEFAULT 'sealed' CHECK (state IN ('sealed', 'burned', 'retired')),
  UNIQUE (job_id, hid)
);
CREATE INDEX holdouts_job ON holdouts(job_id);
CREATE TRIGGER holdouts_no_delete BEFORE DELETE ON holdouts
  BEGIN SELECT RAISE(ABORT, 'holdouts are never deleted; a set is burned or retired'); END;
CREATE TRIGGER holdouts_commitment_immutable BEFORE UPDATE OF job_id, hid, kind, sha256,
  author_label, sealed_at, generation ON holdouts
  BEGIN SELECT RAISE(ABORT, 'a sealed holdout commitment is immutable'); END;
CREATE TRIGGER holdouts_trail_once BEFORE UPDATE OF trail_id ON holdouts
  WHEN OLD.trail_id IS NOT NULL
  BEGIN SELECT RAISE(ABORT, 'a sealed holdout commitment is immutable'); END;
CREATE TRIGGER holdouts_state_forward BEFORE UPDATE OF state ON holdouts
  WHEN NEW.state IS NOT OLD.state AND OLD.state <> 'sealed'
  BEGIN SELECT RAISE(ABORT, 'a burned or retired holdout stays so'); END;

-- trail kinds gain the level-5 kinds (one rebuild for all of them: SQLite cannot alter a CHECK).
DROP TRIGGER trail_no_update;
DROP TRIGGER trail_no_delete;
ALTER TABLE trail RENAME TO trail_v1;
CREATE TABLE trail (
  id            INTEGER PRIMARY KEY,
  job_id        INTEGER NOT NULL REFERENCES jobs(id),
  ts            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  actor         TEXT NOT NULL,
  role          TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('note', 'status', 'evidence', 'verdict', 'finding',
                  'move', 'approval', 'review', 'dod-review', 'holdout', 'ship', 'rollback',
                  'escalation', 'budget')),
  body          TEXT NOT NULL DEFAULT '',
  payload_json  TEXT
);
INSERT INTO trail (id, job_id, ts, actor, role, kind, body, payload_json)
  SELECT id, job_id, ts, actor, role, kind, body, payload_json FROM trail_v1;
DROP TABLE trail_v1;
CREATE INDEX trail_job ON trail(job_id);
CREATE TRIGGER trail_no_update BEFORE UPDATE ON trail
  BEGIN SELECT RAISE(ABORT, 'trail is append-only'); END;
CREATE TRIGGER trail_no_delete BEFORE DELETE ON trail
  BEGIN SELECT RAISE(ABORT, 'trail is append-only'); END;
