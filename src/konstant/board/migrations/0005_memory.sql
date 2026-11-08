-- konstant board schema v5: built-in memory (wave L5-M; docs/CONCEPTS.md "Memory"). Applied by
-- konstant.board.migrate. The vault (memory/, its own git repository) holds the notes; this table
-- is the board's append-only record of every write konstant made to it and every write it
-- refused: who (the token's label and role, never a request field), what (path, pool, the
-- sha256 of the file konstant wrote, the vault commit), for which run and job. A note whose file
-- no longer hashes to its latest stored row was changed outside konstant (not attributed).

CREATE TABLE memory_writes (
  id          INTEGER PRIMARY KEY,
  path        TEXT,
  pool   TEXT NOT NULL,
  actor       TEXT NOT NULL,
  role        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('fact', 'note')),
  state       TEXT NOT NULL CHECK (state IN ('stored', 'refused')),
  reason      TEXT,
  sha256      TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
  commit_sha  TEXT,
  run         TEXT,
  job_id      INTEGER REFERENCES jobs(id),
  at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  CHECK (state = 'refused' OR (path IS NOT NULL AND sha256 IS NOT NULL))
);
CREATE INDEX memory_writes_path ON memory_writes(path);
CREATE INDEX memory_writes_job ON memory_writes(job_id);
CREATE TRIGGER memory_writes_no_update BEFORE UPDATE ON memory_writes
  BEGIN SELECT RAISE(ABORT, 'memory_writes is append-only'); END;
CREATE TRIGGER memory_writes_no_delete BEFORE DELETE ON memory_writes
  BEGIN SELECT RAISE(ABORT, 'memory_writes is append-only'); END;
