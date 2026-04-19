from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from typing import Optional

from clubconcours.core.ranking import compute_player_ranking
from clubconcours.storage.repositories import HistoryRepo, RoundRepo

FORMAT_TO_TEAM_SIZE = {
    "SINGLE": 1,
    "DOUBLETTE": 2,
    "TRIPLETTE": 3,
}

DRAW_MODES = {"RANDOM", "AVOID_DUPLICATES", "SWISS_BY_WINS"}

@dataclass(frozen=True)
class RoundConfig:
    format: str                 # SINGLE|DOUBLETTE|TRIPLETTE
    draw_mode: str              # RANDOM|AVOID_DUPLICATES|SWISS_BY_WINS
    exempt_mode: str = "win_fixed_score"   # none|win_fixed_score
    exempt_score_for: int = 13
    exempt_score_against: int = 7

def _pair_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)

def _team_strength(team_players: list[int], wins_by_player: dict[int, int]) -> int:
    return sum(wins_by_player.get(pid, 0) for pid in team_players)

def draw_round(
    conn: sqlite3.Connection,
    round_number: int,
    cfg: RoundConfig,
    player_ids: list[int],
) -> int:
    if cfg.format not in FORMAT_TO_TEAM_SIZE:
        raise ValueError(f"Unknown format: {cfg.format}")
    if cfg.draw_mode not in DRAW_MODES:
        raise ValueError(f"Unknown draw_mode: {cfg.draw_mode}")

    team_size = FORMAT_TO_TEAM_SIZE[cfg.format]
    rr = RoundRepo(conn)
    hr = HistoryRepo(conn)

    # --- create round row ---
    round_id = rr.create_round(
        number=round_number,
        format=cfg.format,
        draw_mode=cfg.draw_mode,
        exempt_mode=cfg.exempt_mode,
        exempt_score_for=cfg.exempt_score_for,
        exempt_score_against=cfg.exempt_score_against,
    )

    # --- ranking -> wins map for swiss ---
    ranking = compute_player_ranking(conn)
    wins_by_player = {s.player_id: s.wins for s in ranking}

    # --- history penalties (priority=3: teammates + opponents) ---
    teammate_counts = hr.teammate_count()
    opponent_counts = hr.opponent_count()

    def teammate_penalty(team: list[int]) -> int:
        # how many times players in this team already were together
        p = 0
        t = sorted(team)
        for i in range(len(t)):
            for j in range(i + 1, len(t)):
                p += teammate_counts.get(_pair_key(t[i], t[j]), 0)
        return p

    def opponent_penalty(team_a: list[int], team_b: list[int]) -> int:
        p = 0
        for a in team_a:
            for b in team_b:
                p += opponent_counts.get(_pair_key(a, b), 0)
        return p

    # --- build teams ---
    pool = player_ids[:]
    random.shuffle(pool)

    teams: list[list[int]] = []
    while len(pool) >= team_size:
        teams.append([pool.pop() for _ in range(team_size)])

    # leftovers -> exempt "team" (if any)
    exempt_team: Optional[list[int]] = pool[:] if pool else None

    # Improve: avoid repeating teammates (simple greedy improvement)
    # (v1 heuristic: do a few random shuffles and keep best)
    def score_team_set(ts: list[list[int]]) -> int:
        return sum(teammate_penalty(t) for t in ts)

    best = teams
    best_score = score_team_set(best)
    for _ in range(200):  # small search
        cand = [t[:] for t in teams]
        flat = [pid for t in cand for pid in t]
        random.shuffle(flat)
        rebuilt = []
        i = 0
        while i + team_size <= len(flat):
            rebuilt.append(flat[i:i+team_size])
            i += team_size
        s = score_team_set(rebuilt)
        if s < best_score:
            best = rebuilt
            best_score = s
            if best_score == 0:
                break
    teams = best

    # --- persist teams with team_index 1..N ---
    team_ids: list[int] = []
    team_players_by_id: dict[int, list[int]] = {}
    for idx, t in enumerate(teams, start=1):
        tid = rr.create_round_team(round_id, idx, t)
        team_ids.append(tid)
        team_players_by_id[tid] = t

    exempt_team_id: Optional[int] = None
    if exempt_team:
        # Put exempt team at the end (team_index N+1)
        exempt_team_id = rr.create_round_team(round_id, len(teams) + 1, exempt_team)
        team_players_by_id[exempt_team_id] = exempt_team

    # --- ordering for pairing ---
    if cfg.draw_mode == "SWISS_BY_WINS":
        # sort teams by strength desc; tie-break: lower teammate penalty
        team_ids.sort(
            key=lambda tid: (
                -_team_strength(team_players_by_id[tid], wins_by_player),
                teammate_penalty(team_players_by_id[tid]),
                tid,
            )
        )
    else:
        random.shuffle(team_ids)

    # --- pairing teams into matches ---
    def build_pairing_greedy(ids: list[int]) -> list[tuple[int, Optional[int]]]:
        remaining = ids[:]
        pairs: list[tuple[int, Optional[int]]] = []
        while len(remaining) >= 2:
            a = remaining.pop(0)
            best_j = None
            best_cost = None
            for j, b in enumerate(remaining):
                cost = opponent_penalty(team_players_by_id[a], team_players_by_id[b])
                # if swiss: add small cost if strength gap large (soft constraint)
                if cfg.draw_mode == "SWISS_BY_WINS":
                    sa = _team_strength(team_players_by_id[a], wins_by_player)
                    sb = _team_strength(team_players_by_id[b], wins_by_player)
                    cost += abs(sa - sb)
                if best_cost is None or cost < best_cost:
                    best_cost = cost
                    best_j = j
                    if best_cost == 0:
                        break
            b = remaining.pop(best_j)  # type: ignore[arg-type]
            pairs.append((a, b))
        if remaining:
            pairs.append((remaining[0], None))
        return pairs

    pairs = build_pairing_greedy(team_ids)

    # If we have an explicit exempt team (leftovers), we don't want it paired.
    # So: drop any implicit exempt from pairing; add explicit exempt as match with NULL
    if exempt_team_id is not None:
        # remove implicit bye if created by odd number of teams
        pairs = [(a, b) for (a, b) in pairs if b is not None]
        pairs.append((exempt_team_id, None))

    # --- persist matches ---
    for (t1, t2) in pairs:
        rr.create_match(round_id, t1, t2)

    rr.mark_round_drawn(round_id)
    rr.commit()
    return round_id