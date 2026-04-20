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


# ---------- Rounds / Teams / Matches / Courts ----------


class RoundRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- meta settings ----

    def set_num_courts(self, num_courts: int) -> None:
        if num_courts < 1:
            raise ValueError("num_courts must be >= 1")
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('num_courts', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(num_courts),),
        )
        self.conn.commit()

    def get_num_courts(self) -> int:
        row = self.conn.execute("SELECT value FROM meta WHERE key='num_courts'").fetchone()
        if row is None:
            return 12
        try:
            return int(row["value"])
        except Exception:
            return 12

    # ---- rounds ----

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

    # ---- teams ----

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

    # ---- matches ----

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

    def set_match_score(self, match_id: int, score1: int | None, score2: int | None) -> None:
        self.conn.execute(
            "UPDATE matches SET score1=?, score2=? WHERE id=?",
            (score1, score2, match_id),
        )
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    # ---- courts (court_assignments) ----

    def set_match_court(self, match_id: int, court_number: int | None) -> None:
        self.conn.execute(
            """
            INSERT INTO court_assignments(match_id, court_number, validated)
            VALUES(?, ?, 0)
            ON CONFLICT(match_id) DO UPDATE SET court_number=excluded.court_number, validated=0
            """,
            (match_id, court_number),
        )
        self.conn.commit()

    def assign_courts_for_round(self, round_id: int, num_courts: int | None = None) -> None:
        """
        Assign courts (terrains) to matches of a round (excluding exempt).
        Soft constraints:
          - avoid repeating player/court across validated rounds
          - help players who never played on a court in 1..12 get one
        """
        if num_courts is None:
            num_courts = self.get_num_courts()
        if num_courts < 1:
            raise ValueError("num_courts must be >= 1")

        r = self.conn.execute("SELECT scores_locked, validated FROM rounds WHERE id=?", (round_id,)).fetchone()
        if not r:
            raise ValueError(f"Round not found: {round_id}")
        if int(r["scores_locked"]) == 1 or int(r["validated"]) == 1:
            raise ValueError("Round is locked/validated; unlock it to re-assign courts.")

        matches = self.conn.execute(
            """
            SELECT id, team1_id, team2_id
            FROM matches
            WHERE round_id=? AND team2_id IS NOT NULL
            ORDER BY id
            """,
            (round_id,),
        ).fetchall()
        if not matches:
            return

        # team -> players (for this round)
        team_rows = self.conn.execute(
            """
            SELECT rtp.round_team_id AS team_id, rtp.player_id AS player_id
            FROM round_team_players rtp
            JOIN round_teams rt ON rt.id = rtp.round_team_id
            WHERE rt.round_id=?
            """,
            (round_id,),
        ).fetchall()

        team_players: dict[int, list[int]] = {}
        for tr in team_rows:
            tid = int(tr["team_id"])
            team_players.setdefault(tid, []).append(int(tr["player_id"]))

        # History: player -> courts already played on (validated rounds only)
        hist_rows = self.conn.execute(
            """
            SELECT rtp.player_id AS player_id, ca.court_number AS court_number
            FROM court_assignments ca
            JOIN matches m ON m.id = ca.match_id
            JOIN rounds r ON r.id = m.round_id
            JOIN round_team_players rtp ON rtp.round_team_id IN (m.team1_id, m.team2_id)
            WHERE r.validated=1
              AND m.team2_id IS NOT NULL
              AND ca.court_number IS NOT NULL
            """
        ).fetchall()

        played: dict[int, set[int]] = {}
        for hr in hist_rows:
            pid = int(hr["player_id"])
            cn = int(hr["court_number"])
            played.setdefault(pid, set()).add(cn)

        prio_courts = set(range(1, 13))  # terrains 1..12

        def player_needs_prio(pid: int) -> bool:
            return len(played.get(pid, set()).intersection(prio_courts)) == 0

        import random

        courts = list(range(1, num_courts + 1))
        match_list = [dict(m) for m in matches]
        random.shuffle(match_list)  # keep it "tiré"

        used_this_round: set[int] = set()

        for m in match_list:
            mid = int(m["id"])
            t1 = int(m["team1_id"])
            t2 = int(m["team2_id"])
            pids = team_players.get(t1, []) + team_players.get(t2, [])

            best_court = None
            best_cost = None

            candidates = courts[:]
            random.shuffle(candidates)

            for c in candidates:
                cost = 0

                # small penalty if already used this round (encourage spreading)
                if c in used_this_round:
                    cost += 5

                # big penalty if player already played on that court
                for pid in pids:
                    if c in played.get(pid, set()):
                        cost += 1000

                # bonus if a player needs to get at least one court among 1..12
                if c in prio_courts:
                    for pid in pids:
                        if player_needs_prio(pid):
                            cost -= 50

                if best_cost is None or cost < best_cost:
                    best_cost = cost
                    best_court = c
                    if best_cost <= -50:
                        break

            assert best_court is not None
            used_this_round.add(best_court)

            self.conn.execute(
                """
                INSERT INTO court_assignments(match_id, court_number, validated)
                VALUES(?, ?, 0)
                ON CONFLICT(match_id) DO UPDATE SET court_number=excluded.court_number, validated=0
                """,
                (mid, best_court),
            )

        self.conn.commit()

    # ---- lock / validate / unlock ----

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

        # Require court assignment for non-exempt matches
        missing_court = self.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM matches m
            LEFT JOIN court_assignments ca ON ca.match_id = m.id
            WHERE m.round_id = ?
              AND m.team2_id IS NOT NULL
              AND ca.court_number IS NULL
            """,
            (round_id,),
        ).fetchone()
        if missing_court and int(missing_court["c"]) > 0:
            raise ValueError("Impossible de valider : il manque des terrains pour certains matchs.")

        # Validation implies locking scores AND courts
        self.conn.execute("UPDATE rounds SET scores_locked=1, validated=1 WHERE id=?", (round_id,))
        self.conn.execute("UPDATE matches SET validated=1 WHERE round_id=?", (round_id,))
        self.conn.execute(
            """
            UPDATE court_assignments
            SET validated=1
            WHERE match_id IN (SELECT id FROM matches WHERE round_id=?)
            """,
            (round_id,),
        )
        self.conn.commit()

    def unlock_round(self, round_id: int) -> None:
        # Unlock everything (scores + courts)
        self.conn.execute("UPDATE rounds SET scores_locked=0, validated=0 WHERE id=?", (round_id,))
        self.conn.execute("UPDATE matches SET validated=0 WHERE round_id=?", (round_id,))
        self.conn.execute(
            """
            UPDATE court_assignments
            SET validated=0
            WHERE match_id IN (SELECT id FROM matches WHERE round_id=?)
            """,
            (round_id,),
        )
        self.conn.commit()


# ---------- History / constraints helpers ----------


class HistoryRepo:
    """
    Provides:
      - co-teammate counts (player A played WITH player B)
      - opponent counts (player A played AGAINST player B)
    Based on VALIDATED rounds only (more stable for tournament logic).
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _team_players_validated(self) -> dict[int, list[int]]:
        rows = self.conn.execute(
            """
            SELECT rtp.round_team_id, rtp.player_id
            FROM round_team_players rtp
            JOIN round_teams rt ON rt.id = rtp.round_team_id
            JOIN rounds r ON r.id = rt.round_id
            WHERE r.validated=1
            """
        ).fetchall()
        d: dict[int, list[int]] = {}
        for r in rows:
            d.setdefault(int(r["round_team_id"]), []).append(int(r["player_id"]))
        return d

    def teammate_count(self) -> dict[tuple[int, int], int]:
        team_players = self._team_players_validated()
        counts: dict[tuple[int, int], int] = {}
        for players in team_players.values():
            players = sorted(players)
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    a, b = players[i], players[j]
                    counts[(a, b)] = counts.get((a, b), 0) + 1
        return counts

    def opponent_count(self) -> dict[tuple[int, int], int]:
        team_players = self._team_players_validated()
        rows = self.conn.execute(
            """
            SELECT m.team1_id, m.team2_id
            FROM matches m
            JOIN rounds r ON r.id = m.round_id
            WHERE r.validated=1 AND m.team2_id IS NOT NULL
            """
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