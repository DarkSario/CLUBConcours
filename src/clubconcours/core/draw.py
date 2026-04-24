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
SWISS_STYLES = {"STRONG", "BALANCED"}

PLAYER_ROLES = {"TIREUR", "PLACEUR", "MIXTE"}


@dataclass(frozen=True)
class RoundConfig:
    format: str  # SINGLE|DOUBLETTE|TRIPLETTE
    draw_mode: str  # RANDOM|AVOID_DUPLICATES|SWISS_BY_WINS
    swiss_style: str = "STRONG"  # STRONG | BALANCED (only used for SWISS_BY_WINS)
    exempt_mode: str = "win_fixed_score"  # none|win_fixed_score
    exempt_score_for: int = 13
    exempt_score_against: int = 7


def _pair_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _team_strength(
    team_players: list[int],
    wins_by_player: dict[int, int],
    plus_by_player: dict[int, int],
) -> int:
    wins = sum(wins_by_player.get(pid, 0) for pid in team_players)
    plus = sum(plus_by_player.get(pid, 0) for pid in team_players)
    return wins * 1000 + plus


def _load_roles(conn: sqlite3.Connection, player_ids: list[int]) -> dict[int, str]:
    if not player_ids:
        return {}
    try:
        q = ",".join(["?"] * len(player_ids))
        rows = conn.execute(f"SELECT id, role FROM players WHERE id IN ({q})", tuple(player_ids)).fetchall()
        out: dict[int, str] = {}
        for r in rows:
            pid = int(r["id"])
            role = str(r["role"] or "MIXTE").upper()
            if role not in PLAYER_ROLES:
                role = "MIXTE"
            out[pid] = role
        for pid in player_ids:
            out.setdefault(int(pid), "MIXTE")
        return out
    except Exception:
        return {int(pid): "MIXTE" for pid in player_ids}


def _role_score(team: list[int], role_by_player: dict[int, str], team_size: int) -> int:
    """
    Lower is better.
    For DOUBLETTE:
      0 = T+P
      5 = (T+M) or (P+M)
      10 = M+M
      50 = T+T or P+P
    For TRIPLETTE:
      0 = has T and P
      10 = has T xor P (but not both)
      30 = only M
    """
    if team_size <= 1:
        return 0

    roles = [role_by_player.get(pid, "MIXTE") for pid in team]
    has_t = any(r == "TIREUR" for r in roles)
    has_p = any(r == "PLACEUR" for r in roles)
    n_m = sum(1 for r in roles if r == "MIXTE")

    if team_size == 2:
        if has_t and has_p:
            return 0
        if (has_t or has_p) and n_m == 1:
            return 5
        if n_m == 2:
            return 10
        return 50

    if has_t and has_p:
        return 0
    if has_t or has_p:
        return 10
    return 30


def _debug_role_stats(
    teams: list[list[int]],
    team_size: int,
    role_by_player: dict[int, str],
    prefix: str,
) -> None:
    """
    Prints role distribution for debugging.
    """
    if not teams:
        print(f"[draw] {prefix}: no teams")
        return

    if team_size == 2:
        tp = tm = pm = mm = tt = pp = 0
        for t in teams:
            if len(t) != 2:
                continue
            r1 = role_by_player.get(t[0], "MIXTE")
            r2 = role_by_player.get(t[1], "MIXTE")
            s = {r1, r2}
            if "TIREUR" in s and "PLACEUR" in s:
                tp += 1
            elif "TIREUR" in s and "MIXTE" in s:
                tm += 1
            elif "PLACEUR" in s and "MIXTE" in s:
                pm += 1
            elif s == {"MIXTE"}:
                mm += 1
            elif s == {"TIREUR"}:
                tt += 1
            elif s == {"PLACEUR"}:
                pp += 1

        print(f"[draw] {prefix} roles (doublette): TP={tp} TM={tm} PM={pm} MM={mm} TT={tt} PP={pp}")

    elif team_size == 3:
        has_tp = t_only = p_only = all_m = 0
        for t in teams:
            if len(t) != 3:
                continue
            roles = [role_by_player.get(pid, "MIXTE") for pid in t]
            has_t = any(r == "TIREUR" for r in roles)
            has_p = any(r == "PLACEUR" for r in roles)
            if has_t and has_p:
                has_tp += 1
            elif has_t and not has_p:
                t_only += 1
            elif has_p and not has_t:
                p_only += 1
            else:
                all_m += 1

        print(
            f"[draw] {prefix} roles (triplette): has(T&P)={has_tp} T_only={t_only} P_only={p_only} all_M={all_m}"
        )
    else:
        print(f"[draw] {prefix}: team_size={team_size} (no role stats)")


