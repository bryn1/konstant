-- konstant board schema v3: job clones (docs/LEVEL5.md 2.4, wave L5-2). Applied by
-- konstant.board.migrate. A job with sealed holdouts never runs in its project (the TARGET): the
-- first claim records the job's own clone `<project path>@<job id>` and the target commit it is
-- made from. Both are computed by the board at that claim and never change afterwards: the
-- verifier judges the clone, and a later ship moves the target only from that base.

ALTER TABLE jobs ADD COLUMN workdir TEXT;
ALTER TABLE jobs ADD COLUMN workdir_base TEXT;
CREATE TRIGGER jobs_workdir_once BEFORE UPDATE OF workdir, workdir_base ON jobs
  WHEN OLD.workdir IS NOT NULL AND (NEW.workdir IS NOT OLD.workdir
                                    OR NEW.workdir_base IS NOT OLD.workdir_base)
  BEGIN SELECT RAISE(ABORT, 'a job clone is recorded once'); END;
