-- konstant board schema v6: the intake card (wave L5-T; docs/CONCEPTS.md "Triage"). Applied by
-- konstant.board.migrate. Every non-inline task gets an intake card computed by code before any
-- model plans it (konstant/triage/card.py): type, tier, new or continuation, prior work, reuse
-- candidates, and whether a research step is required. A run bound to a job records its card
-- here: append-only, the actor is the token's label (never a request field), the card's own
-- sha256 is recomputed by the board.

CREATE TABLE intake_cards (
  id          INTEGER PRIMARY KEY,
  job_id      INTEGER NOT NULL REFERENCES jobs(id),
  run         TEXT,
  actor       TEXT NOT NULL,
  role        TEXT NOT NULL,
  tier        TEXT NOT NULL CHECK (tier IN ('inline', 'agent', 'fanout', 'max', 'factory')),
  continuation TEXT NOT NULL CHECK (continuation IN ('new', 'continuation')),
  research_required INTEGER NOT NULL CHECK (research_required IN (0, 1)),
  card_json   TEXT NOT NULL,
  sha256      TEXT NOT NULL CHECK (length(sha256) = 64),
  at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX intake_cards_job ON intake_cards(job_id);
CREATE TRIGGER intake_cards_no_update BEFORE UPDATE ON intake_cards
  BEGIN SELECT RAISE(ABORT, 'intake_cards is append-only'); END;
CREATE TRIGGER intake_cards_no_delete BEFORE DELETE ON intake_cards
  BEGIN SELECT RAISE(ABORT, 'intake_cards is append-only'); END;
