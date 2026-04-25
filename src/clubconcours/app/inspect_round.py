from __future__ import annotations

import sqlite3

def print_round(conn: sqlite3.Connection, round_id: int) -> None:
    r = conn.execute("SELECT * FROM rounds WHERE id=?", (round_id,)).fetchone()
    print(f"\n=== Round {r['number']} format={r['format']} draw_mode={r['draw_mode']} ===")

    teams = conn.execute(
        """
        SELECT rt.id AS team_id, rt.team_index, p.name
        FROM round_teams rt
        JOIN round_team_players rtp ON rtp.round_team_id = rt.id
        JOIN players p ON p.id = rtp.player_id
        WHERE rt.round_id=?
        ORDER BY rt.team_index, p.name
        """,
        (round_id,),
    ).fetchall()

    team_map: dict[int, dict] = {}
    for row in teams:
        tid = int(row["team_id"])
        team_map.setdefault(tid, {"idx": int(row["team_index"]), "players": []})
        team_map[tid]["players"].append(str(row["name"]))

    for tid, info in sorted(team_map.items(), key=lambda kv: kv[1]["idx"]):
        print(f"Team {info['idx']:>2} (id={tid}): {', '.join(info['players'])}")

    matches = conn.execute(
        """
        SELECT m.id, m.team1_id, m.team2_id, m.score1, m.score2
        FROM matches m
        WHERE m.round_id=?
        ORDER BY m.id
        """,
        (round_id,),
    ).fetchall()

    print("\nMatches:")
    for m in matches:
        t1 = int(m["team1_id"])
        t2 = m["team2_id"]
        s1 = m["score1"]
        s2 = m["score2"]
        if t2 is None:
            print(f"- match {m['id']}: team {team_map[t1]['idx']} EXEMPT  score={s1}-{s2}")
        else:
            print(f"- match {m['id']}: team {team_map[t1]['idx']} vs team {team_map[int(t2)]['idx']}  score={s1}-{s2}")