def _build_doublettes_role_first(
    player_ids: list[int],
    role_by_player: dict[int, str],
) -> tuple[list[list[int]], Optional[list[int]]]:
    t = [pid for pid in player_ids if role_by_player.get(pid, "MIXTE") == "TIREUR"]
    p = [pid for pid in player_ids if role_by_player.get(pid, "MIXTE") == "PLACEUR"]
    m = [pid for pid in player_ids if role_by_player.get(pid, "MIXTE") == "MIXTE"]

    random.shuffle(t)
    random.shuffle(p)
    random.shuffle(m)

    teams: list[list[int]] = []

    while t and p:
        teams.append([t.pop(), p.pop()])

    while t and m:
        teams.append([t.pop(), m.pop()])
    while p and m:
        teams.append([p.pop(), m.pop()])

    while len(m) >= 2:
        teams.append([m.pop(), m.pop()])

    while len(t) >= 2:
        teams.append([t.pop(), t.pop()])
    while len(p) >= 2:
        teams.append([p.pop(), p.pop()])

    leftovers = t + p + m
    random.shuffle(leftovers)
    exempt_team = leftovers if leftovers else None
    return teams, exempt_team


def _build_triplettes_role_first(
    player_ids: list[int],
    role_by_player: dict[int, str],
) -> tuple[list[list[int]], Optional[list[int]]]:
    t = [pid for pid in player_ids if role_by_player.get(pid, "MIXTE") == "TIREUR"]
    p = [pid for pid in player_ids if role_by_player.get(pid, "MIXTE") == "PLACEUR"]
    m = [pid for pid in player_ids if role_by_player.get(pid, "MIXTE") == "MIXTE"]

    random.shuffle(t)
    random.shuffle(p)
    random.shuffle(m)

    teams: list[list[int]] = []

    while t and p and (m or t or p):
        a = t.pop()
        b = p.pop()
        if m:
            c = m.pop()
        elif t:
            c = t.pop()
        else:
            c = p.pop()
        teams.append([a, b, c])

    while t and len(m) >= 2:
        teams.append([t.pop(), m.pop(), m.pop()])
    while p and len(m) >= 2:
        teams.append([p.pop(), m.pop(), m.pop()])

    while len(m) >= 3:
        teams.append([m.pop(), m.pop(), m.pop()])

    leftovers = t + p + m
    random.shuffle(leftovers)
    while len(leftovers) >= 3:
        teams.append([leftovers.pop(), leftovers.pop(), leftovers.pop()])

    exempt_team = leftovers if leftovers else None
    return teams, exempt_team


def _build_teams_non_swiss(
    player_ids: list[int],
    team_size: int,
    role_by_player: dict[int, str],
) -> tuple[list[list[int]], Optional[list[int]]]:
    if team_size == 1:
        pool = player_ids[:]
        random.shuffle(pool)
        return [[pid] for pid in pool], None
    if team_size == 2:
        return _build_doublettes_role_first(player_ids, role_by_player)
    if team_size == 3:
        return _build_triplettes_role_first(player_ids, role_by_player)
    raise ValueError(f"Unsupported team size: {team_size}")


