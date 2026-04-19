PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  number INTEGER NOT NULL,
  format TEXT NOT NULL,          -- SINGLE | DOUBLETTE | TRIPLETTE
  draw_mode TEXT NOT NULL,       -- RANDOM | AVOID_DUPLICATES | SWISS_BY_WINS
  exempt_mode TEXT NOT NULL,     -- none | win_fixed_score
  exempt_score_for INTEGER,      -- default 13
  exempt_score_against INTEGER,  -- default 7
  created_at TEXT NOT NULL,
  drawn INTEGER NOT NULL DEFAULT 0,
  scores_locked INTEGER NOT NULL DEFAULT 0,
  validated INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS round_teams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER NOT NULL,
  team_index INTEGER NOT NULL,
  FOREIGN KEY(round_id) REFERENCES rounds(id) ON DELETE CASCADE,
  UNIQUE(round_id, team_index)
);

CREATE TABLE IF NOT EXISTS round_team_players (
  round_team_id INTEGER NOT NULL,
  player_id INTEGER NOT NULL,
  PRIMARY KEY(round_team_id, player_id),
  FOREIGN KEY(round_team_id) REFERENCES round_teams(id) ON DELETE CASCADE,
  FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER NOT NULL,
  team1_id INTEGER NOT NULL,
  team2_id INTEGER,      -- NULL => exempt
  score1 INTEGER,
  score2 INTEGER,
  validated INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(round_id) REFERENCES rounds(id) ON DELETE CASCADE,
  FOREIGN KEY(team1_id) REFERENCES round_teams(id) ON DELETE CASCADE,
  FOREIGN KEY(team2_id) REFERENCES round_teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS court_assignments (
  match_id INTEGER PRIMARY KEY,
  court_number INTEGER,
  validated INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_matches_round_id ON matches(round_id);
CREATE INDEX IF NOT EXISTS idx_round_teams_round_id ON round_teams(round_id);