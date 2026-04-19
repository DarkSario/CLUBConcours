from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

# ---------- Data objects ----------

@dataclass(frozen=True)
class PlayerRow:
    id: int
    name: str

@dataclass(frozen=True)
class RoundRow:
    id: int
    number: int
    format: str
    draw_mode: str
    exempt_mode: str
    exempt_score_for: int | None
    exempt_score_against: int | None
    created_at: str
    drawn: int
    scores_locked: int
    validated: int

# ---------- Players ----------

class PlayerRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add_players(self, names: Iterable[str]) -> list[int]:
        ids: list[int] = []
        for name in names:
            name = name.strip()
            if not name:
                continue
            cur = self.conn.execute("INSERT INTO players(name) VALUES(?)", (name,))
            ids.append(int(cur.lastrowid))
        self.conn.commit()
        return ids

    def list_players(self) -> list[PlayerRow]:
        rows = self.conn.execute("SELECT id, name FROM players ORDER BY name COLLATE NOCASE").fetchall()
        return [PlayerRow(int(r["id"]), str(r["name"])) for r in rows]

# ---------- Rounds / Teams / Matches ----------

class RoundRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_round(
        self,
        number: int,
        format: str,
        draw_mode: str,
        exempt_mode: str = "win_fixed_score",
        exempt_score_for: int = 13,
        exempt_score_against: int = 7,
    ) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            """
            INSERT INTO rounds(number, format, draw_mode, exempt_mode, exempt_score_for, exempt_score_against, created_at, drawn, scores_locked, validated)
            VALUES(?,?,?,?,?,?,?,0,0,0)
            """,
            (number, format, draw_mode, exempt_mode, exempt_score_for, exempt_score_against, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_round(self, round_id: int) -> RoundRow:
        r = self.conn.execute("SELECT * FROM rounds WHERE id=?", (round_id,)).fetchone()
        if not r:
            raise ValueError(f"Round not found: {round_id}")
        return RoundRow(**dict(r))

    def mark_round_drawn(self, round_id: int) -> None:
        self.conn.execute("UPDATE rounds SET drawn=1 WHERE id=?", (round_id,))
        self.conn.commit()

    def create_round_team(self, round_id: int, team_index: int, player_ids: list[int]) -> int:
        cur = self.conn.execute(
            "INSERT INTO round_teams(round_id, team_index) VALUES(?,?)",
            (round_id, team_index),
        )
        team_id = int(cur.lastrowid)
        for pid in player_ids:
            self.conn.execute(
                "INSERT INTO round_team_players(round_team_id, player_id) VALUES(?,?)",
                (team_id, pid),
            )
        return team_id

    def create_match(
        self,
        round_id: int,
        team1_id: int,
        team2_id: Optional[int],
        score1: int | None = None,
        score2: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO matches(round_id, team1_id, team2_id, score1, score2, validated) VALUES(?,?,?,?,?,0)",
            (round_id, team1_id, team2_id, score1, score2),
        )
        return int(cur.lastrowid)

    def commit(self) -> None:
        self.conn.commit()
        
    def lock_scores(self, round_id: int) -> None:
        self.conn.execute("UPDATE rounds SET scores_locked=1 WHERE id=?", (round_id,))
        self.conn.commit()

    def validate_round(self, round_id: int) -> None:
        # Require all scores for non-exempt matches before validation
        missing = self.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM matches
            WHERE round_id = ?
            AND team2_id IS NOT NULL
            AND (score1 IS NULL OR score2 IS NULL)
            """,
            (round_id,),
        ).fetchone()
        if missing and int(missing["c"]) > 0:
            raise ValueError("Impossible de valider : tous les scores ne sont pas saisis (hors exempt).")

        # Validation implies locking scores
        self.conn.execute("UPDATE rounds SET scores_locked=1, validated=1 WHERE id=?", (round_id,))
        self.conn.execute("UPDATE matches SET validated=1 WHERE round_id=?", (round_id,))
        self.conn.commit()
     

# ---------- History / constraints helpers ----------

class HistoryRepo:
    """
    Provides:
      - co-teammate counts (player A played WITH player B)
      - opponent counts (player A played AGAINST player B)
    Based on all matches in DB (you can later restrict to validated rounds only).
    """
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _team_players(self) -> dict[int, list[int]]:
        rows = self.conn.execute(
            "SELECT round_team_id, player_id FROM round_team_players"
        ).fetchall()
        d: dict[int, list[int]] = {}
        for r in rows:
            d.setdefault(int(r["round_team_id"]), []).append(int(r["player_id"]))
        return d

    def teammate_count(self) -> dict[tuple[int, int], int]:
        team_players = self._team_players()
        counts: dict[tuple[int, int], int] = {}
        for players in team_players.values():
            players = sorted(players)
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    a, b = players[i], players[j]
                    counts[(a, b)] = counts.get((a, b), 0) + 1
        return counts

    def opponent_count(self) -> dict[tuple[int, int], int]:
        team_players = self._team_players()
        rows = self.conn.execute(
            "SELECT team1_id, team2_id FROM matches WHERE team2_id IS NOT NULL"
        ).fetchall()
        counts: dict[tuple[int, int], int] = {}
        for r in rows:
            t1 = int(r["team1_id"])
            t2 = int(r["team2_id"])
            p1 = team_players.get(t1, [])
            p2 = team_players.get(t2, [])
            for a in p1:
                for b in p2:
                    x, y = (a, b) if a < b else (b, a)
                    counts[(x, y)] = counts.get((x, y), 0) + 1
        return counts