def _build_teams_role_aware_from_order(
    ordered: list[int],
    team_size: int,
    role_by_player: dict[int, str],
    swiss_style: str,
) -> tuple[list[list[int]], Optional[list[int]]]:
    if team_size == 1:
        return [[pid] for pid in ordered], None

    pool = ordered[:]
    teams: list[list[int]] = []

    if swiss_style == "BALANCED":
        while len(pool) >= team_size:
            if team_size == 2:
                teams.append([pool.pop(0), pool.pop(-1)])
            else:
                a = pool.pop(0)
                b = pool.pop(-1)
                c = pool.pop(-1) if pool else None
                if c is None:
                    break
                teams.append([a, b, c])
    else:
        i = 0
        while i + team_size <= len(pool):
            teams.append(pool[i : i + team_size])
            i += team_size
        pool = pool[i:]

    exempt_team = pool[:] if pool else None

    if team_size in (2, 3) and len(teams) >= 2:
        for _ in range(200):
            improved = False
            for i in range(len(teams) - 1):
                t1 = teams[i]
                t2 = teams[i + 1]
                base = _role_score(t1, role_by_player, team_size) + _role_score(t2, role_by_player, team_size)

                best = base
                best_swap = None

                for a in range(team_size):
                    for b in range(team_size):
                        cand1 = t1[:]
                        cand2 = t2[:]
                        cand1[a], cand2[b] = cand2[b], cand1[a]
                        score = _role_score(cand1, role_by_player, team_size) + _role_score(
                            cand2, role_by_player, team_size
                        )
                        if score < best:
                            best = score
                            best_swap = (a, b)
                            if best == 0:
                                break
                    if best == 0:
                        break

                if best_swap is not None:
                    a, b = best_swap
                    t1[a], t2[b] = t2[b], t1[a]
                    improved = True
            if not improved:
                break

    return teams, exempt_team


