from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class PlayerStats:
    player_id: int
    name: str
    wins: int = 0
    plus: int = 0
    minus: int = 0

    @property
    def ga(self) -> int:
        return self.plus - self.minus


def compute_player_ranking(conn: sqlite3.Connection) -> list[PlayerStats]:
    # Load players
    players = conn.execute("SELECT id, name FROM players").fetchall()
    stats = {int(p["id"]): PlayerStats(int(p["id"]), str(p["name"])) for p in players}

    # Helper: team -> players
    rows = conn.execute("SELECT round_team_id, player_id FROM round_team_players").fetchall()
    team_to_players: dict[int, list[int]] = {}
    for r in rows:
        team_to_players.setdefault(int(r["round_team_id"]), []).append(int(r["player_id"]))

    # Matches: count ONLY validated matches
    matches = conn.execute(
        "SELECT team1_id, team2_id, score1, score2 FROM matches WHERE validated=1"
    ).fetchall()

    for m in matches:
        t1 = int(m["team1_id"])
        t2 = m["team2_id"]
        s1 = m["score1"]
        s2 = m["score2"]
        if s1 is None or s2 is None:
            continue

        s1i = int(s1)
        s2i = int(s2)

        p1 = team_to_players.get(t1, [])
        p2 = team_to_players.get(int(t2), []) if t2 is not None else []

        # points (EXEMPT: p2 is empty, that's ok)
        for pid in p1:
            stats[pid].plus += s1i
            stats[pid].minus += s2i
        for pid in p2:
            stats[pid].plus += s2i
            stats[pid].minus += s1i

        # wins
        if t2 is None:
            # EXEMPT counts as a win for team1 (if validated with scores)
            for pid in p1:
                stats[pid].wins += 1
        else:
            if s1i > s2i:
                for pid in p1:
                    stats[pid].wins += 1
            elif s2i > s1i:
                for pid in p2:
                    stats[pid].wins += 1

    # Sort (wins desc, plus desc, ga desc, name)
    result = list(stats.values())
    result.sort(key=lambda x: (-x.wins, -x.plus, -x.ga, x.name.casefold()))
    return result