def _improve_teams_avoid_duplicates(
    teams: list[list[int]],
    team_size: int,
    role_by_player: dict[int, str],
    teammate_counts: dict[tuple[int, int], int],
    iterations: int = 1200,
) -> list[list[int]]:
    if team_size <= 1 or len(teams) < 2:
        return teams

    def teammate_penalty(team: list[int]) -> int:
        p = 0
        t = sorted(team)
        for i in range(len(t)):
            for j in range(i + 1, len(t)):
                p += teammate_counts.get(_pair_key(t[i], t[j]), 0)
        return p

    cur = [t[:] for t in teams]

    for _ in range(iterations):
        i = random.randrange(len(cur))
        j = random.randrange(len(cur))
        if i == j:
            continue

        a = cur[i][:]
        b = cur[j][:]

        ai = random.randrange(team_size)
        bj = random.randrange(team_size)

        a2 = a[:]
        b2 = b[:]
        a2[ai], b2[bj] = b2[bj], a2[ai]

        role_before = _role_score(a, role_by_player, team_size) + _role_score(b, role_by_player, team_size)
        role_after = _role_score(a2, role_by_player, team_size) + _role_score(b2, role_by_player, team_size)
        if role_after > role_before:
            continue

        pen_before = teammate_penalty(a) + teammate_penalty(b)
        pen_after = teammate_penalty(a2) + teammate_penalty(b2)

        better = pen_after < pen_before or (pen_after == pen_before and role_after < role_before)
        if not better:
            continue

        cur[i] = a2
        cur[j] = b2

    return cur


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
    if cfg.swiss_style.strip().upper() not in SWISS_STYLES:
        raise ValueError(f"Unknown swiss_style: {cfg.swiss_style}")

    team_size = FORMAT_TO_TEAM_SIZE[cfg.format]
    rr = RoundRepo(conn)
    hr = HistoryRepo(conn)

    swiss_style = cfg.swiss_style.strip().upper()

    round_id = rr.create_round(
        number=round_number,
        format=cfg.format,
        draw_mode=cfg.draw_mode,
        exempt_mode=cfg.exempt_mode,
        exempt_score_for=cfg.exempt_score_for,
        exempt_score_against=cfg.exempt_score_against,
    )

    try:
        conn.execute("UPDATE rounds SET swiss_style=? WHERE id=?", (swiss_style, round_id))
        conn.commit()
    except Exception:
        pass

    ranking = compute_player_ranking(conn)
    wins_by_player = {s.player_id: s.wins for s in ranking}
    plus_by_player = {s.player_id: s.plus for s in ranking}

    teammate_counts = hr.teammate_count()
    opponent_counts = hr.opponent_count()

    role_by_player = _load_roles(conn, player_ids)

    def teammate_penalty(team: list[int]) -> int:
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
    if cfg.draw_mode == "SWISS_BY_WINS":
        pool = player_ids[:]
        pool.sort(
            key=lambda pid: (wins_by_player.get(pid, 0), plus_by_player.get(pid, 0)),
            reverse=True,
        )
        teams, exempt_team = _build_teams_role_aware_from_order(pool, team_size, role_by_player, swiss_style)
        _debug_role_stats(teams, team_size, role_by_player, prefix=f"{cfg.draw_mode}/{swiss_style} BEFORE")
    else:
        teams, exempt_team = _build_teams_non_swiss(player_ids, team_size, role_by_player)
        _debug_role_stats(teams, team_size, role_by_player, prefix=f"{cfg.draw_mode} BEFORE")

        if cfg.draw_mode == "AVOID_DUPLICATES":
            teams = _improve_teams_avoid_duplicates(
                teams=teams,
                team_size=team_size,
                role_by_player=role_by_player,
                teammate_counts=teammate_counts,
                iterations=1500,
            )
            _debug_role_stats(teams, team_size, role_by_player, prefix=f"{cfg.draw_mode} AFTER")

    # --- persist teams ---
    team_ids: list[int] = []
    team_players_by_id: dict[int, list[int]] = {}

    for idx, t in enumerate(teams, start=1):
        tid = rr.create_round_team(round_id, idx, t)
        team_ids.append(tid)
        team_players_by_id[tid] = t

    exempt_team_id: Optional[int] = None
    if exempt_team:
        exempt_team_id = rr.create_round_team(round_id, len(teams) + 1, exempt_team)
        team_players_by_id[exempt_team_id] = exempt_team

    # --- pairing ---
    if cfg.draw_mode == "SWISS_BY_WINS":
        team_ids.sort(
            key=lambda tid: (
                -_team_strength(team_players_by_id[tid], wins_by_player, plus_by_player),
                teammate_penalty(team_players_by_id[tid]),
                tid,
            )
        )

        pairs: list[tuple[int, Optional[int]]] = []
        i = 0
        while i + 1 < len(team_ids):
            pairs.append((team_ids[i], team_ids[i + 1]))
            i += 2
        if i < len(team_ids):
            pairs.append((team_ids[i], None))

        for i in range(len(pairs) - 1):
            a1, b1 = pairs[i]
            a2, b2 = pairs[i + 1]
            if b1 is None or b2 is None:
                continue

            base = opponent_penalty(team_players_by_id[a1], team_players_by_id[b1]) + opponent_penalty(
                team_players_by_id[a2], team_players_by_id[b2]
            )
            swap = opponent_penalty(team_players_by_id[a1], team_players_by_id[b2]) + opponent_penalty(
                team_players_by_id[a2], team_players_by_id[b1]
            )
            if swap < base:
                pairs[i] = (a1, b2)
                pairs[i + 1] = (a2, b1)

    else:
        random.shuffle(team_ids)

        def build_pairing_greedy(ids: list[int]) -> list[tuple[int, Optional[int]]]:
            remaining = ids[:]
            pairs: list[tuple[int, Optional[int]]] = []

            while len(remaining) >= 2:
                a = remaining.pop(0)

                best_j: Optional[int] = None
                best_cost: Optional[int] = None

                for j, b in enumerate(remaining):
                    cost = opponent_penalty(team_players_by_id[a], team_players_by_id[b])
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

    if exempt_team_id is not None:
        pairs = [(a, b) for (a, b) in pairs if b is not None]
        pairs.append((exempt_team_id, None))

    # --- persist matches ---
    for (t1, t2) in pairs:
        if t2 is None and cfg.exempt_mode == "win_fixed_score":
            rr.create_match(
                round_id,
                t1,
                None,
                score1=cfg.exempt_score_for,
                score2=cfg.exempt_score_against,
            )
        else:
            rr.create_match(round_id, t1, t2)

    try:
        rr.assign_courts_for_round(round_id)
    except Exception:
        pass

    rr.mark_round_drawn(round_id)
    rr.commit()
    return round_id